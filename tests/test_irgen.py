"""IR generation tests: exact listings, numbering, renaming, positions and the artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscript import ir
from agentscript.diagnostics import CompileError
from agentscript.irgen import ir_artifact, lower
from agentscript.lexer import tokenize
from agentscript.parser import parse

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text())


def lower_src(source: str) -> list[ir.IRFunction]:
    return lower(parse(tokenize(source)))


def program(body: str, ret: str = "int", params: str = "", permit: str = "llm") -> str:
    """One task whose body starts at line 5."""
    return (
        "agent A {\n"
        f"  permit {permit};\n"
        "  budget calls = 9;\n"
        f"  task t({params}) -> {ret} {{\n"
        f"{body}\n"
        "  }\n"
        "}\n"
    )


def listing(fn: ir.IRFunction) -> list[str]:
    """Instruction texts, labels as `L1:`."""
    return [ir.format_instr(i) for i in fn.instrs]


def lower_one(body: str, **kw) -> ir.IRFunction:
    fns = lower_src(program(body, **kw))
    assert len(fns) == 1
    return fns[0]


# ------------------------------------------------------------------ examples


def test_valid_report_exact_listing():
    (fn,) = lower_src((EXAMPLES / "valid_report.as").read_text())
    expected = """\
task report(topic: string) -> bool
      raw = call web_search(topic)             ; line 6
      t1 = raw[0]                              ; line 7
      clean = call sanitize(t1)                ; line 7
      t2 = "Summarize: " + clean               ; line 8
      summary = call llm(t2)                   ; line 8
      t3 = call confirm("Send report?")        ; line 9
      if t3 goto L1 else L2                    ; line 9
  L1:
      t4 = call send_email("me@example.com", summary) ; line 10
      return t4                                ; line 10
  L2:
      return false                             ; line 12"""
    assert ir.format_function(fn) == expected


def test_valid_report_columns():
    (fn,) = lower_src((EXAMPLES / "valid_report.as").read_text())
    positions = [(type(i).__name__, i.line, i.col) for i in fn.instrs]
    assert positions == [
        ("Call", 6, 15),  # web_search
        ("Index", 7, 29),  # the [
        ("Call", 7, 17),  # sanitize
        ("BinOp", 8, 37),  # the +
        ("Call", 8, 19),  # llm
        ("Call", 9, 9),  # confirm
        ("Branch", 9, 5),  # if
        ("Label", 9, 5),
        ("Call", 10, 14),  # send_email
        ("Return", 10, 7),
        ("Label", 9, 5),
        ("Return", 12, 5),
    ]


def test_valid_report_operands():
    (fn,) = lower_src((EXAMPLES / "valid_report.as").read_text())
    call = fn.instrs[0]
    assert isinstance(call, ir.Call)
    assert call.dst == ir.Var("raw") and call.args == [ir.Var("topic")]
    assert fn.instrs[1] == ir.Index(ir.Var("t1"), ir.Var("raw"), ir.Const(0), line=7, col=29)
    assert fn.instrs[-1] == ir.Return(ir.Const(False), line=12, col=5)
    assert fn.name == "report"
    assert [(n, str(t)) for n, t in fn.params] == [("topic", "string")]
    assert str(fn.return_type) == "bool"


def test_runtime_budget_repeat_variable():
    (fn,) = lower_src((EXAMPLES / "runtime_budget.as").read_text())
    assert listing(fn) == [
        "t1 = 0",
        "t2 = times",
        "goto L1",
        "L1:",
        "t3 = t1 < t2",
        "if t3 goto L2 else L3",
        "L2:",
        "r = call web_search(topic)",
        "t1 = t1 + 1",
        "goto L1",
        "L3:",
        "return times",
    ]
    repeat_instrs = [i for i in fn.instrs if not isinstance(i, ir.Call) and i.line == 6]
    assert len(repeat_instrs) == 10
    assert all(i.col == 5 for i in repeat_instrs)


def test_valid_cleanup_branches_on_let_variable():
    (fn,) = lower_src((EXAMPLES / "valid_cleanup.as").read_text())
    assert listing(fn) == [
        't1 = "Delete " + path',
        't2 = t1 + "?"',
        "ok = call confirm(t2)",
        "if ok goto L1 else L2",
        "L1:",
        "t3 = call delete_file(path)",
        "return t3",
        "L2:",
        "return false",
    ]


def test_optimize_demo_listing():
    (fn,) = lower_src((EXAMPLES / "optimize_demo.as").read_text())
    assert listing(fn) == [
        "pages = 2 * 3",
        "first = call web_search(topic)",
        "again = call web_search(topic)",
        "debug = false",
        "if debug goto L1 else L2",
        "L1:",
        't1 = call llm("debug")',
        "return t1",
        "L2:",
        "t2 = first[1]",
        't3 = "Compare: " + t2',
        't4 = t3 + " / "',
        "t5 = again[2]",
        "t6 = t4 + t5",
        "t7 = call llm(t6)",
        "return t7",
    ]
    assign = fn.instrs[3]
    assert isinstance(assign, ir.Assign) and (assign.line, assign.col) == (9, 5)


# ---------------------------------------------------------------------- if


def test_if_else_both_return_has_no_end_label():
    fn = lower_one(
        "    if (true) {\n      return 1;\n    } else {\n      return 2;\n    }",
    )
    assert listing(fn) == [
        "if true goto L1 else L2",
        "L1:",
        "return 1",
        "L2:",
        "return 2",
    ]
    # L3 was allocated for the end but never emitted


def test_if_else_falls_through_to_end():
    fn = lower_one(
        "    let a = 1;\n"
        "    if (a < 2) {\n      let b = a + 1;\n    } else {\n      let c = a * 2;\n    }\n"
        "    return a;",
    )
    assert listing(fn) == [
        "a = 1",
        "t1 = a < 2",
        "if t1 goto L1 else L2",
        "L1:",
        "b = a + 1",
        "goto L3",
        "L2:",
        "c = a * 2",
        "goto L3",
        "L3:",
        "return a",
    ]


def test_if_without_else_and_then_returning():
    fn = lower_one("    if (false) {\n      return 1;\n    }\n    return 0;")
    assert listing(fn) == ["if false goto L1 else L2", "L1:", "return 1", "L2:", "return 0"]


def test_if_then_falls_through_without_else():
    fn = lower_one("    if (false) {\n      let x = 1;\n    }\n    return 0;")
    assert listing(fn) == [
        "if false goto L1 else L2",
        "L1:",
        "x = 1",
        "goto L2",
        "L2:",
        "return 0",
    ]


def test_if_jump_positions_at_if_keyword():
    fn = lower_one("    if (false) {\n      let x = 1;\n    }\n    return 0;")
    for instr in fn.instrs:
        if isinstance(instr, (ir.Branch, ir.Jump, ir.Label)):
            assert (instr.line, instr.col) == (5, 5)


def test_nested_ifs_label_numbering():
    fn = lower_one(
        "    let a = 1;\n"
        "    if (a == 1) {\n"
        "      if (a == 2) {\n        let b = 3;\n      } else {\n        let c = 4;\n      }\n"
        "    } else {\n"
        "      if (a == 3) {\n        return 5;\n      }\n"
        "    }\n"
        "    return a;",
    )
    assert listing(fn) == [
        "a = 1",
        "t1 = a == 1",
        "if t1 goto L1 else L2",
        "L1:",
        "t2 = a == 2",
        "if t2 goto L4 else L5",
        "L4:",
        "b = 3",
        "goto L6",
        "L5:",
        "c = 4",
        "goto L6",
        "L6:",
        "goto L3",
        "L2:",
        "t3 = a == 3",
        "if t3 goto L7 else L8",
        "L7:",
        "return 5",
        "L8:",
        "goto L3",
        "L3:",
        "return a",
    ]


def test_nested_if_both_return_suppresses_outer_goto():
    fn = lower_one(
        "    if (true) {\n"
        "      if (false) {\n        return 1;\n      } else {\n        return 2;\n      }\n"
        "    }\n"
        "    return 3;",
    )
    assert listing(fn) == [
        "if true goto L1 else L2",
        "L1:",
        "if false goto L3 else L4",
        "L3:",
        "return 1",
        "L4:",
        "return 2",
        "L2:",
        "return 3",
    ]


def test_if_condition_call_goes_into_temp():
    fn = lower_one(
        '    if (confirm("ok?")) {\n      return 1;\n    }\n    return 0;', permit="confirm"
    )
    assert listing(fn)[:2] == ['t1 = call confirm("ok?")', "if t1 goto L1 else L2"]


# ------------------------------------------------------------------ repeat


def test_repeat_literal():
    fn = lower_one("    repeat 3 {\n      llm(\"hi\");\n    }\n    return 0;")
    assert listing(fn) == [
        "t1 = 0",
        "t2 = 3",
        "goto L1",
        "L1:",
        "t3 = t1 < t2",
        "if t3 goto L2 else L3",
        "L2:",
        't4 = call llm("hi")',
        "t1 = t1 + 1",
        "goto L1",
        "L3:",
        "return 0",
    ]


def test_repeat_variable_count_and_nesting():
    fn = lower_one(
        "    repeat n {\n      repeat 2 {\n        let x = n + 1;\n      }\n    }\n    return n;",
        params="n: int",
    )
    assert listing(fn) == [
        "t1 = 0",
        "t2 = n",
        "goto L1",
        "L1:",
        "t3 = t1 < t2",
        "if t3 goto L2 else L3",
        "L2:",
        "t4 = 0",
        "t5 = 2",
        "goto L4",
        "L4:",
        "t6 = t4 < t5",
        "if t6 goto L5 else L6",
        "L5:",
        "x = n + 1",
        "t4 = t4 + 1",
        "goto L4",
        "L6:",
        "t1 = t1 + 1",
        "goto L1",
        "L3:",
        "return n",
    ]


def test_repeat_positions_at_repeat_keyword():
    fn = lower_one("    repeat 2 {\n      let x = 1;\n    }\n    return 0;")
    for instr in fn.instrs:
        if instr.line == 5:
            assert instr.col == 5
    assign_x = next(i for i in fn.instrs if isinstance(i, ir.Assign) and i.dst.name == "x")
    assert (assign_x.line, assign_x.col) == (6, 7)


# ---------------------------------------------------------------- renaming


def test_sibling_scope_names_are_renamed():
    fn = lower_one(
        "    if (true) {\n      let x = 1;\n      let y = x;\n    } else {\n      let x = 2;\n"
        "      let y = x;\n    }\n"
        "    repeat 1 {\n      let x = 3;\n    }\n"
        "    return 0;",
    )
    texts = listing(fn)
    assert "x = 1" in texts and "y = x" in texts
    assert "x.2 = 2" in texts and "y.2 = x.2" in texts
    assert "x.3 = 3" in texts


def test_renamed_variable_used_inside_its_scope():
    fn = lower_one(
        "    if (true) {\n      let s = \"a\";\n      llm(s);\n    }\n"
        "    if (true) {\n      let s = \"b\";\n      llm(s);\n    }\n"
        "    return 0;",
    )
    calls = [i for i in fn.instrs if isinstance(i, ir.Call)]
    assert [c.args for c in calls] == [[ir.Var("s")], [ir.Var("s.2")]]


def test_param_names_count_as_used_in_other_tasks_only():
    source = (
        "agent A {\n  permit llm;\n  budget calls = 1;\n"
        "  task one(x: int) -> int {\n    return x;\n  }\n"
        "  task two() -> int {\n    let x = 1;\n    return x;\n  }\n"
        "}\n"
    )
    one, two = lower_src(source)
    assert listing(one) == ["return x"]
    assert listing(two) == ["x = 1", "return x"]  # numbering and renaming restart per task


def test_numbering_restarts_per_task():
    source = (
        "agent A {\n  permit llm;\n  budget calls = 2;\n"
        '  task one() -> string {\n    return llm("a");\n  }\n'
        '  task two() -> string {\n    if (true) {\n      return llm("b");\n    }\n'
        '    return "c";\n  }\n'
        "}\n"
    )
    one, two = lower_src(source)
    assert [f.name for f in (one, two)] == ["one", "two"]
    assert listing(one) == ['t1 = call llm("a")', "return t1"]
    assert listing(two) == [
        "if true goto L1 else L2",
        "L1:",
        't1 = call llm("b")',
        "return t1",
        "L2:",
        'return "c"',
    ]


def test_user_variable_named_like_a_temp_is_not_clobbered():
    fn = lower_one("    let t1 = 5;\n    let y = t1 + 1;\n    return y + t1;")
    assert listing(fn) == ["t1 = 5", "y = t1 + 1", "t2 = y + t1", "return t2"]


# ----------------------------------------------------- expressions and lets


def test_expression_statements_use_fresh_temps():
    fn = lower_one('    llm("a");\n    llm(llm("b"));\n    return 0;')
    assert listing(fn) == [
        't1 = call llm("a")',
        't2 = call llm("b")',
        "t3 = call llm(t2)",
        "return 0",
    ]
    assert (fn.instrs[0].line, fn.instrs[0].col) == (5, 5)


def test_let_of_name_and_literal_emits_assign():
    fn = lower_one('    let a = "x";\n    let b = a;\n    let c = true;\n    return 0;')
    assert listing(fn) == ['a = "x"', "b = a", "c = true", "return 0"]
    assert all((i.line, i.col) == (5 + n, 5) for n, i in enumerate(fn.instrs[:3]))


def test_let_of_paren_name_emits_assign():
    fn = lower_one("    let a = 1;\n    let b = (a);\n    return b;")
    assert listing(fn) == ["a = 1", "b = a", "return b"]


def test_precedence_and_left_associativity():
    fn = lower_one("    let x = 1 + 2 * 3 - 4;\n    return x;")
    assert listing(fn) == ["t1 = 2 * 3", "t2 = 1 + t1", "x = t2 - 4", "return x"]


def test_nested_index_and_comparisons():
    fn = lower_one(
        '    let xs = web_search("q");\n    let b = xs[1 + 1] == "z";\n    return 0;',
        permit="web_search",
    )
    assert listing(fn) == [
        'xs = call web_search("q")',
        "t1 = 1 + 1",
        "t2 = xs[t1]",
        'b = t2 == "z"',
        "return 0",
    ]


def test_return_of_expression_uses_temp():
    fn = lower_one("    return 1 + 2;")
    assert listing(fn) == ["t1 = 1 + 2", "return t1"]


def test_string_escapes_in_constants():
    fn = lower_one('    let s = "a\\"b\\n";\n    return 0;')
    assert fn.instrs[0] == ir.Assign(ir.Var("s"), ir.Const('a"b\n'), line=5, col=5)
    assert listing(fn)[0] == 's = "a\\"b\\n"'


def test_code_after_return_is_kept():
    fn = lower_one("    return 1;\n    let x = 2;")
    assert listing(fn) == ["return 1", "x = 2"]


def test_lowering_is_deterministic():
    source = (EXAMPLES / "optimize_demo.as").read_text()
    assert ir_artifact(lower_src(source)) == ir_artifact(lower_src(source))


# ------------------------------------------------------------------ artifact


def test_ir_artifact_shape():
    source = (EXAMPLES / "valid_report.as").read_text()
    fns = lower_src(source)
    art = ir_artifact(fns)
    assert art["text"] == "\n\n".join(ir.format_function(f) for f in fns)
    (task,) = art["data"]
    assert task["name"] == "report"
    assert task["params"] == [{"name": "topic", "type": "string"}]
    assert task["return_type"] == "bool"
    assert task["instrs"][0] == {
        "text": "raw = call web_search(topic)",
        "op": "Call",
        "line": 6,
        "col": 15,
    }
    assert task["instrs"][7] == {"text": "L1:", "op": "Label", "line": 9, "col": 5}
    json.dumps(art)  # JSON-ready


def test_ir_artifact_joins_tasks_with_blank_line():
    source = (
        "agent A {\n  permit llm;\n  budget calls = 1;\n"
        "  task one() -> int {\n    return 1;\n  }\n"
        "  task two() -> int {\n    return 2;\n  }\n"
        "}\n"
    )
    art = ir_artifact(lower_src(source))
    assert art["text"].split("\n\n")[1].startswith("task two() -> int")
    assert [t["name"] for t in art["data"]] == ["one", "two"]


# ---------------------------------------------------- every parseable example


def _parseable_examples():
    out = []
    for entry in MANIFEST:
        try:
            parse(tokenize((EXAMPLES / entry["file"]).read_text()))
        except CompileError:
            continue
        out.append(entry["file"])
    return out


@pytest.mark.parametrize("name", _parseable_examples())
def test_every_parseable_example_lowers(name):
    source = (EXAMPLES / name).read_text()
    if name == "sem_undeclared.as":
        with pytest.raises(KeyError):  # irgen assumes a semantically valid AST
            lower_src(source)
        return
    fns = lower_src(source)
    assert fns
    for fn in fns:
        for instr in fn.instrs:
            assert instr.line > 0 and instr.col > 0
