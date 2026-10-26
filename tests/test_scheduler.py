"""Scheduler tests (M7): dependencies, barriers, rounds, report and artifact."""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from agentscript import ir
from agentscript.cfg import build_cfg, cfg_to_dict, format_cfg
from agentscript.ir import Assign, BasicBlock, BinOp, Call, Const, ParallelCalls, Return, Var
from agentscript.irgen import lower
from agentscript.lexer import tokenize
from agentscript.parser import parse
from agentscript.scheduler import (
    ScheduleReport,
    build_dependencies,
    schedule,
    schedule_artifact,
    schedule_block,
)
from agentscript.semantic import analyze
from agentscript.typesys import INT

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text())


def cfgs_of(source: str) -> list[ir.CFG]:
    agent = parse(tokenize(source))
    analyze(agent)
    return [build_cfg(fn) for fn in lower(agent)]


def example_cfgs(name: str) -> list[ir.CFG]:
    return cfgs_of((EXAMPLES / name).read_text())


def program(body: str, ret: str = "string", params: str = "a: string, b: string", permit: str = "") -> str:
    permit = permit or "web_search, read_file, llm, sanitize, send_email, delete_file, confirm"
    return (
        "agent A {\n"
        f"  permit {permit};\n"
        "  budget calls = 20;\n"
        f"  task t({params}) -> {ret} {{\n"
        f"{body}\n"
        "  }\n"
        "}\n"
    )


def scheduled(body: str, **kw) -> tuple[ir.CFG, ScheduleReport]:
    (cfg,) = cfgs_of(program(body, **kw))
    return schedule(cfg)


def round_texts(report: ScheduleReport, label: str = "entry") -> list[list[str]]:
    (task,) = report.tasks
    for block in task.blocks:
        if block.label == label:
            return block.rounds
    raise KeyError(label)


def flat_instrs(cfg: ir.CFG) -> list[ir.Instr]:
    out: list[ir.Instr] = []
    for block in cfg.blocks.values():
        for instr in block.instrs:
            out.extend(instr.calls if isinstance(instr, ParallelCalls) else [instr])
    return out


def call_position(cfg: ir.CFG, dst: str) -> int:
    """Index of the scheduled entry-block instruction (or round) that writes dst."""
    for k, instr in enumerate(cfg.blocks["entry"].instrs):
        if dst in ir.defined_vars(instr):
            return k
    raise KeyError(dst)


# ------------------------------------------------------------------ examples


def test_parallel_demo_four_to_two_rounds():
    (cfg,) = example_cfgs("parallel_demo.as")
    out, report = schedule(cfg)
    assert (report.rounds_before, report.rounds_after) == (4, 2)
    rounds = round_texts(report)
    assert rounds[0] == [
        "ra = call web_search(a)",
        "rb = call web_search(b)",
        "rc = call web_search(c)",
    ]
    assert rounds[1] == ["t8 = call llm(t7)"]
    first = out.blocks["entry"].instrs[0]
    assert isinstance(first, ParallelCalls)
    assert [c.dst.name for c in first.calls] == ["ra", "rb", "rc"]
    assert (first.line, first.col) == (first.calls[0].line, first.calls[0].col)
    assert first.line == 6


def test_valid_report_five_to_five():
    (cfg,) = example_cfgs("valid_report.as")
    out, report = schedule(cfg)
    assert (report.rounds_before, report.rounds_after) == (5, 5)
    assert round_texts(report) == [
        ["raw = call web_search(topic)"],
        ["clean = call sanitize(t1)"],
        ["summary = call llm(t2)"],
        ['t3 = call confirm("Send report?")'],
    ]
    assert round_texts(report, "L1") == [['t4 = call send_email("me@example.com", summary)']]
    assert not any(isinstance(i, ParallelCalls) for b in out.blocks.values() for i in b.instrs)
    # Already sequential: the schedule leaves the program unchanged.
    assert format_cfg(out) == format_cfg(cfg)


def test_report_to_dict_shape():
    (cfg,) = example_cfgs("parallel_demo.as")
    _, report = schedule(cfg)
    assert report.to_dict() == {
        "tasks": [
            {
                "name": "scout",
                "rounds_before": 4,
                "rounds_after": 2,
                "blocks": [
                    {
                        "label": "entry",
                        "rounds": [
                            [
                                "ra = call web_search(a)",
                                "rb = call web_search(b)",
                                "rc = call web_search(c)",
                            ],
                            ["t8 = call llm(t7)"],
                        ],
                    }
                ],
            }
        ],
        "rounds_before": 4,
        "rounds_after": 2,
    }


def test_artifact_text_and_data():
    results = [schedule(c) for c in example_cfgs("parallel_demo.as")]
    art = schedule_artifact(results)
    assert set(art) == {"text", "data"}
    assert (
        "round 1: ra = call web_search(a) | rb = call web_search(b) | rc = call web_search(c)"
        in art["text"]
    )
    assert "round 2: t8 = call llm(t7)" in art["text"]
    assert "rounds 4 -> 2" in art["text"]
    assert art["text"].splitlines()[-1] == "total: rounds 4 -> 2"
    assert art["data"]["rounds_before"] == 4
    assert art["data"]["rounds_after"] == 2
    assert art["data"]["tasks"][0]["name"] == "scout"
    json.dumps(art)  # JSON-serialisable


def test_artifact_totals_over_several_tasks():
    source = (
        "agent A {\n"
        "  permit web_search, llm;\n"
        "  budget calls = 9;\n"
        "  task one(a: string) -> string { let x = web_search(a); let y = web_search(a); return a; }\n"
        "  task two(a: string) -> string { return llm(a); }\n"
        "}\n"
    )
    results = [schedule(c) for c in cfgs_of(source)]
    art = schedule_artifact(results)
    assert [t["name"] for t in art["data"]["tasks"]] == ["one", "two"]
    assert (art["data"]["rounds_before"], art["data"]["rounds_after"]) == (3, 2)
    assert "task one: rounds 2 -> 1" in art["text"]
    assert "task two: rounds 1 -> 1" in art["text"]
    assert art["text"].endswith("total: rounds 3 -> 2")


def test_artifact_of_no_tasks():
    art = schedule_artifact([])
    assert art["text"] == "total: rounds 0 -> 0"
    assert art["data"] == {"tasks": [], "rounds_before": 0, "rounds_after": 0}


@pytest.mark.parametrize("name", [e["file"] for e in MANIFEST if e.get("expect") is None])
def test_valid_examples_schedule_to_valid_cfgs(name):
    for cfg in example_cfgs(name):
        out, report = schedule(cfg)
        assert_valid(cfg, out)
        assert report.rounds_before == ir.count_calls(cfg)
        assert 1 <= report.rounds_after <= report.rounds_before or report.rounds_before == 0


# --------------------------------------------------------------- invariants


def assert_valid(before: ir.CFG, after: ir.CFG) -> None:
    """Every block ends with exactly one terminator; instructions are preserved exactly once."""
    assert list(after.blocks) == list(before.blocks)
    for label, block in after.blocks.items():
        assert block.instrs, label
        assert isinstance(block.terminator, ir.TERMINATORS)
        assert not any(isinstance(i, ir.TERMINATORS) for i in block.instrs[:-1])
        assert block.terminator == before.blocks[label].terminator
        assert block.succs == before.blocks[label].succs
        assert block.preds == before.blocks[label].preds
        for instr in block.instrs:
            if isinstance(instr, ParallelCalls):
                assert len(instr.calls) >= 2
        old = Counter(repr(i) for i in before.blocks[label].instrs)
        new = Counter(
            repr(i)
            for instr in block.instrs
            for i in (instr.calls if isinstance(instr, ParallelCalls) else [instr])
        )
        assert old == new, label
    assert ir.count_instructions(after) == ir.count_instructions(before)
    assert ir.count_calls(after) == ir.count_calls(before)


def test_input_is_not_mutated():
    (cfg,) = example_cfgs("parallel_demo.as")
    snapshot = copy.deepcopy(cfg)
    out, _ = schedule(cfg)
    assert cfg == snapshot
    assert out is not cfg
    assert out.blocks["entry"] is not cfg.blocks["entry"]


def test_deterministic():
    (cfg,) = example_cfgs("parallel_demo.as")
    first = schedule(cfg)
    second = schedule(cfg)
    assert cfg_to_dict(first[0]) == cfg_to_dict(second[0])
    assert first[1].to_dict() == second[1].to_dict()


def test_rescheduling_is_idempotent():
    (cfg,) = example_cfgs("parallel_demo.as")
    once, report1 = schedule(cfg)
    twice, report2 = schedule(once)
    assert format_cfg(once) == format_cfg(twice)
    assert report1.to_dict() == report2.to_dict()


def test_branches_and_loops_stay_valid():
    body = (
        "    let x = web_search(a);\n"
        "    repeat 2 { let y = web_search(b); let z = read_file(b); }\n"
        "    if (x[0] == b) { let p = llm(a); let q = llm(b); return p + q; }\n"
        "    return a;"
    )
    (cfg,) = cfgs_of(program(body))
    out, report = schedule(cfg)
    assert_valid(cfg, out)
    assert report.rounds_before == 5
    # loop body: two independent calls -> one round; the if-then block likewise.
    assert report.rounds_after == 3


# ------------------------------------------------------------- barriers (L3)


def test_barrier_keeps_calls_on_their_sides():
    body = (
        "    let x = web_search(a);\n"
        '    let s = send_email("me@example.com", "hi");\n'
        "    let y = web_search(b);\n"
        "    return a;"
    )
    out, report = scheduled(body)
    assert round_texts(report) == [
        ["x = call web_search(a)"],
        ['s = call send_email("me@example.com", "hi")'],
        ["y = call web_search(b)"],
    ]
    assert call_position(out, "x") < call_position(out, "s") < call_position(out, "y")
    assert (report.rounds_before, report.rounds_after) == (3, 3)


def test_barrier_alone_in_its_round_between_groups():
    body = (
        "    let x1 = web_search(a);\n"
        "    let x2 = web_search(b);\n"
        '    let ok = confirm("go?");\n'
        "    let y1 = read_file(a);\n"
        "    let y2 = read_file(b);\n"
        "    return a;"
    )
    _, report = scheduled(body)
    assert round_texts(report) == [
        ["x1 = call web_search(a)", "x2 = call web_search(b)"],
        ['ok = call confirm("go?")'],
        ["y1 = call read_file(a)", "y2 = call read_file(b)"],
    ]
    assert (report.rounds_before, report.rounds_after) == (5, 3)


@pytest.mark.parametrize("tool", ["send_email", "delete_file", "confirm"])
def test_each_barrier_tool_is_ordered(tool):
    args = '("me@example.com", "x")' if tool == "send_email" else '("x")'
    body = f"    let p = llm(a);\n    let q = {tool}{args};\n    let r = llm(b);\n    return a;"
    _, report = scheduled(body)
    assert [len(r) for r in round_texts(report)] == [1, 1, 1]


def test_two_barriers_keep_their_order():
    body = (
        '    let s = send_email("x@example.com", a);\n'
        '    let ok = confirm("go?");\n'
        "    return a;"
    )
    _, report = scheduled(body)
    assert round_texts(report) == [
        ['s = call send_email("x@example.com", a)'],
        ['ok = call confirm("go?")'],
    ]


def test_non_barrier_calls_merge_into_one_round():
    body = (
        "    let p = llm(a);\n"
        "    let q = sanitize(b);\n"
        "    let r = read_file(a);\n"
        "    let s = web_search(b);\n"
        "    return a;"
    )
    out, report = scheduled(body)
    assert (report.rounds_before, report.rounds_after) == (4, 1)
    first = out.blocks["entry"].instrs[0]
    assert isinstance(first, ParallelCalls)
    assert [c.tool for c in first.calls] == ["llm", "sanitize", "read_file", "web_search"]


# ------------------------------------------------------- data dependencies


def test_true_dependency_chain_is_sequential():
    body = "    let p = llm(a);\n    let q = llm(p);\n    let r = llm(q);\n    return r;"
    _, report = scheduled(body)
    assert round_texts(report) == [
        ["p = call llm(a)"],
        ["q = call llm(p)"],
        ["r = call llm(q)"],
    ]


def test_dependency_through_non_call_instructions():
    body = (
        "    let p = llm(a);\n"
        '    let q = llm(p + "!");\n'
        "    let r = llm(b);\n"
        "    return q + r;"
    )
    out, report = scheduled(body)
    # r is independent of p, so it joins p's round; q waits for t1 = p + "!".
    assert round_texts(report) == [
        ["p = call llm(a)", "r = call llm(b)"],
        ["q = call llm(t1)"],
    ]
    texts = [ir.format_instr(i) for i in out.blocks["entry"].instrs]
    assert texts.index('t1 = p + "!"') < texts.index("q = call llm(t1)")


def test_non_calls_are_emitted_before_ready_calls_in_original_order():
    body = "    let p = llm(a);\n    let n = 2 * 3;\n    let m = n + 1;\n    return a;"
    out, _ = scheduled(body)
    texts = [ir.format_instr(i) for i in out.blocks["entry"].instrs]
    assert texts == ["n = 2 * 3", "m = n + 1", "p = call llm(a)", "return a"]


def test_build_dependencies_kinds():
    instrs = [
        Assign(Var("x"), Const(1)),  # 0: writes x
        BinOp(Var("y"), "+", Var("x"), Const(1)),  # 1: reads x (true on 0)
        Assign(Var("x"), Const(2)),  # 2: writes x (anti on 1, output on 0)
        Call(Var("z"), "llm", [Var("q")]),  # 3: independent
        Call(Var("w"), "confirm", [Const("ok?")]),  # 4: barrier after call 3
        Call(Var("v"), "llm", [Const("a")]),  # 5: after the barrier 4
        Assign(Var("u"), Var("v")),  # 6: true on 5
    ]
    deps = build_dependencies(instrs)
    assert deps == [set(), {0}, {0, 1}, set(), {3}, {4}, {5}]


def test_anti_dependency_respected_by_hand_built_block():
    # q reads x; a later call writes x (only possible in hand-made IR or loop counters):
    # the write must not join or precede the read's round.
    block = BasicBlock(
        "entry",
        [
            Call(Var("q"), "llm", [Var("x")], line=1, col=1),
            Call(Var("x"), "llm", [Const("a")], line=2, col=1),
            Return(Var("q"), line=3, col=1),
        ],
    )
    rounds = schedule_block(block)
    assert [[c.dst.name for c in r] for r in rounds] == [["q"], ["x"]]
    assert [ir.format_instr(i) for i in block.instrs] == [
        "q = call llm(x)",
        'x = call llm("a")',
        "return q",
    ]


def test_output_dependency_respected_by_hand_built_block():
    block = BasicBlock(
        "entry",
        [
            Call(Var("x"), "llm", [Const("a")], line=1, col=1),
            Call(Var("x"), "llm", [Const("b")], line=2, col=1),
            Call(Var("y"), "llm", [Const("c")], line=3, col=1),
            Return(Var("x"), line=4, col=1),
        ],
    )
    rounds = schedule_block(block)
    assert [[ir.format_instr(c) for c in r] for r in rounds] == [
        ['x = call llm("a")', 'y = call llm("c")'],
        ['x = call llm("b")'],
    ]


def test_anti_dependency_on_non_call_waits_for_call():
    # The call reads x and the BinOp writes x, so the BinOp is not hoisted above the call
    # even though non-calls are normally emitted first (anti dependency).
    block = BasicBlock(
        "entry",
        [
            Call(Var("q"), "llm", [Var("x")], line=1, col=1),
            BinOp(Var("x"), "+", Const(1), Const(2), line=2, col=1),
            Return(Var("x"), line=3, col=1),
        ],
    )
    schedule_block(block)
    assert [ir.format_instr(i) for i in block.instrs] == [
        "q = call llm(x)",
        "x = 1 + 2",
        "return x",
    ]


def test_block_without_calls_is_unchanged():
    body = "    let n = 2 * 3;\n    return n;"
    (cfg,) = cfgs_of(program(body, ret="int", params=""))
    out, report = schedule(cfg)
    assert format_cfg(out) == format_cfg(cfg)
    assert report.tasks[0].blocks == []
    assert (report.rounds_before, report.rounds_after) == (0, 0)


def test_loop_counter_dependencies_in_hand_built_block():
    # k = k + 1 both reads and writes k: it must stay after every reader of the old k.
    block = BasicBlock(
        "entry",
        [
            Call(Var("p"), "llm", [Var("k")], line=1, col=1),
            BinOp(Var("k"), "+", Var("k"), Const(1), line=2, col=1),
            Call(Var("r"), "llm", [Var("k")], line=3, col=1),
            Return(Var("r"), line=4, col=1),
        ],
    )
    schedule_block(block)
    assert [ir.format_instr(i) for i in block.instrs] == [
        "p = call llm(k)",
        "k = k + 1",
        "r = call llm(k)",
        "return r",
    ]


def test_cfg_params_and_metadata_preserved():
    (cfg,) = example_cfgs("parallel_demo.as")
    out, _ = schedule(cfg)
    assert (out.name, out.params, out.return_type, out.entry) == (
        cfg.name,
        cfg.params,
        cfg.return_type,
        cfg.entry,
    )


def test_hand_built_cfg_with_int_task():
    block = BasicBlock(
        "entry",
        [
            Call(Var("a"), "read_file", [Const("x")], line=1, col=3),
            Call(Var("b"), "read_file", [Const("y")], line=2, col=3),
            Return(Const(0), line=3, col=1),
        ],
    )
    cfg = ir.CFG("t", [], INT, {"entry": block})
    out, report = schedule(cfg)
    (group, ret) = out.blocks["entry"].instrs
    assert isinstance(group, ParallelCalls) and (group.line, group.col) == (1, 3)
    assert isinstance(ret, Return)
    assert (report.rounds_before, report.rounds_after) == (2, 1)
    assert len(block.instrs) == 3  # input block untouched


# ------------------------------------------- Index (may raise E603) is ordered against calls


def test_index_after_barrier_call_stays_after_it():
    cfg, report = scheduled(
        '    let xs = web_search(a);\n'
        '    let sent = send_email(b, "hello");\n'
        '    let y = xs[10];\n'
        '    return y;'
    )
    instrs = cfg.blocks["entry"].instrs
    kinds = [type(i).__name__ for i in instrs]
    assert kinds.index("Index") > max(k for k, i in enumerate(instrs) if isinstance(i, Call))


def test_call_after_index_waits_for_it():
    cfg, report = scheduled(
        '    let xs = web_search(a);\n'
        '    let y = xs[10];\n'
        '    let z = read_file(b);\n'
        '    return z;'
    )
    assert report.rounds_after == 2
    instrs = cfg.blocks["entry"].instrs
    order = [type(i).__name__ for i in instrs]
    assert order.index("Index") < [k for k, i in enumerate(instrs) if isinstance(i, Call)][1]


def test_index_dependencies_in_graph():
    xs, y, z = Var("xs"), Var("y"), Var("z")
    body = [
        Call(xs, "web_search", [Const("q")], line=1, col=1),
        ir.Index(y, xs, Const(0), line=2, col=1),
        Call(z, "read_file", [Const("f")], line=3, col=1),
    ]
    deps = build_dependencies(body)
    assert deps[1] == {0} and 1 in deps[2]


def test_index_before_all_calls_does_not_serialize_them():
    cfg, report = scheduled(
        '    let p = web_search(a);\n'
        '    let q = web_search(b);\n'
        '    let r = web_search(a + b);\n'
        '    let x = p[0] + q[0] + r[0];\n'
        '    return llm(x);'
    )
    assert (report.rounds_before, report.rounds_after) == (4, 2)


@pytest.mark.parametrize(
    "body, params, args",
    [
        (
            '    let xs = web_search("q");\n    let sent = send_email(to, "hello");\n'
            '    let y = xs[10];\n    return y;',
            "to: string", {"to": "bob"},
        ),
        (
            '    let xs = web_search("q");\n    let y = xs[10];\n    let z = read_file(p);\n    return z;',
            "p: string", {"p": "f"},
        ),
        (
            '    let ok = confirm("go?");\n    let xs = web_search("q");\n    let y = xs[5];\n'
            '    let z = llm(y);\n    return z;',
            "", {},
        ),
    ],
)
def test_scheduled_run_matches_sequential_run(body, params, args):
    from agentscript.pipeline import run_source

    src = program(body, params=params)
    seq = run_source(src, "t", args, parallel=False)
    par = run_source(src, "t", args, parallel=True)
    strip = lambda r: ([(c["tool"], c["args"]) for c in r["calls"]], [d["code"] for d in r["diagnostics"]],
                       r["value"], r["calls_used"])
    assert strip(seq) == strip(par)
