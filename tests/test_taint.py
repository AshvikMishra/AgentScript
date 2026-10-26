"""Taint analysis tests: sources, propagation, sanitize, joins, loops, sinks, report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscript import ir
from agentscript.cfg import build_cfg, link_blocks
from agentscript.diagnostics import CompileError, PathStep
from agentscript.ir import CFG, BasicBlock, Call, Const, Jump, Return, Var
from agentscript.irgen import lower
from agentscript.lexer import tokenize
from agentscript.parser import parse
from agentscript.semantic import analyze
from agentscript.taint import TaintInfo, TaintReport, analyze_taint, solve, transfer
from agentscript.typesys import BOOL

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
ALL_TOOLS = "web_search, read_file, llm, send_email, delete_file, sanitize, confirm"


def cfgs_of(source: str) -> list[CFG]:
    agent = parse(tokenize(source))
    analyze(agent)
    return [build_cfg(fn) for fn in lower(agent)]


def program(body: str, ret: str = "bool", params: str = "topic: string") -> str:
    return (
        "agent A {\n"
        f"  permit {ALL_TOOLS};\n"
        "  budget calls = 20;\n"
        f"  task t({params}) -> {ret} {{\n"
        f"{body}\n"
        "  }\n"
        "}\n"
    )


def taint_of(body: str, **kw) -> TaintReport:
    return analyze_taint(cfgs_of(program(body, **kw)))


def violation(body: str, **kw) -> CompileError:
    with pytest.raises(CompileError) as exc:
        taint_of(body, **kw)
    return exc.value


def untrusted_names(report: TaintReport) -> set[str]:
    return {u.var for t in report.tasks for u in t.untrusted}


def example(name: str) -> str:
    return (EXAMPLES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ examples


def test_taint_injection_example_reports_e401_with_path():
    with pytest.raises(CompileError) as exc:
        analyze_taint(cfgs_of(example("taint_injection.as")))
    diag = exc.value.diagnostic
    assert (diag.code, diag.phase, diag.line, diag.col) == ("E401", "taint", 9, 14)
    assert diag.message == (
        "untrusted data from web_search (line 6) reaches privileged tool 'send_email' "
        "(line 9), argument 2; pass it through sanitize first"
    )
    path = diag.path
    assert path[0] == PathStep(
        6, 15, "raw = call web_search(topic)  <- web_search returns untrusted data"
    )
    assert any(s.line == 7 and "call llm" in s.note for s in path)
    assert path[-1].line == 9 and path[-1].col == 14
    assert path[-1].note.endswith("<- privileged sink")
    assert [s.line for s in path] == sorted(s.line for s in path)


def test_taint_injection_error_carries_full_report():
    with pytest.raises(CompileError) as exc:
        analyze_taint(cfgs_of(example("taint_injection.as")))
    art = exc.value.artifact
    assert set(art) == {"text", "data"}
    data = art["data"]
    assert data["violation"]["code"] == "E401"
    assert data["violation"]["line"] == 9
    assert data["tainted_lines"] == [6, 7]
    (task,) = data["tasks"]
    (sink,) = task["sinks"]
    assert sink["tool"] == "send_email" and sink["status"] == "VIOLATION"
    assert [a["taint"] for a in sink["args"]] == ["trusted", "untrusted"]
    assert "VIOLATION" in art["text"] and "E401" in art["text"]
    json.dumps(art)  # JSON-serializable


def test_valid_report_passes_raw_untrusted_clean_trusted():
    report = analyze_taint(cfgs_of(example("valid_report.as")))
    assert report.violation is None
    names = untrusted_names(report)
    assert "raw" in names
    assert "clean" not in names and "summary" not in names
    (task,) = report.tasks
    (san,) = task.sanitized
    assert san.var == "clean" and san.input_untrusted
    (sink,) = task.sinks
    assert sink.ok and sink.line == 10
    art = report.artifact()
    assert art["data"]["violation"] is None
    assert art["data"]["tainted_lines"] == [6, 7]
    assert "OK" in art["text"]
    assert "clean" in art["text"] and "web_search (line 6)" in art["text"]


def _semantically_valid_examples() -> list[str]:
    names = []
    for entry in MANIFEST:
        expect = entry["expect"]
        if expect is None or expect["phase"] not in ("lexer", "parser", "semantic"):
            names.append(entry["file"])
    return names


@pytest.mark.parametrize("name", _semantically_valid_examples())
def test_examples_past_semantics_match_manifest(name):
    entry = next(e for e in MANIFEST if e["file"] == name)
    cfgs = cfgs_of(example(name))
    expect = entry["expect"]
    if expect is not None and expect["phase"] == "taint":
        with pytest.raises(CompileError) as exc:
            analyze_taint(cfgs)
        d = exc.value.diagnostic
        assert (d.code, d.line, d.col) == (expect["code"], expect["line"], expect["col"])
    else:
        report = analyze_taint(cfgs)
        assert report.violation is None


def test_deterministic():
    a = analyze_taint(cfgs_of(example("valid_report.as"))).artifact()
    b = analyze_taint(cfgs_of(example("valid_report.as"))).artifact()
    assert a == b


# --------------------------------------------------------------- propagation


def test_index_of_untrusted_list_is_untrusted():
    report = taint_of("    let r = web_search(topic);\n    let x = r[1];\n    return true;")
    assert {"r", "x"} <= untrusted_names(report)


def test_untrusted_index_taints_result():
    # No tool returns an untrusted int, so this flow is only reachable in hand-made IR.
    state = {"i": TaintInfo("read_file", 1, 1, ())}
    transfer(ir.Index(Var("x"), Var("xs"), Var("i"), line=2, col=3), state)
    assert state["x"].source_tool == "read_file"
    assert state["x"].steps[-1] == PathStep(2, 3, "x = xs[i]")


def test_trusted_list_indexed_is_trusted():
    taint_of(
        "    let x = xs[0];\n    return send_email(x, x);",
        params="xs: list<string>",
    )


def test_concat_with_untrusted_is_untrusted():
    err = violation(
        "    let page = read_file(topic);\n"
        "    let body = \"Hi \" + page;\n"
        "    return send_email(\"a@b.c\", body);"
    )
    d = err.diagnostic
    assert d.line == 7 and "read_file (line 5)" in d.message and "argument 2" in d.message
    assert [s.line for s in d.path] == [5, 6, 7]


def test_concat_of_trusted_is_trusted():
    taint_of("    let body = \"Hi \" + topic;\n    return send_email(topic, body);")


def test_llm_propagates_taint():
    err = violation(
        "    let page = read_file(topic);\n"
        "    let s = llm(page);\n"
        "    return send_email(\"a@b.c\", s);"
    )
    notes = [s.note for s in err.diagnostic.path]
    assert notes[0].startswith("page = call read_file(topic)")
    assert notes[1] == "s = call llm(page)"


def test_llm_of_trusted_is_trusted():
    taint_of("    let s = llm(topic);\n    return send_email(\"a@b.c\", s);")


def test_sanitize_clears_taint():
    report = taint_of(
        "    let page = read_file(topic);\n"
        "    let c = sanitize(page);\n"
        "    let s = llm(c);\n"
        "    return send_email(\"a@b.c\", s);"
    )
    assert untrusted_names(report) == {"page"}
    (task,) = report.tasks
    assert [s.var for s in task.sanitized] == ["c"]


def test_send_email_first_argument_checked():
    err = violation(
        "    let to = read_file(topic);\n    return send_email(to, \"hello\");"
    )
    assert "argument 1" in err.diagnostic.message


def test_send_email_both_arguments_checked_first_reported():
    err = violation(
        "    let a = read_file(topic);\n"
        "    let b = web_search(topic);\n"
        "    return send_email(a, b[0]);"
    )
    assert "argument 1" in err.diagnostic.message
    assert "read_file" in err.diagnostic.message
    sink = err.artifact["data"]["tasks"][0]["sinks"][0]
    assert [a["taint"] for a in sink["args"]] == ["untrusted", "untrusted"]


def test_delete_file_is_a_sink():
    err = violation(
        "    let p = read_file(topic);\n"
        "    if (confirm(\"go?\")) {\n"
        "      return delete_file(p);\n"
        "    }\n"
        "    return false;"
    )
    assert "'delete_file'" in err.diagnostic.message


def test_taint_through_let_copy():
    err = violation(
        "    let page = read_file(topic);\n"
        "    let copy = page;\n"
        "    let again = copy;\n"
        "    return send_email(\"a@b.c\", again);"
    )
    notes = [s.note for s in err.diagnostic.path]
    assert notes[1:3] == ["copy = page", "again = copy"]


def test_read_file_is_a_source():
    report = taint_of("    let p = read_file(topic);\n    return true;")
    (u,) = report.tasks[0].untrusted
    assert u.var == "p" and u.info.source_tool == "read_file" and u.info.source_line == 5


def test_confirm_and_send_email_results_are_trusted():
    report = taint_of(
        "    let page = read_file(topic);\n"
        "    let ok = confirm(page);\n"
        "    return ok;"
    )
    assert untrusted_names(report) == {"page"}


def test_untrusted_value_not_reaching_sink_is_fine():
    report = taint_of(
        "    let page = read_file(topic);\n"
        "    let s = llm(page);\n"
        "    let sent = send_email(\"a@b.c\", topic);\n"
        "    return sent;"
    )
    assert report.violation is None
    assert report.tasks[0].sinks[0].ok


def test_return_of_untrusted_is_fine():
    taint_of("    return read_file(topic);", ret="string")


# -------------------------------------------------------------- control flow


def test_join_at_if_else_tainted_on_one_branch():
    body = (
        "    let page = read_file(topic);\n"
        "    let msg = \"x\";\n"
        "    if (topic == \"a\") {\n"
        "      let r = llm(page);\n"
        "      return send_email(\"a@b.c\", r);\n"
        "    } else {\n"
        "      let q = \"safe\";\n"
        "    }\n"
        "    return false;"
    )
    err = violation(body)
    assert err.diagnostic.line == 9


def test_join_after_if_carries_taint_from_one_branch():
    # After the join: `page` (untrusted on both paths) and `x` (untrusted on the then
    # path only) are untrusted; `y` (trusted) is not.
    cfgs = cfgs_of(program(
        "    let page = read_file(topic);\n"
        "    if (topic == \"a\") {\n"
        "      let x = llm(page);\n"
        "    } else {\n"
        "      let y = topic;\n"
        "    }\n"
        "    return send_email(\"a@b.c\", page);"
    ))
    (cfg,) = cfgs
    entries, _ = solve(cfg)
    join = list(cfg.blocks)[-1]
    assert "page" in entries[join]
    assert "x" in entries[join]  # union: untrusted on the then-branch only
    assert "y" not in entries[join]
    with pytest.raises(CompileError):
        analyze_taint(cfgs)


def test_join_provenance_from_first_predecessor():
    # Hand-made CFG: x is untrusted on both preds with different sources; the first
    # predecessor in preds order wins.
    def call(dst: str, tool: str, line: int) -> Call:
        return Call(Var(dst), tool, [Const("p")], line=line, col=1)

    blocks = {
        "entry": BasicBlock("entry", [ir.Branch(Const(True), "A", "B", line=1, col=1)]),
        "A": BasicBlock("A", [call("x", "read_file", 2), Jump("J", line=2, col=1)]),
        "B": BasicBlock("B", [call("x", "web_search", 3), Jump("J", line=3, col=1)]),
        "J": BasicBlock("J", [Return(Var("x"), line=4, col=1)]),
    }
    cfg = CFG("t", [], BOOL, blocks)
    link_blocks(cfg)
    entries, _ = solve(cfg)
    assert entries["J"]["x"].source_tool == "read_file"
    cfg.blocks["J"].preds.reverse()
    entries, _ = solve(cfg)
    assert entries["J"]["x"].source_tool == "web_search"


def test_repeat_loop_fixpoint_converges():
    body = (
        "    let page = read_file(topic);\n"
        "    repeat 3 {\n"
        "      let s = llm(page);\n"
        "      let note = \"tick\";\n"
        "    }\n"
        "    return true;"
    )
    report = taint_of(body)
    (task,) = report.tasks
    assert 2 <= task.iterations <= 5
    # the loop head sees `page` (and `s` from the back edge) as untrusted
    head_states = [v for k, v in task.block_entry.items() if k != "entry"]
    assert any("s" in v and "page" in v for v in head_states)
    assert "s" in untrusted_names(report) and "note" not in untrusted_names(report)
    # the loop counter, bound and condition temps stay trusted
    (cfg,) = cfgs_of(program(body))
    counters = {
        i.dst.name
        for b in cfg.blocks.values()
        for i in b.instrs
        if isinstance(i, ir.BinOp) and i.op in ("<", "+")  # body has no concatenation
    }
    assert counters and not counters & untrusted_names(report)


def test_repeat_loop_taint_into_sink_inside_loop():
    body = (
        "    let page = read_file(topic);\n"
        "    repeat 2 {\n"
        "      let s = llm(page);\n"
        "      let r = send_email(\"a@b.c\", s);\n"
        "    }\n"
        "    return true;"
    )
    err = violation(body)
    assert err.diagnostic.line == 8


def test_repeat_with_variable_count_from_param_is_trusted():
    report = taint_of(
        "    repeat n {\n      let r = send_email(topic, topic);\n    }\n    return true;",
        params="topic: string, n: int",
    )
    assert report.violation is None


def test_implicit_flow_via_if_condition_is_not_tainted():
    """Documented limitation: no implicit flows through branch conditions."""
    report = taint_of(
        "    let page = read_file(topic);\n"
        "    let msg = \"no\";\n"
        "    if (page == \"secret\") {\n"
        "      return send_email(\"a@b.c\", \"yes\");\n"
        "    }\n"
        "    return send_email(\"a@b.c\", msg);"
    )
    assert report.violation is None
    assert all(s.ok for s in report.tasks[0].sinks)


def test_unreachable_code_is_ignored():
    report = taint_of(
        "    return true;\n"
        "    let page = read_file(topic);\n"
        "    return send_email(\"a@b.c\", page);"
    )
    assert report.violation is None
    assert report.tasks[0].sinks == []


def test_single_block_converges_in_one_iteration():
    report = taint_of("    return true;")
    assert report.tasks[0].iterations == 1


# ------------------------------------------------------------------ transfer


def test_transfer_redefinition_to_trusted_removes_var():
    info = TaintInfo("read_file", 1, 1, ())
    state = {"x": info}
    transfer(ir.Assign(Var("x"), Const("lit"), line=2, col=1), state)
    assert state == {}


def test_transfer_binop_takes_first_untrusted_operand():
    a = TaintInfo("read_file", 1, 1, ())
    b = TaintInfo("web_search", 2, 1, ())
    state = {"a": a, "b": b}
    transfer(ir.BinOp(Var("c"), "+", Var("a"), Var("b"), line=3, col=4), state)
    assert state["c"].source_tool == "read_file"
    assert state["c"].steps == (PathStep(3, 4, "c = a + b"),)


def test_transfer_sanitize_and_bool_tools_trust_result():
    info = TaintInfo("read_file", 1, 1, ())
    for tool in ("sanitize", "confirm", "send_email", "delete_file"):
        state = {"x": info, "y": info}
        args = [Var("x"), Var("x")] if tool == "send_email" else [Var("x")]
        transfer(Call(Var("y"), tool, args, line=2, col=1), state)
        assert "y" not in state and "x" in state


def test_transfer_parallel_calls_use_state_before_round():
    info = TaintInfo("read_file", 1, 1, ())
    state = {"p": info}
    round_ = ir.ParallelCalls(
        [
            Call(Var("p"), "sanitize", [Var("p")], line=2, col=1),
            Call(Var("q"), "llm", [Var("p")], line=2, col=5),
        ]
    )
    transfer(round_, state)
    assert "p" not in state and state["q"].source_tool == "read_file"


# -------------------------------------------------------------- multi-task


def test_multiple_tasks_reported_violation_in_second_task():
    source = (
        "agent A {\n"
        f"  permit {ALL_TOOLS};\n"
        "  budget calls = 9;\n"
        "  task good(topic: string) -> bool {\n"
        "    return send_email(\"a@b.c\", topic);\n"
        "  }\n"
        "  task bad(topic: string) -> bool {\n"
        "    let p = read_file(topic);\n"
        "    return send_email(\"a@b.c\", p);\n"
        "  }\n"
        "}\n"
    )
    with pytest.raises(CompileError) as exc:
        analyze_taint(cfgs_of(source))
    assert exc.value.diagnostic.line == 9
    data = exc.value.artifact["data"]
    assert [t["name"] for t in data["tasks"]] == ["good", "bad"]
    assert [t["sinks"][0]["status"] for t in data["tasks"]] == ["OK", "VIOLATION"]
    assert data["tainted_lines"] == [8]
