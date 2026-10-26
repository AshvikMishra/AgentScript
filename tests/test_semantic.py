"""Semantic analysis tests: scopes, shadowing, types, permissions, returns and the budget."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from agentscript import ast_nodes as ast
from agentscript.diagnostics import CompileError
from agentscript.lexer import tokenize
from agentscript.parser import parse
from agentscript.semantic import BudgetInfo, Scope, SemanticResult, Symbol, analyze
from agentscript.typesys import BOOL, INT, STRING, list_of

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
ALL_TOOLS = "web_search, read_file, llm, send_email, delete_file, sanitize, confirm"


def parse_src(source: str) -> ast.Agent:
    return parse(tokenize(source))


def program(
    body: str,
    ret: str = "int",
    params: str = "",
    permit: str = ALL_TOOLS,
    budget: int = 100,
    extra: str = "",
) -> str:
    """One agent with task `t`; `body` starts on line 5, `extra` holds more tasks."""
    return (
        "agent A {\n"
        f"  permit {permit};\n"
        f"  budget calls = {budget};\n"
        f"  task t({params}) -> {ret} {{\n"
        f"{body}\n"
        "  }\n"
        f"{extra}"
        "}\n"
    )


def check(source: str) -> SemanticResult:
    return analyze(parse_src(source))


def error_of(source: str) -> tuple[str, int, int, str]:
    with pytest.raises(CompileError) as info:
        check(source)
    d = info.value.diagnostic
    assert d.phase == "semantic" and d.severity == "error"
    return d.code, d.line, d.col, d.message


def assert_error(source: str, code: str, line: int, col: int) -> str:
    got = error_of(source)
    assert got[:3] == (code, line, col), got
    return got[3]


def all_exprs(node: object) -> list[ast.Expr]:
    found: list[ast.Expr] = []
    if isinstance(node, list):
        for n in node:
            found.extend(all_exprs(n))
    elif is_dataclass(node):
        if isinstance(node, ast.Expr):
            found.append(node)
        for f in fields(node):
            found.extend(all_exprs(getattr(node, f.name)))
    return found


def expr_type(expr_src: str, params: str = "", ret: str = "int"):
    agent = parse_src(program(f"    let v = {expr_src};\n    return 0;", params=params, ret=ret))
    analyze(agent)
    return agent.tasks[0].body.statements[0].value.type


# ------------------------------------------------------------- examples


SEMANTIC_ERRORS = [e for e in MANIFEST if e["expect"] and e["expect"]["code"].startswith("E3")]
PASSING = [e for e in MANIFEST if not (e["expect"] and e["expect"]["phase"] in ("lexer", "parser", "semantic"))]


def test_manifest_has_every_semantic_error():
    assert sorted(e["expect"]["code"] for e in SEMANTIC_ERRORS) == [
        "E301", "E302", "E303", "E304", "E305", "E306",
    ]


@pytest.mark.parametrize("entry", SEMANTIC_ERRORS, ids=lambda e: e["file"])
def test_semantic_error_examples(entry):
    exp = entry["expect"]
    source = (EXAMPLES / entry["file"]).read_text(encoding="utf-8")
    assert_error(source, exp["code"], exp["line"], exp["col"])


@pytest.mark.parametrize("entry", PASSING, ids=lambda e: e["file"])
def test_other_examples_pass(entry):
    result = check((EXAMPLES / entry["file"]).read_text(encoding="utf-8"))
    got = [(w.code, w.phase, w.line, w.col) for w in result.warnings]
    want = [(w["code"], w["phase"], w["line"], w["col"]) for w in entry["warnings"]]
    assert got == want


def test_runtime_budget_warning():
    result = check((EXAMPLES / "runtime_budget.as").read_text(encoding="utf-8"))
    assert len(result.warnings) == 1
    w = result.warnings[0]
    assert (w.code, w.severity, w.line, w.col) == ("W306", "warning", 6, 12)
    assert w.message == (
        "repeat count 'times' is not a literal; the budget for this loop is enforced at runtime"
    )
    info = result.budget["poll"]
    assert info.dynamic_loops and info.worst_path_calls == 1


def test_valid_report_budget_and_symbols():
    result = check((EXAMPLES / "valid_report.as").read_text(encoding="utf-8"))
    info = result.budget["report"]
    assert isinstance(info, BudgetInfo)
    assert (info.task, info.worst_path_calls, info.budget, info.dynamic_loops) == ("report", 5, 5, False)
    assert info.call_sites == [
        ("web_search", 6, 15), ("sanitize", 7, 17), ("llm", 8, 19),
        ("confirm", 9, 9), ("send_email", 10, 14),
    ]
    assert result.permits == ["web_search", "llm", "sanitize", "send_email", "confirm"]
    assert result.warnings == []


def test_budget_example_path():
    with pytest.raises(CompileError) as info:
        check((EXAMPLES / "sem_budget.as").read_text(encoding="utf-8"))
    d = info.value.diagnostic
    assert d.message == "task 'dig' may make 4 tool calls on its worst path, but the budget is 3"
    assert [(s.line, s.col) for s in d.path] == [(6, 13), (7, 13), (8, 13), (9, 12)]
    assert d.path[0].note == "call 1: web_search"
    assert d.path[3].note.startswith("call 4: llm")


def test_every_expression_is_typed_in_examples():
    for entry in PASSING:
        agent = parse_src((EXAMPLES / entry["file"]).read_text(encoding="utf-8"))
        analyze(agent)
        exprs = all_exprs(agent)
        assert exprs and all(e.type is not None for e in exprs), entry["file"]


# ------------------------------------------------------------ scopes


def test_scope_tree_shape():
    src = program(
        "    let a = p;\n"
        "    if (true) { let b = 1; } else { let c = 2; }\n"
        "    repeat 2 { let d = 3; }\n"
        "    return a;",
        params="p: int",
    )
    root = check(src).root_scope
    assert isinstance(root, Scope) and root.kind == "builtins" and root.parent is None
    assert [s.kind for s in root.symbols.values()] == ["tool"] * 7
    (agent_scope,) = root.children
    assert (agent_scope.kind, agent_scope.name) == ("agent", "A")
    assert agent_scope.symbols["t"].kind == "task"
    (task_scope,) = agent_scope.children
    assert task_scope.kind == "task" and list(task_scope.symbols) == ["p"]
    (body,) = task_scope.children
    assert body.kind == "block" and list(body.symbols) == ["a"]
    assert [list(c.symbols) for c in body.children] == [["b"], ["c"], ["d"]]
    assert all(c.parent is body for c in body.children)
    sym = body.symbols["a"]
    assert isinstance(sym, Symbol)
    assert (sym.name, sym.kind, sym.type, sym.line, sym.col, sym.scope) == ("a", "variable", INT, 5, 9, body.name)


def test_lookup_walks_outward():
    root = Scope("builtins", "builtins")
    root.declare(Symbol("x", "variable", INT, 1, 1, ""))
    inner = root.child("block", "b").child("block", "c")
    assert inner.lookup("x") is root.symbols["x"]
    assert inner.lookup("nope") is None


def test_sibling_scopes_may_reuse_names():
    src = program(
        "    if (true) { let x = 1; } else { let x = \"s\"; }\n"
        "    repeat 2 { let x = true; }\n"
        "    let x = 5;\n"
        "    return x;"
    )
    check(src)


def test_tasks_have_separate_scopes():
    extra = "  task u(p: int) -> int {\n    let a = p;\n    return a;\n  }\n"
    check(program("    let a = 1;\n    return a;", params="p: int", extra=extra))


def test_shadowing_in_nested_block_rejected():
    assert_error(program("    let x = 1;\n    if (true) {\n      let x = 2;\n    }\n    return x;"), "E302", 7, 11)


def test_let_shadowing_param_rejected():
    msg = assert_error(program("    let p = 1;\n    return p;", params="p: int"), "E302", 5, 9)
    assert "param" in msg


def test_duplicate_param():
    assert_error(program("    return 1;", params="a: int, a: string"), "E302", 4, 18)


def test_param_named_like_tool_or_task():
    assert_error(program("    return 1;", params="llm: int"), "E302", 4, 10)
    assert_error(program("    return 1;", params="t: int"), "E302", 4, 10)


def test_variable_named_like_tool_rejected():
    msg = assert_error(program("    let web_search = 1;\n    return 1;"), "E302", 5, 9)
    assert "built-in tool" in msg


def test_variable_named_like_task_rejected():
    extra = "  task later() -> int {\n    return 1;\n  }\n"
    assert_error(program("    let later = 1;\n    return 1;", extra=extra), "E302", 5, 9)


def test_duplicate_task():
    extra = "  task t() -> int {\n    return 2;\n  }\n"
    assert_error(program("    return 1;", extra=extra), "E302", 7, 3)


def test_task_named_like_tool():
    src = "agent A {\n  permit llm;\n  budget calls = 1;\n  task llm() -> int {\n    return 1;\n  }\n}\n"
    assert_error(src, "E302", 4, 3)


def test_permit_unknown_and_duplicate():
    assert_error(program("    return 1;", permit="llm, fly"), "E301", 2, 15)
    assert_error(program("    return 1;", permit="llm, web_search, llm"), "E302", 2, 27)
    src = "agent A {\n  permit llm;\n  permit llm;\n  budget calls = 1;\n  task t() -> int {\n    return 1;\n  }\n}\n"
    assert_error(src, "E302", 3, 10)


# ---------------------------------------------------------- names, E301


def test_undeclared_and_let_self_reference():
    assert_error(program("    return y;"), "E301", 5, 12)
    assert_error(program("    let x = x;\n    return 1;"), "E301", 5, 13)


def test_use_before_declaration():
    assert_error(program("    let a = b;\n    let b = 1;\n    return a;"), "E301", 5, 13)


def test_variable_out_of_scope_after_block():
    assert_error(program("    if (true) { let x = 1; }\n    return x;"), "E301", 6, 12)


def test_tool_name_as_variable():
    msg = assert_error(program("    return llm;", ret="string"), "E301", 5, 12)
    assert "tool" in msg


def test_task_name_as_variable():
    msg = assert_error(program("    return t;"), "E301", 5, 12)
    assert "task" in msg


def test_unknown_tool_and_task_call():
    assert_error(program("    return fly(1);"), "E301", 5, 12)
    msg = assert_error(program("    return t();"), "E301", 5, 12)
    assert "task" in msg


def test_calling_a_variable():
    assert_error(program("    let f = 1;\n    return f(2);"), "E301", 6, 12)


def test_repeat_count_names():
    assert_error(program("    repeat n { }\n    return 1;"), "E301", 5, 12)
    assert_error(program("    repeat llm { }\n    return 1;"), "E301", 5, 12)


# ------------------------------------------------------------ calls


def test_not_permitted():
    assert_error(program("    return llm(\"x\");", ret="string", permit="web_search"), "E305", 5, 12)


def test_callee_checked_before_arguments():
    # E305 wins over the bad argument; the argument is not even looked at.
    assert_error(program("    return llm(zzz);", ret="string", permit="web_search"), "E305", 5, 12)
    assert_error(program("    return fly(zzz);"), "E301", 5, 12)


def test_arguments_checked_before_arity():
    assert_error(program("    return send_email(zzz);", ret="bool"), "E301", 5, 23)


def test_arity():
    msg = assert_error(program("    return send_email(\"a\");", ret="bool"), "E303", 5, 12)
    assert "2 arguments" in msg and "found 1" in msg
    assert_error(program("    return llm(\"a\", \"b\");", ret="string"), "E303", 5, 12)
    assert_error(program("    return llm();", ret="string"), "E303", 5, 12)


def test_argument_type_at_offending_argument():
    msg = assert_error(program("    return send_email(\"a\", 3);", ret="bool"), "E303", 5, 28)
    assert "argument 2" in msg
    assert_error(program("    return llm(web_search(\"q\"));", ret="string"), "E303", 5, 16)


def test_call_result_types():
    assert expr_type("web_search(\"q\")") == list_of(STRING)
    assert expr_type("read_file(\"f\")") == STRING
    assert expr_type("send_email(\"a\", \"b\")") == BOOL
    assert expr_type("confirm(\"ok?\")") == BOOL
    assert expr_type("llm(sanitize(read_file(\"f\")))") == STRING


# -------------------------------------------------------- operators


@pytest.mark.parametrize(
    "src,expected",
    [
        ("1 + 2", INT),
        ("\"a\" + \"b\"", STRING),
        ("3 - 1", INT),
        ("3 * 2", INT),
        ("1 < 2", BOOL),
        ("1 <= 2", BOOL),
        ("1 > 2", BOOL),
        ("1 >= 2", BOOL),
        ("1 == 2", BOOL),
        ("\"a\" != \"b\"", BOOL),
        ("true == false", BOOL),
        ("(1 < 2) != (3 < 4)", BOOL),
        ("1 + 2 * 3 - 4", INT),
    ],
)
def test_operator_results(src, expected):
    assert expr_type(src) == expected


@pytest.mark.parametrize(
    "src,col",
    [
        ("1 + \"a\"", 15),
        ("\"a\" + 1", 17),
        ("true + true", 18),
        ("\"a\" - \"b\"", 17),
        ("\"a\" * 2", 17),
        ("true * 1", 18),
        ("\"a\" < \"b\"", 17),
        ("true <= false", 18),
        ("1 > true", 15),
        ("\"a\" >= 1", 17),
        ("1 == \"a\"", 15),
        ("true != 1", 18),
        ("l == l", 15),
        ("l + l", 15),
    ],
)
def test_operator_mismatches(src, col):
    source = program(f"    let v = {src};\n    return 0;", params="l: list<int>")
    msg = assert_error(source, "E303", 5, col)
    assert "operator" in msg


def test_operator_error_reports_innermost_first():
    # `1 + "a"` is checked before the outer `*`.
    assert_error(program("    let v = (1 + \"a\") * 2;\n    return 0;"), "E303", 5, 16)


# ------------------------------------------------------------ index


def test_index_types():
    assert expr_type("l[0]", params="l: list<string>") == STRING
    assert expr_type("m[0]", params="m: list<list<string>>") == list_of(STRING)
    assert expr_type("m[0][1]", params="m: list<list<string>>") == STRING
    assert expr_type("m[1 + 1][0] + \"x\"", params="m: list<list<string>>") == STRING
    assert expr_type("web_search(\"q\")[2]") == STRING


def test_index_errors():
    src = program("    let v = s[0];\n    return 0;", params="s: string")
    assert "indexed" in assert_error(src, "E303", 5, 14)
    src = program("    let v = l[\"a\"];\n    return 0;", params="l: list<int>")
    assert_error(src, "E303", 5, 15)
    src = program("    let v = m[0][0][0];\n    return 0;", params="m: list<list<int>>")
    assert_error(src, "E303", 5, 20)


# ---------------------------------------------------------- statements


def test_if_condition_must_be_bool():
    assert_error(program("    if (1) { }\n    return 0;"), "E303", 5, 9)
    assert_error(program("    if (\"a\" + \"b\") { }\n    return 0;"), "E303", 5, 13)
    check(program("    if (confirm(\"go?\")) { }\n    return 0;"))


def test_repeat_count():
    check(program("    repeat 3 { }\n    return 0;"))
    check(program("    repeat n { }\n    return 0;", params="n: int"))
    assert_error(program("    repeat s { }\n    return 0;", params="s: string"), "E303", 5, 12)
    assert_error(program("    repeat b { }\n    return 0;", params="b: bool"), "E303", 5, 12)


def test_return_type():
    msg = assert_error(program("    return \"a\";"), "E303", 5, 12)
    assert "returns int" in msg
    assert_error(program("    return web_search(\"q\");", ret="list<int>"), "E303", 5, 12)
    assert_error(program("    if (true) { return 1 < 2; }\n    return 0;"), "E303", 5, 26)
    check(program("    return web_search(\"q\");", ret="list<string>"))
    check(program("    return l;", ret="list<list<int>>", params="l: list<list<int>>"))


def test_statements_after_return_are_checked():
    assert_error(program("    return 1;\n    return \"a\";"), "E303", 6, 12)
    check(program("    return 1;\n    let x = 2;"))


def test_expression_statements():
    result = check(program("    llm(\"hi\");\n    1 + 2;\n    return 0;"))
    assert result.budget["t"].worst_path_calls == 1


# ------------------------------------------------------- missing return


def test_missing_return_variants():
    assert_error(program("    let x = 1;"), "E304", 6, 3)
    assert_error(program(""), "E304", 6, 3)
    assert_error(program("    if (true) { return 1; }"), "E304", 6, 3)
    assert_error(program("    if (true) { return 1; } else { let a = 1; }"), "E304", 6, 3)
    assert_error(program("    repeat 3 { return 1; }"), "E304", 6, 3)
    assert_error(
        program("    if (true) { if (false) { return 1; } } else { return 2; }"), "E304", 6, 3
    )


def test_returning_on_every_path():
    check(program("    if (true) { return 1; } else { return 2; }"))
    check(program("    if (true) { if (false) { return 1; } else { return 3; } } else { return 2; }"))
    check(program("    if (true) { let a = 1; }\n    return 2;"))
    check(program("    repeat 2 { return 1; }\n    return 0;"))


def test_missing_return_in_second_task():
    extra = "  task u() -> bool {\n    let a = 1;\n  }\n"
    assert_error(program("    return 1;", extra=extra), "E304", 9, 3)


# --------------------------------------------------------------- order


def test_first_error_in_source_order():
    assert_error(program("    let a = y;\n    return \"x\";"), "E301", 5, 13)
    assert_error(program("    return \"x\";\n    let a = y;"), "E303", 5, 12)


def test_walk_errors_win_over_budget():
    src = program("    llm(\"a\");\n    llm(\"b\");\n    return y;", budget=1)
    assert_error(src, "E301", 7, 12)


# -------------------------------------------------------------- budget


def calls_of(body: str, **kw) -> BudgetInfo:
    return check(program(body, **kw)).budget["t"]


def test_budget_counts_nested_calls_in_eval_order():
    info = calls_of("    return llm(sanitize(read_file(\"f\")) + llm(\"x\"));", ret="string")
    assert info.worst_path_calls == 4
    assert [t for t, _, _ in info.call_sites] == ["read_file", "sanitize", "llm", "llm"]
    assert info.call_sites[-1] == ("llm", 5, 12)


def test_budget_if_takes_longer_branch():
    body = (
        "    if (confirm(\"a\")) {\n      llm(\"1\");\n    } else {\n"
        "      llm(\"2\");\n      llm(\"3\");\n    }\n    return 0;"
    )
    info = calls_of(body)
    assert info.worst_path_calls == 3
    assert [ln for _, ln, _ in info.call_sites] == [5, 8, 9]


def test_budget_if_tie_takes_then_and_missing_else_is_zero():
    info = calls_of("    if (true) { llm(\"a\"); } else { llm(\"b\"); }\n    return 0;")
    assert info.call_sites == [("llm", 5, 17)]
    info = calls_of("    if (true) { llm(\"a\"); llm(\"b\"); }\n    return 0;")
    assert info.worst_path_calls == 2


def test_budget_repeat_literal_multiplies():
    info = calls_of("    repeat 3 { llm(\"a\"); sanitize(\"b\"); }\n    return 0;")
    assert info.worst_path_calls == 6
    assert [t for t, _, _ in info.call_sites] == ["llm", "sanitize"] * 3
    assert not info.dynamic_loops
    assert calls_of("    repeat 0 { llm(\"a\"); }\n    return 0;").worst_path_calls == 0
    nested = calls_of("    repeat 2 { repeat 3 { llm(\"a\"); } llm(\"b\"); }\n    return 0;")
    assert nested.worst_path_calls == 8


def test_budget_repeat_variable_counted_once_with_warning():
    result = check(program("    repeat n { repeat 2 { llm(\"a\"); } }\n    return 0;", params="n: int"))
    info = result.budget["t"]
    assert info.worst_path_calls == 2 and info.dynamic_loops
    assert [(w.code, w.line, w.col) for w in result.warnings] == [("W306", 5, 12)]


def test_budget_warning_for_each_dynamic_loop_in_branches():
    body = "    if (true) { repeat n { } } else { repeat n { } }\n    repeat 2 { repeat n { } }\n    return 0;"
    result = check(program(body, params="n: int"))
    assert [(w.line, w.col) for w in result.warnings] == [(5, 24), (5, 46), (6, 23)]


def test_budget_exceeded_at_budget_plus_one_call():
    body = "    repeat 2 { llm(\"a\"); sanitize(\"b\"); }\n    return 0;"
    code, line, col, msg = error_of(program(body, budget=3))
    assert (code, line, col) == ("E306", 5, 26)
    assert msg == "task 't' may make 4 tool calls on its worst path, but the budget is 3"


def test_budget_zero():
    assert_error(program("    return llm(\"a\");", ret="string", budget=0), "E306", 5, 12)
    assert calls_of("    return 1;", budget=0).worst_path_calls == 0


def test_budget_exact_fit_ok():
    assert calls_of("    llm(\"a\");\n    return 0;", budget=1).worst_path_calls == 1


def test_budget_in_condition_counts():
    info = calls_of("    if (confirm(llm(\"a\")) == true) { }\n    return 0;")
    assert [t for t, _, _ in info.call_sites] == ["llm", "confirm"]


def test_budget_huge_repeat_is_not_materialized():
    body = "    repeat 1000000000 { llm(\"a\"); }\n    return 0;"
    with pytest.raises(CompileError) as info:
        check(program(body, budget=5))
    d = info.value.diagnostic
    assert (d.code, d.line, d.col) == ("E306", 5, 25)
    assert "1000000000 tool calls" in d.message
    assert len(d.path) <= 102


def test_budget_checked_per_task_in_order():
    extra = "  task u() -> int {\n    llm(\"a\");\n    llm(\"b\");\n    return 0;\n  }\n"
    src = program("    llm(\"a\");\n    return 0;", budget=1, extra=extra)
    code, line, col, msg = error_of(src)
    assert (code, line, col) == ("E306", 10, 5) and "task 'u'" in msg
    result = check(program("    llm(\"a\");\n    return 0;", budget=2, extra=extra))
    assert [(i.task, i.worst_path_calls) for i in result.budget.values()] == [("t", 1), ("u", 2)]


# ---------------------------------------------------------------- types


def test_expr_types_annotated():
    src = program(
        "    let r = web_search(q);\n"
        "    let first = r[0] + \"!\";\n"
        "    if (len_ok == (1 < 2)) { repeat n { llm(first); } }\n"
        "    return first;",
        ret="string",
        params="q: string, n: int, len_ok: bool",
    )
    agent = parse_src(src)
    analyze(agent)
    exprs = all_exprs(agent)
    assert all(e.type is not None for e in exprs)
    stmts = agent.tasks[0].body.statements
    assert stmts[0].value.type == list_of(STRING)
    assert stmts[0].value.args[0].type == STRING
    assert stmts[1].value.left.type == STRING and stmts[1].value.left.base.type == list_of(STRING)
    assert stmts[1].value.left.index.type == INT
    assert stmts[2].cond.type == BOOL and stmts[2].cond.right.type == BOOL
    assert stmts[2].then_block.statements[0].count.type == INT


def test_let_infers_type_into_symbol():
    root = check(program("    let r = web_search(\"q\");\n    return 0;")).root_scope
    body = root.children[0].children[0].children[0]
    assert body.symbols["r"].type == list_of(STRING)


# ------------------------------------------------------------- artifact


def test_artifact_text_and_data():
    result = check((EXAMPLES / "valid_report.as").read_text(encoding="utf-8"))
    art = result.artifact()
    assert set(art) == {"text", "data"}
    text = art["text"]
    assert "builtins" in text and "agent Assistant" in text and "task report" in text
    assert "raw" in text and "list<string>" in text and "6:9" in text
    assert "Permitted tools: web_search, llm, sanitize, send_email, confirm" in text
    assert "web_search@6:15 -> sanitize@7:17" in text
    data = art["data"]
    json.dumps(data)
    assert data["permits"] == result.permits
    assert data["scopes"]["kind"] == "builtins"
    assert len(data["scopes"]["symbols"]) == 7
    agent_scope = data["scopes"]["children"][0]
    assert agent_scope["symbols"][0] == {
        "name": "report", "kind": "task", "type": "(string) -> bool", "line": 5, "col": 3,
    }
    body = agent_scope["children"][0]["children"][0]
    assert {"name": "raw", "kind": "variable", "type": "list<string>", "line": 6, "col": 9} in body["symbols"]
    assert data["budget"] == [
        {
            "task": "report", "worst_path_calls": 5, "budget": 5, "dynamic_loops": False,
            "call_sites": [
                {"tool": "web_search", "line": 6, "col": 15},
                {"tool": "sanitize", "line": 7, "col": 17},
                {"tool": "llm", "line": 8, "col": 19},
                {"tool": "confirm", "line": 9, "col": 9},
                {"tool": "send_email", "line": 10, "col": 14},
            ],
        }
    ]
    assert data["warnings"] == []


def test_artifact_includes_warnings():
    art = check((EXAMPLES / "runtime_budget.as").read_text(encoding="utf-8")).artifact()
    assert "W306" in art["text"]
    assert art["data"]["warnings"][0]["code"] == "W306"


def test_analysis_is_deterministic():
    src = (EXAMPLES / "valid_report.as").read_text(encoding="utf-8")
    assert check(src).artifact() == check(src).artifact()


def test_duplicate_task_does_not_hide_an_earlier_error():
    # source order, first error wins: the E301 in the first task body comes before the
    # duplicate task name
    src = "agent A { budget calls = 1; task a() -> int { return x; } task a() -> int { return 1; } }"
    assert error_of(src)[:3] == ("E301", 1, 54)
    src = "agent A { budget calls = 1; task a() -> int { return 1; } task a() -> int { return 1; } }"
    assert error_of(src)[:3] == ("E302", 1, 59)
