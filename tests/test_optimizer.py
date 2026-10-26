"""Optimizer tests: folding, propagation, unreachable blocks, dead code, duplicate calls."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from agentscript import ir
from agentscript.cfg import build_cfg, cfg_to_dict, format_cfg, link_blocks, reachable
from agentscript.ir import Assign, BinOp, Branch, Call, Const, Index, IRFunction, Jump, Return, Var
from agentscript.irgen import lower
from agentscript.lexer import tokenize
from agentscript.optimizer import OptReport, fold_binop, optimize, optimized_artifact
from agentscript.parser import parse
from agentscript.semantic import analyze
from agentscript.typesys import INT, STRING, list_of

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
VALID_EXAMPLES = [e["file"] for e in MANIFEST if e["expect"] is None]


def cfgs_of(source: str) -> list[ir.CFG]:
    agent = parse(tokenize(source))
    analyze(agent)  # the optimizer only ever sees semantically valid programs
    return [build_cfg(fn) for fn in lower(agent)]


def example_cfgs(name: str) -> list[ir.CFG]:
    return cfgs_of((EXAMPLES / name).read_text(encoding="utf-8"))


def program(body: str, ret: str = "int", params: str = "", permit: str = "llm") -> str:
    return (
        "agent A {\n"
        f"  permit {permit};\n"
        "  budget calls = 20;\n"
        f"  task t({params}) -> {ret} {{\n"
        f"{body}\n"
        "  }\n"
        "}\n"
    )


def opt_one(body: str, **kw) -> tuple[ir.CFG, ir.CFG, OptReport]:
    (cfg,) = cfgs_of(program(body, **kw))
    out, report = optimize(cfg)
    return cfg, out, report


def all_instrs(cfg: ir.CFG) -> list[ir.Instr]:
    return [i for b in cfg.blocks.values() for i in b.instrs]


def calls(cfg: ir.CFG) -> list[Call]:
    return [i for i in all_instrs(cfg) if isinstance(i, Call)]


def assert_links_consistent(cfg: ir.CFG) -> None:
    fresh = copy.deepcopy(cfg)
    link_blocks(fresh)
    for label, block in cfg.blocks.items():
        assert block.succs == fresh.blocks[label].succs
        assert block.preds == fresh.blocks[label].preds
        for succ in block.succs:
            assert succ in cfg.blocks


def manual_cfg(instrs: list[ir.Instr], params: list[tuple[str, object]] | None = None) -> ir.CFG:
    return build_cfg(IRFunction("t", params or [], INT, instrs))


# ------------------------------------------------------------------ demo program


def test_optimize_demo_calls_4_to_2():
    (cfg,) = example_cfgs("optimize_demo.as")
    out, report = optimize(cfg)
    assert report.before == {"instructions": 14, "calls": 4}
    assert report.after == {"instructions": 10, "calls": 2}
    assert [c.tool for c in calls(out)] == ["web_search", "llm"]
    assert "L1" not in out.blocks  # the debug branch with llm("debug")
    dsts = {ir.defined_var(i) for i in all_instrs(out)}
    assert "pages" not in dsts and "debug" not in dsts
    assert isinstance(out.blocks["entry"].terminator, Jump)
    assert_links_consistent(out)


def test_optimize_demo_changes_list():
    (cfg,) = example_cfgs("optimize_demo.as")
    _, report = optimize(cfg)
    assert report.changes == [
        "line 6: folded pages = 2 * 3 -> 6",
        "line 10: replaced debug with false",
        "line 10: branch on false -> goto L2",
        "removed unreachable block L1 (line 11)",
        "line 6: removed dead assignment pages = 6",
        "line 9: removed dead assignment debug = false",
        "line 8: duplicate call web_search(topic) replaced by copy of first (line 7)",
    ]
    assert report.iterations >= 2


def test_merged_call_keeps_line_and_col():
    (cfg,) = example_cfgs("optimize_demo.as")
    original = cfg.blocks["entry"].instrs[2]
    out, _ = optimize(cfg)
    copy_instr = next(i for i in all_instrs(out) if ir.defined_var(i) == "again")
    assert copy_instr == Assign(Var("again"), Var("first"), line=original.line, col=original.col)


def test_input_cfg_not_mutated():
    (cfg,) = example_cfgs("optimize_demo.as")
    text, data = format_cfg(cfg), cfg_to_dict(cfg)
    snapshot = copy.deepcopy(cfg)
    optimize(cfg)
    assert format_cfg(cfg) == text
    assert cfg_to_dict(cfg) == data
    assert cfg == snapshot


def test_valid_report_keeps_all_five_calls():
    (cfg,) = example_cfgs("valid_report.as")
    out, report = optimize(cfg)
    assert report.before["calls"] == report.after["calls"] == 5
    assert [c.tool for c in calls(out)] == ["web_search", "sanitize", "llm", "confirm", "send_email"]
    assert report.changes == []
    assert format_cfg(out) == format_cfg(cfg)


@pytest.mark.parametrize("name", VALID_EXAMPLES)
def test_valid_examples_idempotent_and_consistent(name):
    for cfg in example_cfgs(name):
        out, report = optimize(cfg)
        assert report.after["calls"] <= report.before["calls"]
        assert report.after["instructions"] <= report.before["instructions"]
        assert set(out.blocks) == reachable(out)
        assert_links_consistent(out)
        again, second = optimize(out)
        assert second.changes == []
        assert second.iterations == 1
        assert format_cfg(again) == format_cfg(out)


def test_deterministic():
    (a,) = example_cfgs("optimize_demo.as")
    (b,) = example_cfgs("optimize_demo.as")
    out_a, rep_a = optimize(a)
    out_b, rep_b = optimize(b)
    assert format_cfg(out_a) == format_cfg(out_b)
    assert rep_a.to_dict() == rep_b.to_dict()


# -------------------------------------------------------- duplicate tool calls


@pytest.mark.parametrize(
    "stmts, permit",
    [
        ('    let a = confirm("go?");\n    let b = confirm("go?");', "confirm"),
        ('    let a = send_email("x", "y");\n    let b = send_email("x", "y");', "send_email"),
        ('    let a = delete_file("p");\n    let b = delete_file("p");', "delete_file"),
    ],
)
def test_non_mergeable_tools_never_merged(stmts, permit):
    body = stmts + "\n    if (a == b) { return 1; }\n    return 0;"
    cfg, out, report = opt_one(body, permit=permit)
    assert len(calls(out)) == 2
    assert not any("duplicate call" in c for c in report.changes)


def test_three_identical_calls_merge_into_first():
    body = (
        "    let a = web_search(q);\n"
        "    let b = web_search(q);\n"
        "    let c = web_search(q);\n"
        "    return llm(a[0] + b[0] + c[0]);"
    )
    _, out, report = opt_one(body, ret="string", params="q: string", permit="web_search, llm")
    assert report.before["calls"] == 4 and report.after["calls"] == 2
    assert "line 6: duplicate call web_search(q) replaced by copy of a (line 5)" in report.changes
    assert "line 7: duplicate call web_search(q) replaced by copy of a (line 5)" in report.changes
    # the copies are propagated into the same block's uses and then die
    assert not any(isinstance(i, Assign) for i in all_instrs(out))
    assert [i.base for i in all_instrs(out) if isinstance(i, Index)] == [Var("a")] * 3


def test_call_between_blocks_merging():
    body = (
        "    let a = llm(q);\n"
        "    let x = sanitize(q);\n"
        "    let b = llm(q);\n"
        "    return a + x + b;"
    )
    _, out, report = opt_one(body, ret="string", params="q: string", permit="llm, sanitize")
    assert [c.tool for c in calls(out)] == ["llm", "sanitize", "llm"]
    assert report.after["calls"] == 3


def test_different_arguments_not_merged():
    body = '    let a = llm(q);\n    let b = llm("other");\n    return a + b;'
    _, out, _ = opt_one(body, ret="string", params="q: string")
    assert len(calls(out)) == 2


def test_identical_calls_in_different_blocks_not_merged():
    body = (
        "    let a = llm(q);\n"
        "    if (flag) {\n"
        "      let b = llm(q);\n"
        "      return b;\n"
        "    }\n"
        "    return a;"
    )
    _, out, report = opt_one(body, ret="string", params="q: string, flag: bool")
    assert len(calls(out)) == 2
    assert report.changes == []


def test_constant_arguments_merged_after_propagation():
    body = '    let p = "same";\n    let a = llm(p);\n    let b = llm("same");\n    return a + b;'
    _, out, report = opt_one(body, ret="string")
    assert report.after["calls"] == 1
    assert "line 7: duplicate call llm(\"same\") replaced by copy of a (line 6)" in report.changes


def test_redefined_argument_blocks_merging():
    # x = call llm(a); a = xs[0]; y = call llm(a): same text, different value of `a`.
    instrs = [
        Call(Var("x"), "llm", [Var("a")], line=1),
        Index(Var("a"), Var("xs"), Const(0), line=2),
        Call(Var("y"), "llm", [Var("a")], line=3),
        BinOp(Var("z"), "+", Var("x"), Var("y"), line=4),
        Return(Var("z"), line=4),
    ]
    out, report = optimize(manual_cfg(instrs, [("a", STRING), ("xs", list_of(STRING))]))
    assert len(calls(out)) == 2
    assert not any("duplicate" in c for c in report.changes)


def test_redefined_earlier_destination_blocks_merging():
    instrs = [
        Call(Var("x"), "llm", [Var("a")], line=1),
        Index(Var("x"), Var("xs"), Const(0), line=2),
        Call(Var("y"), "llm", [Var("a")], line=3),
        BinOp(Var("z"), "+", Var("x"), Var("y"), line=4),
        Return(Var("z"), line=4),
    ]
    out, _ = optimize(manual_cfg(instrs, [("a", STRING), ("xs", list_of(STRING))]))
    assert len(calls(out)) == 2


def test_unrelated_definition_between_allows_merging():
    instrs = [
        Call(Var("x"), "llm", [Var("a")], line=1),
        Index(Var("w"), Var("xs"), Const(0), line=2),
        Call(Var("y"), "llm", [Var("a")], line=3),
        BinOp(Var("z"), "+", Var("x"), Var("y"), line=4),
        BinOp(Var("z2"), "+", Var("z"), Var("w"), line=4),
        Return(Var("z2"), line=4),
    ]
    out, report = optimize(manual_cfg(instrs, [("a", STRING), ("xs", list_of(STRING))]))
    assert len(calls(out)) == 1
    assert "line 3: duplicate call llm(a) replaced by copy of x (line 1)" in report.changes


# ------------------------------------------------------------ dead assignments


def test_index_never_removed():
    body = "    let x = xs[5];\n    return 1;"
    _, out, _ = opt_one(body, params="xs: list<string>")
    assert any(isinstance(i, Index) and i.dst == Var("x") for i in all_instrs(out))


def test_unused_call_never_removed():
    body = '    let unused = llm("hi");\n    llm("again");\n    return 1;'
    _, out, report = opt_one(body)
    assert len(calls(out)) == 2
    assert report.after["calls"] == 2


def test_dead_binop_and_chains_removed():
    body = "    let a = n + 1;\n    let b = a * 2;\n    return n;"
    _, out, report = opt_one(body, params="n: int")
    assert [type(i) for i in all_instrs(out)] == [Return]
    assert "line 6: removed dead assignment b = a * 2" in report.changes
    assert "line 5: removed dead assignment a = n + 1" in report.changes


def test_variable_used_in_other_block_kept():
    body = "    let a = n + 1;\n    if (flag) { return a; }\n    return 0;"
    _, out, _ = opt_one(body, params="n: int, flag: bool")
    assert any(isinstance(i, BinOp) and i.dst == Var("a") for i in all_instrs(out))


# ------------------------------------------------ folding and propagation


@pytest.mark.parametrize(
    "op, left, right, expected",
    [
        ("+", 2, 3, 5),
        ("-", 2, 7, -5),
        ("*", 4, 6, 24),
        ("+", "ab", "cd", "abcd"),
        ("<", 2, 3, True),
        ("<=", 3, 3, True),
        (">", 2, 3, False),
        (">=", 2, 3, False),
        ("==", "a", "a", True),
        ("!=", "a", "b", True),
        ("==", True, False, False),
        ("!=", True, False, True),
        ("==", 4, 4, True),
    ],
)
def test_fold_binop_matches_vm(op, left, right, expected):
    result = fold_binop(op, left, right)
    assert result is not None
    assert type(result.value) is type(expected) and result.value == expected


@pytest.mark.parametrize(
    "op, left, right",
    [("==", True, 1), ("+", True, 1), ("-", "a", "b"), ("<", "a", "b"), ("*", "a", 2), ("+", "a", 1)],
)
def test_fold_binop_refuses_ill_typed(op, left, right):
    assert fold_binop(op, left, right) is None


def test_string_folding_in_program():
    body = '    let s = "Hello, " + "world";\n    return s;'
    _, out, report = opt_one(body, ret="string")
    assert out.blocks["entry"].instrs == [Return(Const("Hello, world"), line=6, col=5)]
    assert 'line 5: folded s = "Hello, " + "world" -> "Hello, world"' in report.changes


def test_comparison_folding_and_chain_propagation():
    body = "    let a = 2 * 3;\n    let b = a + 4;\n    let c = b == 10;\n    if (c) { return 1; }\n    return 2;"
    _, out, report = opt_one(body)
    assert list(out.blocks) == ["entry", "L1"]
    assert out.blocks["L1"].instrs == [Return(Const(1), line=8, col=14)]
    assert "line 8: branch on true -> goto L1" in report.changes
    assert report.after == {"instructions": 2, "calls": 0}


def test_branch_on_true_removes_else():
    body = '    if (true) { return llm("a"); } else { return llm("b"); }'
    _, out, report = opt_one(body, ret="string")
    assert [c.args for c in calls(out)] == [[Const("a")]]
    assert report.before["calls"] == 2 and report.after["calls"] == 1
    assert_links_consistent(out)


def test_branch_on_false_removes_then():
    body = '    if (1 > 2) { return llm("a"); }\n    return llm("b");'
    _, out, report = opt_one(body, ret="string")
    assert [c.args for c in calls(out)] == [[Const("b")]]
    assert any(c.startswith("removed unreachable block L1") for c in report.changes)
    assert_links_consistent(out)


def test_copy_propagation_of_param():
    body = "    let a = n;\n    let b = a + 1;\n    return b;"
    _, out, _ = opt_one(body, params="n: int")
    first = out.blocks["entry"].instrs[0]
    assert isinstance(first, BinOp) and (first.dst, first.left, first.right) == (Var("b"), Var("n"), Const(1))
    assert len(out.blocks["entry"].instrs) == 2


def test_propagation_is_block_local():
    body = "    let a = 5;\n    if (flag) { return a; }\n    return 0;"
    _, out, _ = opt_one(body, params="flag: bool")
    # `a` is read in another block, so its definition stays and the use is not rewritten
    assert Assign(Var("a"), Const(5), line=5, col=5) in all_instrs(out)
    then_block = out.blocks[out.blocks["entry"].succs[0]]
    assert then_block.instrs[0] == Return(Var("a"), line=6, col=17)


def test_copy_killed_when_source_redefined():
    # b = a; a = xs[0]; return b  -> `b` must not become `a` after `a` changes.
    instrs = [
        Assign(Var("b"), Var("a"), line=1),
        Index(Var("a"), Var("xs"), Const(0), line=2),
        BinOp(Var("r"), "+", Var("b"), Var("a"), line=3),
        Return(Var("r"), line=3),
    ]
    out, _ = optimize(manual_cfg(instrs, [("a", STRING), ("xs", list_of(STRING))]))
    binop = next(i for i in all_instrs(out) if isinstance(i, BinOp))
    assert binop.left == Var("b") and binop.right == Var("a")


def test_constant_killed_when_var_redefined():
    instrs = [
        Assign(Var("k"), Const(0), line=1),
        Index(Var("k"), Var("xs"), Const(0), line=2),
        Return(Var("k"), line=3),
    ]
    out, _ = optimize(manual_cfg(instrs, [("xs", list_of(INT))]))
    assert out.blocks["entry"].instrs[-1] == Return(Var("k"), line=3)


# ----------------------------------------------------------------------- loops


def test_repeat_literal_keeps_loop():
    body = '    repeat 3 {\n      let r = llm("x");\n    }\n    return 1;'
    cfg, out, report = opt_one(body)
    assert report.after["calls"] == 1
    assert list(out.blocks) == list(cfg.blocks)
    head = out.blocks["L1"]
    assert isinstance(head.terminator, Branch)
    assert head.instrs == cfg.blocks["L1"].instrs
    # the counter's increment and the limit survive; nothing was folded inside the loop
    assert any(isinstance(i, BinOp) and i.op == "+" for i in out.blocks["L2"].instrs)
    assert not any("branch on" in c for c in report.changes)
    assert_links_consistent(out)


def test_repeat_variable_keeps_loop():
    (cfg,) = example_cfgs("runtime_budget.as")
    out, report = optimize(cfg)
    assert report.changes == []
    assert format_cfg(out) == format_cfg(cfg)


def test_repeat_zero_still_not_folded_across_blocks():
    body = '    repeat 0 {\n      llm("x");\n    }\n    return 1;'
    _, out, _ = opt_one(body)
    assert len(calls(out)) == 1  # the head's compare reads counters defined in other blocks


# -------------------------------------------------------------- unreachable code


def test_code_after_return_removed():
    body = '    return 1;\n    llm("never");'
    cfg, out, report = opt_one(body)
    assert any(label.startswith("U") for label in cfg.blocks)
    assert list(out.blocks) == ["entry"]
    assert report.after["calls"] == 0
    assert any(c.startswith("removed unreachable block U1") for c in report.changes)


# ------------------------------------------------------------- report / artifact


def test_report_to_dict():
    (cfg,) = example_cfgs("optimize_demo.as")
    _, report = optimize(cfg)
    data = report.to_dict()
    assert set(data) == {"before", "after", "changes", "iterations"}
    assert data["before"] == {"instructions": 14, "calls": 4}
    json.dumps(data)


def test_optimized_artifact():
    cfgs = example_cfgs("optimize_demo.as") + example_cfgs("valid_report.as")
    results = [optimize(c) for c in cfgs]
    art = optimized_artifact(results)
    assert set(art) == {"text", "data"}
    assert "instructions 14 -> 10, tool calls 4 -> 2" in art["text"]
    assert "instructions 10 -> 10, tool calls 5 -> 5" in art["text"]
    assert "line 8: duplicate call web_search(topic) replaced by copy of first (line 7)" in art["text"]
    assert format_cfg(results[0][0]) in art["text"]
    data = art["data"]
    assert [t["name"] for t in data["tasks"]] == ["research", "report"]
    first = data["tasks"][0]
    assert first["cfg"]["name"] == "research"
    assert first["cfg"]["mermaid"].startswith("flowchart TD")
    assert first["report"] == results[0][1].to_dict()
    assert data["before"] == {"instructions": 24, "calls": 9}
    assert data["after"] == {"instructions": 20, "calls": 7}
    json.dumps(art)


def test_optimized_artifact_empty():
    art = optimized_artifact([])
    assert art["data"] == {"tasks": [], "before": {"instructions": 0, "calls": 0}, "after": {"instructions": 0, "calls": 0}}
