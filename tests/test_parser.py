"""Parser tests: AST shape and positions, precedence, types, statements and E201."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscript import ast_nodes as ast
from agentscript.diagnostics import CompileError
from agentscript.lexer import tokenize
from agentscript.parser import parse
from agentscript.typesys import BOOL, INT, STRING, list_of

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))


def parse_src(source: str) -> ast.Agent:
    return parse(tokenize(source))


def program(body: str, ret: str = "int", params: str = "") -> str:
    """A minimal agent with one task whose body is `body` (lines start at line 5)."""
    return (
        "agent A {\n"
        "  permit llm;\n"
        "  budget calls = 1;\n"
        f"  task t({params}) -> {ret} {{\n"
        f"{body}\n"
        "  }\n"
        "}\n"
    )


def stmts(body: str, **kw) -> list[ast.Stmt]:
    return parse_src(program(body, **kw)).tasks[0].body.statements


def expr_of(text: str) -> ast.Expr:
    """Parse `text` as the value of a return statement."""
    (ret,) = stmts(f"    return {text};")
    assert isinstance(ret, ast.Return)
    return ret.value


def show(e: ast.Expr) -> str:
    """Fully parenthesized form, to check precedence and associativity."""
    if isinstance(e, ast.Binary):
        return f"({show(e.left)} {e.op} {show(e.right)})"
    if isinstance(e, ast.Index):
        return f"{show(e.base)}[{show(e.index)}]"
    if isinstance(e, ast.Call):
        return f"{e.tool}(" + ", ".join(show(a) for a in e.args) + ")"
    if isinstance(e, ast.Name):
        return e.name
    if isinstance(e, ast.StrLit):
        return repr(e.value)
    return str(e.value)


def syntax_error(source: str) -> tuple[int, int, str]:
    with pytest.raises(CompileError) as info:
        parse_src(source)
    d = info.value.diagnostic
    assert d.code == "E201"
    assert d.phase == "parser"
    assert d.message.startswith("expected ")
    return d.line, d.col, d.message


# ------------------------------------------------------------ the PRD example


def test_valid_report_ast_shape_and_positions():
    agent = parse_src((EXAMPLES / "valid_report.as").read_text(encoding="utf-8"))
    assert (agent.name, agent.line, agent.col) == ("Assistant", 1, 1)
    assert agent.permitted_tools() == ["web_search", "llm", "sanitize", "send_email", "confirm"]
    (permit,) = agent.permits
    assert (permit.line, permit.col) == (2, 3)
    assert [(r.line, r.col) for r in permit.tools][:2] == [(2, 10), (2, 22)]
    assert (agent.budget.calls, agent.budget.line, agent.budget.col) == (5, 3, 3)

    (task,) = agent.tasks
    assert (task.name, task.line, task.col, task.return_type) == ("report", 5, 3, BOOL)
    assert [(p.name, p.declared_type, p.line, p.col) for p in task.params] == [("topic", STRING, 5, 15)]
    body = task.body
    assert (body.line, body.col, body.end_line, body.end_col) == (5, 38, 13, 3)

    let_raw, let_clean, let_summary, if_stmt, ret = body.statements
    assert isinstance(let_raw, ast.Let)
    assert (let_raw.name, let_raw.line, let_raw.col, let_raw.name_line, let_raw.name_col) == ("raw", 6, 5, 6, 9)
    call = let_raw.value
    assert isinstance(call, ast.Call) and (call.tool, call.line, call.col) == ("web_search", 6, 15)
    assert call.args == [ast.Name("topic", 6, 26)]

    idx = let_clean.value.args[0]
    assert isinstance(idx, ast.Index) and (idx.line, idx.col) == (7, 29)
    assert idx.base == ast.Name("raw", 7, 26) and idx.index == ast.IntLit(0, 7, 30)

    concat = let_summary.value.args[0]
    assert isinstance(concat, ast.Binary) and (concat.op, concat.line, concat.col) == ("+", 8, 37)
    assert concat.left == ast.StrLit("Summarize: ", 8, 23)

    assert isinstance(if_stmt, ast.If) and (if_stmt.line, if_stmt.col) == (9, 5)
    assert if_stmt.cond.tool == "confirm" and if_stmt.else_block is None
    tb = if_stmt.then_block
    assert (tb.line, tb.col, tb.end_line, tb.end_col) == (9, 34, 11, 5)
    (inner,) = tb.statements
    assert isinstance(inner, ast.Return) and (inner.line, inner.col) == (10, 7)
    assert [show(a) for a in inner.value.args] == ["'me@example.com'", "summary"]

    assert ret == ast.Return(ast.BoolLit(False, 12, 12), 12, 5)
    # The parser never sets types; semantic analysis does.
    assert call.type is None


def test_format_ast_on_valid_report():
    agent = parse_src((EXAMPLES / "valid_report.as").read_text(encoding="utf-8"))
    text = ast.format_ast(agent)
    lines = text.split("\n")
    assert lines[0] == "Agent Assistant @1:1"
    assert "  Permit [web_search, llm, sanitize, send_email, confirm] @2:3" in lines
    assert "    Budget 5 @3:3" in lines
    assert "  Task report return_type=bool @5:3" in lines
    assert "    Param topic declared_type=string @5:15" in lines
    assert "        Let raw @6:5" in lines
    assert "          Call web_search @6:15" in lines
    assert "            Name topic @6:26" in lines
    assert "            Binary + @8:37" in lines
    assert "              StrLit 'Summarize: ' @8:23" in lines
    assert "          then_block:" in lines
    assert "          BoolLit False @12:12" in lines


def test_ast_to_dict_on_valid_report():
    agent = parse_src((EXAMPLES / "valid_report.as").read_text(encoding="utf-8"))
    d = ast.ast_to_dict(agent)
    json.dumps(d)  # JSON-ready
    assert d["node"] == "Agent" and d["name"] == "Assistant"
    assert d["budget"] == {"node": "Budget", "calls": 5, "line": 3, "col": 3}
    task = d["tasks"][0]
    assert task["return_type"] == "bool"
    assert task["params"][0]["declared_type"] == "string"
    first = task["body"]["statements"][0]
    assert first["node"] == "Let" and first["value"]["node"] == "Call"
    assert first["value"]["tool"] == "web_search"
    assert "type" not in first["value"]  # untyped before semantic analysis


def test_parse_is_deterministic():
    src = (EXAMPLES / "valid_report.as").read_text(encoding="utf-8")
    assert parse_src(src) == parse_src(src)


# -------------------------------------------------------------- declarations


def test_no_permits_is_allowed():
    agent = parse_src("agent A { budget calls = 0; task t() -> int { return 1; } }")
    assert agent.permits == [] and agent.budget.calls == 0


def test_several_permits_and_tasks():
    src = (
        "agent A {\n permit llm;\n permit web_search, sanitize;\n budget calls = 3;\n"
        " task a() -> int { return 1; }\n task b(x: int, y: bool) -> bool { return y; }\n}"
    )
    agent = parse_src(src)
    assert agent.permitted_tools() == ["llm", "web_search", "sanitize"]
    assert [t.name for t in agent.tasks] == ["a", "b"]
    assert [(p.name, p.declared_type) for p in agent.tasks[1].params] == [("x", INT), ("y", BOOL)]


def test_empty_param_list():
    agent = parse_src(program("    return 1;"))
    assert agent.tasks[0].params == []


@pytest.mark.parametrize(
    "text, expected",
    [
        ("string", STRING),
        ("int", INT),
        ("bool", BOOL),
        ("list<string>", list_of(STRING)),
        ("list<list<string>>", list_of(list_of(STRING))),
        ("list<list<list<int>>>", list_of(list_of(list_of(INT)))),
    ],
)
def test_types(text, expected):
    agent = parse_src(program("    return x;", ret=text, params=f"x: {text}"))
    task = agent.tasks[0]
    assert task.return_type == expected
    assert task.params[0].declared_type == expected


# ---------------------------------------------------------------- statements


def test_let_statement():
    (let,) = stmts("    let  value = 3;")
    assert let == ast.Let("value", ast.IntLit(3, 5, 18), 5, 5, 5, 10)


def test_if_without_else():
    (s,) = stmts("    if (true) { return 1; }")
    assert isinstance(s, ast.If) and s.else_block is None
    assert s.cond == ast.BoolLit(True, 5, 9)


def test_if_with_else():
    (s, _) = stmts("    if (x < 1) {\n      return 1;\n    } else {\n      let y = 2;\n    }\n    return 3;")
    assert isinstance(s, ast.If)
    assert show(s.cond) == "(x < 1)"
    eb = s.else_block
    assert eb is not None and (eb.line, eb.col, eb.end_line, eb.end_col) == (7, 12, 9, 5)
    assert isinstance(eb.statements[0], ast.Let)


def test_empty_blocks():
    (s, _) = stmts("    if (b) {} else {}\n    return 1;")
    assert s.then_block.statements == [] and s.else_block.statements == []


def test_nested_ifs():
    (s, _) = stmts("    if (a) { if (b) { return 1; } }\n    return 2;")
    assert isinstance(s.then_block.statements[0], ast.If)


def test_repeat_with_int_literal():
    (s, _) = stmts("    repeat 3 { llm(\"x\"); }\n    return 1;")
    assert isinstance(s, ast.Repeat) and (s.line, s.col) == (5, 5)
    assert s.count == ast.IntLit(3, 5, 12)
    (body_stmt,) = s.body.statements
    assert isinstance(body_stmt, ast.ExprStmt)


def test_repeat_with_identifier():
    (s, _) = stmts("    repeat times {\n    }\n    return 1;", params="times: int")
    assert s.count == ast.Name("times", 5, 12)
    assert s.body.statements == []


def test_expression_statement():
    (s, _) = stmts('    llm("hi");\n    return 1;')
    assert isinstance(s, ast.ExprStmt)
    assert isinstance(s.expr, ast.Call) and s.expr.tool == "llm"
    assert (s.line, s.col) == (5, 5) == (s.expr.line, s.expr.col)


def test_expression_statement_position_is_its_expression():
    (s, _) = stmts("    (1) + 2;\n    return 1;")
    assert isinstance(s.expr, ast.Binary)
    assert (s.line, s.col) == (5, 9)  # the operator


def test_statements_after_return_parse():
    ss = stmts("    return 1;\n    let x = 2;")
    assert [type(s).__name__ for s in ss] == ["Return", "Let"]


# --------------------------------------------------------------- expressions


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1 + 2 * 3", "(1 + (2 * 3))"),
        ("1 * 2 + 3", "((1 * 2) + 3)"),
        ("a - b - c", "((a - b) - c)"),
        ("a * b * c", "((a * b) * c)"),
        ("a - b + c", "((a - b) + c)"),
        ("a == b + 1", "(a == (b + 1))"),
        ("a == b == c", "((a == b) == c)"),
        ("a < b == c >= d", "((a < b) == (c >= d))"),
        ("a + b < c * d", "((a + b) < (c * d))"),
        ("a != b", "(a != b)"),
        ("a <= b", "(a <= b)"),
        ("a > b", "(a > b)"),
        ("(1 + 2) * 3", "((1 + 2) * 3)"),
        ("a * (b - c)", "(a * (b - c))"),
        ("((a))", "a"),
        ("xs[0][1]", "xs[0][1]"),
        ("xs[i + 1] * 2", "(xs[(i + 1)] * 2)"),
        ("f(x)[0]", "f(x)[0]"),
        ("(xs)[0]", "xs[0]"),
        ("f()", "f()"),
        ("f(a, b + 1, g(c))", "f(a, (b + 1), g(c))"),
        ('"a" + "b"', "('a' + 'b')"),
    ],
)
def test_precedence_and_associativity(text, expected):
    assert show(expr_of(text)) == expected


def test_binary_position_is_operator():
    e = expr_of("1 + 2 * 3")  # "    return " is 11 columns wide
    assert (e.op, e.line, e.col) == ("+", 5, 14)
    assert (e.right.op, e.right.line, e.right.col) == ("*", 5, 18)


def test_index_position_is_bracket_and_nesting():
    e = expr_of("xs[0][1]")
    assert isinstance(e, ast.Index) and (e.line, e.col) == (5, 17)
    assert isinstance(e.base, ast.Index) and (e.base.line, e.base.col) == (5, 14)
    assert e.base.base == ast.Name("xs", 5, 12)
    assert e.index == ast.IntLit(1, 5, 18)


def test_call_position_is_tool_name():
    e = expr_of("web_search(q)")
    assert isinstance(e, ast.Call) and (e.line, e.col) == (5, 12)
    assert e.args == [ast.Name("q", 5, 23)]


def test_literals():
    assert expr_of("42") == ast.IntLit(42, 5, 12)
    assert expr_of("true") == ast.BoolLit(True, 5, 12)
    assert expr_of("false") == ast.BoolLit(False, 5, 12)
    assert expr_of(r'"a\tb\"c"') == ast.StrLit('a\tb"c', 5, 12)


def test_name_without_parens_is_not_a_call():
    assert expr_of("llm") == ast.Name("llm", 5, 12)


# ----------------------------------------------------------- syntax errors


def test_missing_semicolon_reported_after_previous_token():
    line, col, msg = syntax_error(program("    let a = 1\n    return a;"))
    assert (line, col) == (5, 14)
    assert msg == "expected ';', found 'return'"


def test_missing_semicolon_same_line_reported_at_found_token():
    line, col, msg = syntax_error(program("    let a = 1 return a;"))
    assert (line, col) == (5, 15)
    assert msg == "expected ';', found 'return'"


def test_missing_closing_brace_at_eof():
    src = "agent A {\n  budget calls = 1;\n  task t() -> int {\n    return 1;\n  }\n"
    line, col, msg = syntax_error(src)
    assert (line, col) == (5, 4)  # right after the task's '}'
    assert msg == "expected 'task' or '}', found end of file"


def test_missing_block_brace_at_eof():
    line, col, msg = syntax_error("agent A { budget calls = 1; task t() -> int { return 1;")
    assert (line, col) == (1, 56)
    assert msg == "expected '}', found end of file"


def test_missing_rparen_in_call():
    line, col, msg = syntax_error(program("    return llm(x;"))
    assert (line, col) == (5, 17)
    assert msg == "expected ',' or ')', found ';'"


def test_missing_rparen_in_if():
    line, col, msg = syntax_error(program("    if (x {\n    }\n    return 1;"))
    assert (line, col) == (5, 11)
    assert msg == "expected ')', found '{'"


def test_missing_rparen_in_grouping():
    _, _, msg = syntax_error(program("    return (1 + 2;"))
    assert msg == "expected ')', found ';'"


def test_let_without_name():
    line, col, msg = syntax_error(program("    let = 3;"))
    assert (line, col) == (5, 9)
    assert msg == "expected identifier, found '='"


def test_let_with_keyword_name():
    _, _, msg = syntax_error(program("    let if = 3;"))
    assert msg == "expected identifier, found 'if'"


def test_let_missing_assign():
    _, _, msg = syntax_error(program("    let x 3;"))
    assert msg == "expected '=', found integer 3"


def test_repeat_with_string_count():
    line, col, msg = syntax_error(program('    repeat "x" {}'))
    assert (line, col) == (5, 12)
    assert msg == 'expected integer or identifier, found string "x"'


def test_repeat_with_expression_count():
    _, _, msg = syntax_error(program("    repeat n + 1 {}"))
    assert msg == "expected '{', found '+'"


def test_missing_budget():
    src = "agent A {\n  permit llm;\n  task t() -> int { return 1; }\n}"
    line, col, msg = syntax_error(src)
    assert (line, col) == (2, 14)
    assert msg == "expected 'permit' or 'budget', found 'task'"


def test_budget_before_permit():
    src = "agent A { budget calls = 1; permit llm; task t() -> int { return 1; } }"
    _, _, msg = syntax_error(src)
    assert msg == "expected 'task', found 'permit'"


def test_duplicate_budget():
    src = "agent A { budget calls = 1; budget calls = 2; task t() -> int { return 1; } }"
    _, _, msg = syntax_error(src)
    assert msg == "expected 'task', found 'budget'"


def test_malformed_budget():
    assert syntax_error("agent A { budget = 1; }")[2] == "expected 'calls', found '='"
    assert syntax_error("agent A { budget calls 1; }")[2] == "expected '=', found integer 1"
    assert syntax_error("agent A { budget calls = x; }")[2] == "expected integer, found identifier 'x'"
    assert syntax_error("agent A { budget calls = 1 }")[2] == "expected ';', found '}'"


def test_agent_without_tasks():
    line, col, msg = syntax_error("agent A {\n  budget calls = 1;\n}")
    assert (line, col) == (2, 20)
    assert msg == "expected 'task', found '}'"


def test_trailing_tokens_after_agent():
    src = "agent A { budget calls = 1; task t() -> int { return 1; } } extra"
    line, col, msg = syntax_error(src)
    assert (line, col) == (1, 61)
    assert msg == "expected end of file, found identifier 'extra'"


def test_second_agent_is_trailing():
    src = "agent A { budget calls = 1; task t() -> int { return 1; } }\nagent B {}"
    line, col, msg = syntax_error(src)
    assert (line, col) == (1, 60)
    assert msg == "expected end of file, found 'agent'"


def test_empty_source():
    line, col, msg = syntax_error("")
    assert (line, col) == (1, 1)  # no previous token: report at EOF itself
    assert msg == "expected 'agent', found end of file"


def test_missing_agent_name():
    assert syntax_error("agent { }")[2] == "expected agent name, found '{'"


def test_permit_errors():
    assert syntax_error("agent A { permit; }")[2] == "expected tool name, found ';'"
    assert syntax_error("agent A { permit llm web_search; }")[2] == "expected ',' or ';', found identifier 'web_search'"
    assert syntax_error("agent A { permit llm, ; }")[2] == "expected tool name, found ';'"


def test_task_header_errors():
    pre = "agent A { budget calls = 1; "
    assert syntax_error(pre + "task () -> int {} }")[2] == "expected task name, found '('"
    assert syntax_error(pre + "task t -> int {} }")[2] == "expected '(', found '->'"
    assert syntax_error(pre + "task t() int {} }")[2] == "expected '->', found 'int'"
    assert syntax_error(pre + "task t() -> {} }")[2] == "expected type, found '{'"
    assert syntax_error(pre + "task t() -> integer {} }")[2] == "expected type, found identifier 'integer'"
    assert syntax_error(pre + "task t(x) -> int {} }")[2] == "expected ':', found ')'"
    assert syntax_error(pre + "task t(x: int y: int) -> int {} }")[2] == "expected ',' or ')', found identifier 'y'"
    assert syntax_error(pre + "task t(x: int,) -> int {} }")[2] == "expected parameter name, found ')'"
    assert syntax_error(pre + "task t() -> int return 1; }")[2] == "expected '{', found 'return'"


def test_list_type_errors():
    pre = "agent A { budget calls = 1; task t() -> "
    assert syntax_error(pre + "list {} }")[2] == "expected '<', found '{'"
    assert syntax_error(pre + "list<> {} }")[2] == "expected type, found '>'"
    assert syntax_error(pre + "list<int {} }")[2] == "expected '>', found '{'"
    assert syntax_error(pre + "list<list<int> {} }")[2] == "expected '>', found '{'"


def test_expression_errors():
    assert syntax_error(program("    return ;"))[2] == "expected expression, found ';'"
    assert syntax_error(program("    return 1 +;"))[2] == "expected expression, found ';'"
    assert syntax_error(program("    return xs[1;"))[2] == "expected ']', found ';'"
    assert syntax_error(program("    return xs[];"))[2] == "expected expression, found ']'"
    assert syntax_error(program("    return f(a,);"))[2] == "expected expression, found ')'"
    assert syntax_error(program("    return 1 2;"))[2] == "expected ';', found integer 2"
    assert syntax_error(program('    return "a" "b";'))[2] == 'expected \';\', found string "b"'


def test_unsupported_constructs_are_syntax_errors():
    # No assignment statement, no `else if`, no list literals, no unary minus.
    assert syntax_error(program("    let x = 1;\n    x = 2;"))[2] == "expected ';', found '='"
    assert syntax_error(program("    if (a) {} else if (b) {}"))[2] == "expected '{', found 'if'"
    assert syntax_error(program("    return [1];"))[2] == "expected expression, found '['"
    assert syntax_error(program("    return -1;"))[2] == "expected expression, found '-'"
    assert syntax_error(program("    else {}"))[2] == "expected expression, found 'else'"


def test_missing_semicolon_before_closing_brace_same_line():
    line, col, msg = syntax_error(program("    return 1 }"))
    assert (line, col) == (5, 14)
    assert msg == "expected ';', found '}'"


def test_location_rule_skips_blank_lines_and_comments():
    line, col, _ = syntax_error(program("    let a = f(x)   // no semicolon\n\n\n    return a;"))
    assert (line, col) == (5, 17)


def test_location_rule_after_string_token():
    line, col, _ = syntax_error(program('    let a = "a\\"b"\n    return a;'))
    assert (line, col) == (5, 19)


def test_parse_requires_eof_terminated_tokens():
    with pytest.raises(ValueError):
        parse([])


# ---------------------------------------------------------------- examples


@pytest.mark.parametrize("entry", MANIFEST, ids=[e["file"] for e in MANIFEST])
def test_examples_parse_per_manifest(entry: dict):
    source = (EXAMPLES / entry["file"]).read_text(encoding="utf-8")
    expect = entry["expect"]
    code = expect["code"] if expect else None
    if code in ("E101", "E102"):
        pytest.skip("lexical error example: covered by test_lexer")
    if code == "E201":
        line, col, _ = syntax_error(source)
        assert (line, col) == (expect["line"], expect["col"])
    else:
        agent = parse_src(source)
        assert isinstance(agent, ast.Agent) and agent.tasks


# ------------------------------------------------------------- nesting bound (MAX_NESTING)
# Deep programs go through compile_source, which runs the phases on a deep stack.


def _deep_diag(body: str):
    from agentscript.pipeline import compile_source

    res = compile_source(program(body))
    return res, (res.error.format() if res.error else None)


def test_max_nesting_value():
    from agentscript.parser import MAX_NESTING

    assert MAX_NESTING == 1000


@pytest.mark.parametrize(
    "body",
    [
        "    return " + "(" * 900 + "1" + ")" * 900 + ";",
        "    return " + "+".join(["1"] * 900) + ";",
        "    " + "if (true) {" * 400 + "return 1;" + "}" * 400 + "\n    return 0;",
        "    " + "repeat 1 {" * 400 + "}" * 400 + "\n    return 0;",
    ],
    ids=["parens-900", "chain-900", "if-400", "repeat-400"],
)
def test_deep_but_bounded_programs_compile(body):
    res, err = _deep_diag(body)
    assert res.ok, err


def test_too_many_parens_is_e201_at_the_token():
    res, _ = _deep_diag("    return " + "(" * 1200 + "1" + ")" * 1200 + ";")
    d = res.error
    assert (d.code, d.phase) == ("E201", "parser")
    assert d.message == "expected at most 1000 levels of nesting, found '('"
    # parse_expr is entered for the return value and once per `(`: the 1000th `(` is refused
    assert (d.line, d.col) == (5, 12 + 999)


def test_long_operator_chain_is_e201_at_the_deep_node():
    res, _ = _deep_diag("    return " + "+".join(["1"] * 5000) + ";")
    d = res.error
    assert d.code == "E201" and d.message.startswith("expected at most 1000 levels of nesting, found a deeper")
    assert d.line == 5


def test_too_many_nested_blocks_is_e201():
    res, _ = _deep_diag("    " + "if (true) {" * 1200 + "return 1;" + "}" * 1200 + "\n    return 0;")
    assert res.error.code == "E201" and "levels of nesting" in res.error.message


def test_check_nesting_is_iterative():
    import sys

    from agentscript.parser import check_nesting

    # a left-deep chain far deeper than the recursion limit is checked without recursion
    expr = ast.IntLit(1, 5, 12)
    for _ in range(sys.getrecursionlimit() + 10):
        expr = ast.Binary("+", expr, ast.IntLit(1, 5, 14), 5, 13)
    agent = parse_src(program("    return 1;"))
    agent.tasks[0].body.statements[0].value = expr
    with pytest.raises(CompileError) as info:
        check_nesting(agent)
    assert info.value.diagnostic.code == "E201"
