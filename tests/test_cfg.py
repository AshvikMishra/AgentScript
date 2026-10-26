"""CFG tests: block splitting, succs/preds, reachability, dominators, printing, Mermaid."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentscript import ir
from agentscript.cfg import (
    build_cfg,
    cfg_artifact,
    cfg_to_dict,
    cfg_to_mermaid,
    dominators,
    format_cfg,
    immediate_dominators,
    reachable,
)
from agentscript.diagnostics import CompileError
from agentscript.ir import Branch, Const, IRFunction, Jump, Label, Return, Var
from agentscript.irgen import lower
from agentscript.lexer import tokenize
from agentscript.parser import parse
from agentscript.typesys import INT

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text())


def cfgs_of(source: str) -> list[ir.CFG]:
    return [build_cfg(fn) for fn in lower(parse(tokenize(source)))]


def program(body: str, ret: str = "int", params: str = "", permit: str = "llm") -> str:
    return (
        "agent A {\n"
        f"  permit {permit};\n"
        "  budget calls = 9;\n"
        f"  task t({params}) -> {ret} {{\n"
        f"{body}\n"
        "  }\n"
        "}\n"
    )


def cfg_one(body: str, **kw) -> ir.CFG:
    (cfg,) = cfgs_of(program(body, **kw))
    return cfg


def fn_of(instrs: list[ir.Instr]) -> IRFunction:
    return IRFunction("t", [], INT, instrs)


def shape(cfg: ir.CFG) -> dict[str, tuple[list[str], list[str]]]:
    return {b.label: (b.succs, b.preds) for b in cfg.blocks.values()}


def texts(block: ir.BasicBlock) -> list[str]:
    return [ir.format_instr(i) for i in block.instrs]


def assert_well_formed(cfg: ir.CFG) -> None:
    assert next(iter(cfg.blocks)) == cfg.entry == "entry"
    for block in cfg.blocks.values():
        assert block.instrs, block.label
        terms = [i for i in block.instrs if isinstance(i, ir.TERMINATORS)]
        assert len(terms) == 1 and block.instrs[-1] is terms[0], block.label
        assert not any(isinstance(i, Label) for i in block.instrs)
        for succ in block.succs:
            assert succ in cfg.blocks
            assert block.label in cfg.blocks[succ].preds
        for pred in block.preds:
            assert block.label in cfg.blocks[pred].succs


# ----------------------------------------------------------------- splitting


def test_valid_report_blocks():
    (cfg,) = cfgs_of((EXAMPLES / "valid_report.as").read_text())
    assert list(cfg.blocks) == ["entry", "L1", "L2"]
    assert texts(cfg.blocks["entry"]) == [
        "raw = call web_search(topic)",
        "t1 = raw[0]",
        "clean = call sanitize(t1)",
        't2 = "Summarize: " + clean',
        "summary = call llm(t2)",
        't3 = call confirm("Send report?")',
        "if t3 goto L1 else L2",
    ]
    assert texts(cfg.blocks["L1"]) == [
        't4 = call send_email("me@example.com", summary)',
        "return t4",
    ]
    assert texts(cfg.blocks["L2"]) == ["return false"]
    assert shape(cfg) == {
        "entry": (["L1", "L2"], []),
        "L1": ([], ["entry"]),
        "L2": ([], ["entry"]),
    }
    assert cfg.name == "report" and str(cfg.return_type) == "bool"
    assert reachable(cfg) == {"entry", "L1", "L2"}


def test_repeat_loop_blocks():
    (cfg,) = cfgs_of((EXAMPLES / "runtime_budget.as").read_text())
    assert shape(cfg) == {
        "entry": (["L1"], []),
        "L1": (["L2", "L3"], ["entry", "L2"]),
        "L2": (["L1"], ["L1"]),
        "L3": ([], ["L1"]),
    }


def test_fallthrough_into_label_gets_explicit_jump():
    fn = fn_of(
        [
            ir.Assign(Var("x"), Const(1), line=1, col=1),
            Label("L1", line=2, col=3),
            Return(Var("x"), line=3, col=1),
        ]
    )
    cfg = build_cfg(fn)
    assert texts(cfg.blocks["entry"]) == ["x = 1", "goto L1"]
    jump = cfg.blocks["entry"].terminator
    assert isinstance(jump, Jump) and (jump.line, jump.col) == (2, 3)
    assert shape(cfg) == {"entry": (["L1"], []), "L1": ([], ["entry"])}


def test_label_after_label_makes_jump_only_block():
    fn = fn_of(
        [
            Jump("L1", line=1, col=1),
            Label("L1", line=1, col=1),
            Label("L2", line=1, col=1),
            Return(Const(0), line=2, col=1),
        ]
    )
    cfg = build_cfg(fn)
    assert texts(cfg.blocks["L1"]) == ["goto L2"]
    assert_well_formed(cfg)


def test_code_after_return_becomes_unreachable_u_block():
    cfg = cfg_one("    return 1;\n    let x = 2;\n    return x;")
    assert list(cfg.blocks) == ["entry", "U1"]
    assert texts(cfg.blocks["entry"]) == ["return 1"]
    assert texts(cfg.blocks["U1"]) == ["x = 2", "return x"]
    assert reachable(cfg) == {"entry"}
    assert cfg.blocks["U1"].preds == []
    assert_well_formed(cfg)


def test_several_unreachable_blocks_are_numbered():
    fn = fn_of(
        [
            Return(Const(1), line=1, col=1),
            Return(Const(2), line=2, col=1),
            Return(Const(3), line=3, col=1),
        ]
    )
    cfg = build_cfg(fn)
    assert list(cfg.blocks) == ["entry", "U1", "U2"]
    assert reachable(cfg) == {"entry"}


def test_trailing_open_block_gets_self_jump():
    # Only possible in dead code: `return 1; let x = 2;` falls off the end of the task.
    cfg = cfg_one("    return 1;\n    let x = 2;")
    assert texts(cfg.blocks["U1"]) == ["x = 2", "goto U1"]
    assert cfg.blocks["U1"].succs == ["U1"] and cfg.blocks["U1"].preds == ["U1"]
    assert reachable(cfg) == {"entry"}
    assert_well_formed(cfg)


def test_dead_if_after_return_ends_with_terminator():
    cfg = cfg_one("    return 1;\n    if (true) {\n      let x = 2;\n    }")
    assert list(cfg.blocks) == ["entry", "U1", "L1", "L2"]
    assert texts(cfg.blocks["L2"]) == ["goto L2"]
    assert reachable(cfg) == {"entry"}
    assert_well_formed(cfg)


def test_repeat_body_ending_in_return_leaves_dead_increment():
    cfg = cfg_one("    repeat 2 {\n      return 1;\n    }\n    return 0;")
    assert list(cfg.blocks) == ["entry", "L1", "L2", "U1", "L3"]
    assert texts(cfg.blocks["U1"]) == ["t1 = t1 + 1", "goto L1"]
    assert reachable(cfg) == {"entry", "L1", "L2", "L3"}
    assert cfg.blocks["L1"].preds == ["entry", "U1"]
    assert_well_formed(cfg)


def test_branch_with_identical_targets_lists_pred_once():
    fn = fn_of(
        [
            Branch(Const(True), "L1", "L1", line=1, col=1),
            Label("L1", line=1, col=1),
            Return(Const(0), line=1, col=1),
        ]
    )
    cfg = build_cfg(fn)
    assert cfg.blocks["entry"].succs == ["L1", "L1"]
    assert cfg.blocks["L1"].preds == ["entry"]


def test_build_cfg_does_not_mutate_listing():
    fns = lower(parse(tokenize((EXAMPLES / "valid_report.as").read_text())))
    before = [ir.format_instr(i) for i in fns[0].instrs]
    build_cfg(fns[0])
    assert [ir.format_instr(i) for i in fns[0].instrs] == before


# --------------------------------------------------------------- dominators

DIAMOND = """\
    let a = 1;
    let r = 0;
    if (a == 1) {
      let b = 2;
    } else {
      let c = 3;
    }
    return r;"""


def test_dominators_diamond():
    cfg = cfg_one(DIAMOND)
    assert shape(cfg) == {
        "entry": (["L1", "L2"], []),
        "L1": (["L3"], ["entry"]),
        "L2": (["L3"], ["entry"]),
        "L3": ([], ["L1", "L2"]),
    }
    assert dominators(cfg) == {
        "entry": {"entry"},
        "L1": {"entry", "L1"},
        "L2": {"entry", "L2"},
        "L3": {"entry", "L3"},
    }
    assert immediate_dominators(cfg) == {"entry": None, "L1": "entry", "L2": "entry", "L3": "entry"}


def test_dominators_loop():
    cfg = cfg_one(
        "    let x = 0;\n    repeat 3 {\n      if (x == 0) {\n        let y = 1;\n      }\n    }\n"
        "    return x;"
    )
    # entry -> L1(head) -> L2(body) -> L4(then) -> L5(end) -> L1 ; L1 -> L3(exit)
    assert shape(cfg) == {
        "entry": (["L1"], []),
        "L1": (["L2", "L3"], ["entry", "L5"]),
        "L2": (["L4", "L5"], ["L1"]),
        "L4": (["L5"], ["L2"]),
        "L5": (["L1"], ["L2", "L4"]),
        "L3": ([], ["L1"]),
    }
    dom = dominators(cfg)
    assert dom["L1"] == {"entry", "L1"}
    assert dom["L2"] == {"entry", "L1", "L2"}
    assert dom["L4"] == {"entry", "L1", "L2", "L4"}
    assert dom["L5"] == {"entry", "L1", "L2", "L5"}
    assert dom["L3"] == {"entry", "L1", "L3"}
    idom = immediate_dominators(cfg)
    assert idom == {"entry": None, "L1": "entry", "L2": "L1", "L4": "L2", "L5": "L2", "L3": "L1"}


def test_dominators_nested_if():
    cfg = cfg_one(
        "    let a = 1;\n"
        "    if (a == 1) {\n"
        "      if (a == 2) {\n        let b = 3;\n      }\n"
        "      let c = 4;\n"
        "    }\n"
        "    return a;"
    )
    # entry -T-> L1 -T-> L3 -> L4 ; L1 -F-> L4 ; L4 -> L2 ; entry -F-> L2
    assert shape(cfg) == {
        "entry": (["L1", "L2"], []),
        "L1": (["L3", "L4"], ["entry"]),
        "L3": (["L4"], ["L1"]),
        "L4": (["L2"], ["L1", "L3"]),
        "L2": ([], ["entry", "L4"]),
    }
    assert dominators(cfg) == {
        "entry": {"entry"},
        "L1": {"entry", "L1"},
        "L3": {"entry", "L1", "L3"},
        "L4": {"entry", "L1", "L4"},
        "L2": {"entry", "L2"},
    }
    assert immediate_dominators(cfg) == {
        "entry": None, "L1": "entry", "L3": "L1", "L4": "L1", "L2": "entry"
    }


def test_dominators_guard_block_of_valid_cleanup():
    (cfg,) = cfgs_of((EXAMPLES / "valid_cleanup.as").read_text())
    dom = dominators(cfg)
    assert dom["L1"] == {"entry", "L1"}  # the delete_file block is dominated by the guard L1


def test_dominators_skip_unreachable_blocks():
    cfg = cfg_one("    if (true) {\n      return 1;\n    }\n    return 0;\n    let x = 2;\n    return x;")
    dom = dominators(cfg)
    assert "U1" not in dom
    assert list(dom) == ["entry", "L1", "L2"]


def test_unreachable_pred_ignored_in_intersection():
    cfg = cfg_one("    repeat 2 {\n      return 1;\n    }\n    return 0;")
    # L1 (loop head) has preds entry and the dead U1; only entry counts
    assert dominators(cfg)["L1"] == {"entry", "L1"}


def test_dominators_diamond_by_hand_ir():
    fn = fn_of(
        [
            Branch(Var("c"), "A", "B", line=1, col=1),
            Label("A", line=1, col=1),
            Jump("J", line=1, col=1),
            Label("B", line=1, col=1),
            Jump("J", line=1, col=1),
            Label("J", line=1, col=1),
            Return(Const(0), line=1, col=1),
        ]
    )
    cfg = build_cfg(fn)
    assert dominators(cfg)["J"] == {"entry", "J"}


# ----------------------------------------------------------------- printing


def test_format_cfg_valid_report():
    (cfg,) = cfgs_of((EXAMPLES / "valid_report.as").read_text())
    text = format_cfg(cfg)
    lines = text.splitlines()
    assert lines[0] == "task report(topic: string) -> bool"
    assert lines[1] == "  entry:"
    assert lines[2] == "      preds: -"
    assert lines[3] == "      succs: L1, L2"
    assert "      raw = call web_search(topic)             ; line 6" in lines
    assert "  L1:" in lines and "  L2:" in lines
    assert "unreachable" not in text


def test_format_cfg_marks_unreachable():
    cfg = cfg_one("    return 1;\n    return 2;")
    text = format_cfg(cfg)
    assert "  U1:  (unreachable)" in text.splitlines()


def test_cfg_to_dict():
    cfg = cfg_one("    return 1;\n    return 2;")
    data = cfg_to_dict(cfg)
    assert data == {
        "name": "t",
        "entry": "entry",
        "blocks": [
            {
                "label": "entry",
                "instrs": [{"text": "return 1", "op": "Return", "line": 5, "col": 5}],
                "succs": [],
                "preds": [],
                "reachable": True,
            },
            {
                "label": "U1",
                "instrs": [{"text": "return 2", "op": "Return", "line": 6, "col": 5}],
                "succs": [],
                "preds": [],
                "reachable": False,
            },
        ],
    }


def test_mermaid_contains_every_block_and_branch_labels():
    (cfg,) = cfgs_of((EXAMPLES / "valid_report.as").read_text())
    text = cfg_to_mermaid(cfg)
    lines = text.splitlines()
    assert lines[0] == "flowchart TD"
    nodes = [l for l in lines if re.match(r"  B\d+\[", l)]
    assert len(nodes) == len(cfg.blocks)
    for label, node in zip(cfg.blocks, nodes):
        assert node.split('["')[1].startswith(label)
    assert "  B0 -->|T| B1" in lines
    assert "  B0 -->|F| B2" in lines


def test_mermaid_escapes_quotes_and_brackets():
    (cfg,) = cfgs_of((EXAMPLES / "optimize_demo.as").read_text())
    text = cfg_to_mermaid(cfg)
    for line in text.splitlines()[1:]:
        m = re.fullmatch(r'  B\d+\["(.*)"\]', line)
        if m:
            inner = m.group(1)
            assert '"' not in inner
            assert "<" not in inner.replace("<br/>", "")
            assert ">" not in inner.replace("<br/>", "")
    assert "#quot;debug#quot;" in text


def test_mermaid_escape_special_characters():
    cfg = cfg_one('    let s = "<a href=\\"x\\">#&`\\\\";\n    return 0;')
    text = cfg_to_mermaid(cfg)
    node = text.splitlines()[1]
    assert "#lt;a href=#92;#quot;x#92;#quot;#gt;#35;#amp;#96;#92;#92;#quot;" in node
    inner = re.fullmatch(r'  B0\["(.*)"\]', node).group(1)
    for ch in '"`&\\':
        assert ch not in inner


def test_mermaid_loop_edges_and_unreachable_class():
    cfg = cfg_one("    repeat 2 {\n      return 1;\n    }\n    return 0;")
    text = cfg_to_mermaid(cfg)
    lines = text.splitlines()
    ids = {label: f"B{i}" for i, label in enumerate(cfg.blocks)}
    assert f"  {ids['entry']} --> {ids['L1']}" in lines
    assert f"  {ids['L1']} -->|T| {ids['L2']}" in lines
    assert f"  {ids['L1']} -->|F| {ids['L3']}" in lines
    assert f"  {ids['U1']} --> {ids['L1']}" in lines
    assert f"  class {ids['U1']} unreachable" in lines


def test_cfg_artifact_shape():
    source = (EXAMPLES / "valid_report.as").read_text()
    cfgs = cfgs_of(source)
    art = cfg_artifact(cfgs)
    assert art["text"] == format_cfg(cfgs[0])
    (task,) = art["data"]["tasks"]
    assert task["name"] == "report"
    assert task["mermaid"] == cfg_to_mermaid(cfgs[0])
    assert task["dominators"] == {
        "entry": ["entry"],
        "L1": ["L1", "entry"],
        "L2": ["L2", "entry"],
    }
    assert [b["label"] for b in task["blocks"]] == ["entry", "L1", "L2"]
    json.dumps(art)


def test_cfg_artifact_multiple_tasks():
    source = (
        "agent A {\n  permit llm;\n  budget calls = 1;\n"
        "  task one() -> int {\n    return 1;\n  }\n"
        "  task two() -> int {\n    return 2;\n  }\n"
        "}\n"
    )
    cfgs = cfgs_of(source)
    art = cfg_artifact(cfgs)
    assert art["text"] == format_cfg(cfgs[0]) + "\n\n" + format_cfg(cfgs[1])
    assert [t["name"] for t in art["data"]["tasks"]] == ["one", "two"]


def test_cfg_is_deterministic():
    source = (EXAMPLES / "optimize_demo.as").read_text()
    assert cfg_artifact(cfgs_of(source)) == cfg_artifact(cfgs_of(source))


# ---------------------------------------------------- every parseable example


def _lowerable_examples():
    out = []
    for entry in MANIFEST:
        try:
            agent = parse(tokenize((EXAMPLES / entry["file"]).read_text()))
            lower(agent)
        except (CompileError, KeyError):  # lexer/parser errors; undeclared names
            continue
        out.append(entry["file"])
    return out


def test_most_examples_are_lowerable():
    assert len(_lowerable_examples()) >= 14


@pytest.mark.parametrize("name", _lowerable_examples())
def test_every_example_builds_a_well_formed_cfg(name):
    for cfg in cfgs_of((EXAMPLES / name).read_text()):
        assert_well_formed(cfg)
        targets = set()
        for block in cfg.blocks.values():
            term = block.terminator
            if isinstance(term, Jump):
                targets.add(term.target)
            elif isinstance(term, Branch):
                targets |= {term.if_true, term.if_false}
        assert targets <= set(cfg.blocks)
        dom = dominators(cfg)
        for label, doms in dom.items():
            assert cfg.entry in doms and label in doms
        assert len(cfg_to_mermaid(cfg).splitlines()) > len(cfg.blocks)
