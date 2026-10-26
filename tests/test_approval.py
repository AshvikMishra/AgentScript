"""Approval analysis tests (A1-A3): confirm guards, dominators, E501/E502 and their paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscript import ir
from agentscript.approval import ApprovalReport, analyze_approval, confirm_values
from agentscript.cfg import build_cfg
from agentscript.diagnostics import CompileError
from agentscript.irgen import lower
from agentscript.lexer import tokenize
from agentscript.parser import parse
from agentscript.semantic import analyze

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = {e["file"]: e for e in json.loads((EXAMPLES / "manifest.json").read_text())}


def cfgs_of(source: str) -> list[ir.CFG]:
    agent = parse(tokenize(source))
    analyze(agent)
    return [build_cfg(fn) for fn in lower(agent)]


def program(body: str, params: str = "p: string, flag: bool") -> str:
    return (
        "agent A {\n"
        "  permit confirm, delete_file, send_email;\n"
        "  budget calls = 50;\n"
        f"  task t({params}) -> bool {{\n"
        f"{body}\n"
        "  }\n"
        "}\n"
    )


def approve(body: str, **kw) -> ApprovalReport:
    return analyze_approval(cfgs_of(program(body, **kw)))


def reject(body: str, **kw) -> CompileError:
    with pytest.raises(CompileError) as info:
        approve(body, **kw)
    return info.value


def example(name: str) -> str:
    return (EXAMPLES / name).read_text()


def verdicts(report: ApprovalReport) -> list[str]:
    return [c.verdict for t in report.tasks for c in t.calls]


# ------------------------------------------------------------------ examples


def test_valid_cleanup_passes_with_let_guard():
    report = analyze_approval(cfgs_of(example("valid_cleanup.as")))
    (task,) = report.tasks
    assert report.violation is None
    assert [(g.label, g.confirm_line, g.condition) for g in task.guards] == [("L1", 6, "ok")]
    (call,) = task.calls
    assert (call.tool, call.line, call.block, call.guarded_by, call.verdict) == (
        "delete_file", 8, "L1", "L1", "approved")


def test_valid_report_passes_send_email_is_not_irreversible():
    report = analyze_approval(cfgs_of(example("valid_report.as")))
    assert report.tasks[0].calls == []
    assert report.tasks[0].guards[0].condition == "confirm(...)"


def test_approval_missing_is_e501_through_force_edge():
    with pytest.raises(CompileError) as info:
        analyze_approval(cfgs_of(example("approval_missing.as")))
    diag = info.value.diagnostic
    expect = MANIFEST["approval_missing.as"]["expect"]
    assert (diag.code, diag.phase, diag.line, diag.col) == (
        expect["code"], expect["phase"], expect["line"], expect["col"])
    assert (diag.line, diag.col) == (7, 14)
    assert diag.message == (
        "irreversible call to 'delete_file' (line 7) is reachable without confirm")
    notes = [s.note for s in diag.path]
    assert notes == [
        "task purge starts (entry)",
        "line 6: if force -> true (L1)",
        "delete_file(...) is irreversible and not guarded by confirm",
    ]
    assert (diag.path[1].line, diag.path[1].col) == (6, 5)
    assert (diag.path[-1].line, diag.path[-1].col) == (7, 14)


def test_approval_one_branch_is_e502():
    with pytest.raises(CompileError) as info:
        analyze_approval(cfgs_of(example("approval_one_branch.as")))
    diag = info.value.diagnostic
    expect = MANIFEST["approval_one_branch.as"]["expect"]
    assert (diag.code, diag.phase, diag.line, diag.col) == (
        expect["code"], expect["phase"], expect["line"], expect["col"])
    assert diag.message == (
        "irreversible call to 'delete_file' (line 9) is not guarded by confirm on every "
        "path; the confirm on line 7 does not guard it")
    assert [s.note for s in diag.path] == [
        "task cleanup starts (entry)",
        "line 6: if careful -> false (L2)",
        "delete_file(...) is irreversible and not guarded by confirm",
    ]


@pytest.mark.parametrize("name", sorted(MANIFEST))
def test_manifest_examples_reaching_approval(name):
    """Every example that passes semantic analysis: approval agrees with the manifest."""
    entry = MANIFEST[name]
    expect = entry["expect"]
    if expect is not None and expect["phase"] in ("lexer", "parser", "semantic"):
        pytest.skip("fails before approval")
    cfgs = cfgs_of(example(name))
    if expect is not None and expect["phase"] == "approval":
        with pytest.raises(CompileError) as info:
            analyze_approval(cfgs)
        d = info.value.diagnostic
        assert (d.code, d.line, d.col) == (expect["code"], expect["line"], expect["col"])
    else:
        analyze_approval(cfgs)  # taint examples have no irreversible calls


def test_error_carries_report_artifact():
    with pytest.raises(CompileError) as info:
        analyze_approval(cfgs_of(example("approval_missing.as")))
    art = info.value.artifact
    assert set(art) == {"text", "data"}
    data = art["data"]
    assert data["violation"]["code"] == "E501"
    assert data["violation"]["line"] == 7
    (task,) = data["tasks"]
    assert [(c["line"], c["verdict"], c["guarded_by"]) for c in task["calls"]] == [
        (7, "E501", None), (10, "approved", "L3")]
    assert task["guards"] == [
        {"label": "L3", "confirm_line": 9, "condition": "confirm(...)", "branch_line": 9}]
    assert task["dominators"]["L3"] == ["entry", "L2", "L3"]
    assert task["idom"] == {"entry": None, "L1": "entry", "L2": "entry", "L3": "L2", "L4": "L2"}
    assert "E501 [approval] 7:14" in art["text"]
    assert "guard blocks:" in art["text"]
    json.dumps(art)  # JSON-serializable


def test_artifact_of_passing_program():
    art = analyze_approval(cfgs_of(example("valid_cleanup.as"))).artifact()
    assert art["data"]["violation"] is None
    assert art["data"]["tasks"][0]["calls"][0]["verdict"] == "approved"
    assert "delete_file line 8 in L1: guarded by L1 -> approved" in art["text"]
    assert "L1  (if ok on line 7; confirm on line 6)" in art["text"]
    json.dumps(art)


def test_deterministic():
    source = example("approval_missing.as")
    arts = []
    for _ in range(3):
        with pytest.raises(CompileError) as info:
            analyze_approval(cfgs_of(source))
        arts.append(json.dumps(info.value.artifact, sort_keys=True))
    assert len(set(arts)) == 1


# ---------------------------------------------------------------- unit cases


def test_direct_if_confirm_is_a_guard():
    report = approve(
        '    if (confirm("go?")) {\n'
        "      return delete_file(p);\n"
        "    }\n"
        "    return false;")
    assert verdicts(report) == ["approved"]
    assert report.tasks[0].guards[0].condition == "confirm(...)"


def test_delete_in_else_branch_of_confirm_is_e502():
    err = reject(
        '    if (confirm("go?")) {\n'
        "      return true;\n"
        "    } else {\n"
        "      return delete_file(p);\n"
        "    }")
    d = err.diagnostic
    assert (d.code, d.line) == ("E502", 8)
    assert "the confirm on line 5 does not guard it" in d.message
    notes = [s.note for s in d.path]
    assert notes[1] == "line 5: confirm(...) is asked here"
    assert notes[2] == "line 5: if confirm(...) -> false (L2)"


def test_delete_after_if_join_of_confirm_is_e502():
    err = reject(
        '    if (confirm("go?")) {\n'
        '      send_email("a@b.c", "deleting");\n'
        "    }\n"
        "    return delete_file(p);")
    d = err.diagnostic
    assert (d.code, d.line, d.col) == ("E502", 8, 12)
    # shortest path avoiding the guard L1 takes the false edge straight to the join
    assert [s.note for s in d.path][-2] == "line 5: if confirm(...) -> false (L2)"


def test_nested_guard_inside_confirm_block_is_approved():
    report = approve(
        '    if (confirm("first?")) {\n'
        "      if (flag) {\n"
        '        let ok = confirm("really?");\n'
        "        if (ok) {\n"
        "          return delete_file(p);\n"
        "        }\n"
        "      }\n"
        "      return delete_file(p);\n"
        "    }\n"
        "    return false;")
    assert verdicts(report) == ["approved", "approved"]
    calls = report.tasks[0].calls
    guards = {g.label: g for g in report.tasks[0].guards}
    # the inner delete is attributed to the innermost dominating guard
    assert guards[calls[0].guarded_by].condition == "ok"
    assert guards[calls[1].guarded_by].condition == "confirm(...)"


def test_confirm_equals_true_is_not_a_guard():
    err = reject(
        '    if (confirm("go?") == true) {\n'
        "      return delete_file(p);\n"
        "    }\n"
        "    return false;")
    d = err.diagnostic
    assert d.code == "E502"  # a confirm is asked on the path, but nothing guards
    assert [s.note for s in d.path][2] == "line 5: if confirm(...) == true -> true (L1)"


def test_copy_of_confirm_value_is_a_guard():
    report = approve(
        '    let ok = confirm("go?");\n'
        "    let yes = ok;\n"
        "    if (yes) {\n"
        "      return delete_file(p);\n"
        "    }\n"
        "    return false;")
    assert verdicts(report) == ["approved"]
    (guard,) = report.tasks[0].guards
    assert (guard.condition, guard.confirm_line, guard.branch_line) == ("yes", 5, 7)


def test_two_confirms_on_two_branches_before_join_is_rejected():
    """Documented limitation: no single guard block dominates the join."""
    err = reject(
        "    if (flag) {\n"
        '      if (confirm("a?")) {\n'
        "      } else {\n"
        "        return false;\n"
        "      }\n"
        "    } else {\n"
        '      if (confirm("b?")) {\n'
        "      } else {\n"
        "        return false;\n"
        "      }\n"
        "    }\n"
        "    return delete_file(p);")
    d = err.diagnostic
    assert (d.code, d.line) == ("E502", 16)
    assert "the confirm on line 6 does not guard it" in d.message
    # every path passes a guard, so the path avoids only the first guard: the else side
    notes = [s.note for s in d.path]
    assert "line 5: if flag -> false (L2)" in notes
    assert any("if confirm(...) -> true" in n for n in notes)


def test_single_confirm_with_else_return_dominates_the_rest():
    report = approve(
        '    if (confirm("go?")) {\n'
        "    } else {\n"
        "      return false;\n"
        "    }\n"
        "    return delete_file(p);")
    assert verdicts(report) == ["approved"]


def test_delete_inside_repeat_inside_guard_is_approved():
    report = approve(
        '    if (confirm("go?")) {\n'
        "      repeat 3 {\n"
        "        delete_file(p);\n"
        "      }\n"
        "    }\n"
        "    return false;")
    assert verdicts(report) == ["approved"]


def test_guard_inside_repeat_with_delete_after_loop_is_e502():
    err = reject(
        "    repeat 2 {\n"
        '      if (confirm("go?")) {\n'
        '        send_email("a@b.c", "x");\n'
        "      }\n"
        "    }\n"
        "    return delete_file(p);")
    d = err.diagnostic
    assert (d.code, d.line, d.col) == ("E502", 10, 12)
    notes = [s.note for s in d.path]
    assert "line 5: repeat 2 -> exit (L3)" in notes
    assert notes[-1] == "delete_file(...) is irreversible and not guarded by confirm"


def test_unreachable_delete_after_return_is_ignored():
    report = approve(
        '    if (confirm("go?")) {\n'
        "      return true;\n"
        "    }\n"
        "    return false;\n"
        "    delete_file(p);")
    (call,) = report.tasks[0].calls
    assert call.verdict == "unreachable"
    assert report.violation is None


def test_no_confirm_anywhere_is_e501():
    err = reject("    return delete_file(p);")
    d = err.diagnostic
    assert (d.code, d.line, d.col) == ("E501", 5, 12)
    assert [s.note for s in d.path] == [
        "task t starts (entry)",
        "delete_file(...) is irreversible and not guarded by confirm",
    ]


def test_bare_confirm_before_delete_in_same_block_is_e502():
    err = reject(
        '    confirm("go?");\n'
        "    return delete_file(p);")
    d = err.diagnostic
    assert d.code == "E502"
    assert "the confirm on line 5" in d.message
    assert [s.note for s in d.path][1] == "line 5: confirm(...) is asked here"


def test_confirm_after_delete_does_not_count():
    err = reject(
        "    delete_file(p);\n"
        '    return confirm("done?");')
    assert err.diagnostic.code == "E501"


def test_bool_param_is_not_a_guard():
    err = reject(
        "    if (flag) {\n"
        "      return delete_file(p);\n"
        "    }\n"
        "    return false;")
    assert err.diagnostic.code == "E501"


def test_first_violation_in_layout_order_is_reported_and_all_calls_listed():
    with pytest.raises(CompileError) as info:
        approve(
            "    if (flag) {\n"
            "      delete_file(p);\n"
            "    }\n"
            "    return delete_file(p);")
    assert info.value.diagnostic.line == 6
    calls = info.value.artifact["data"]["tasks"][0]["calls"]
    assert [(c["line"], c["verdict"]) for c in calls] == [(6, "E501"), (8, "E501")]


def test_violation_in_later_task_reports_every_task():
    source = (
        "agent A {\n"
        "  permit confirm, delete_file;\n"
        "  budget calls = 5;\n"
        "  task ok(p: string) -> bool {\n"
        '    if (confirm("go?")) { return delete_file(p); }\n'
        "    return false;\n"
        "  }\n"
        "  task bad(p: string) -> bool {\n"
        "    return delete_file(p);\n"
        "  }\n"
        "}\n")
    with pytest.raises(CompileError) as info:
        analyze_approval(cfgs_of(source))
    d = info.value.diagnostic
    assert (d.code, d.line) == ("E501", 9)
    assert d.path[0].note == "task bad starts (entry)"
    names = [t["name"] for t in info.value.artifact["data"]["tasks"]]
    assert names == ["ok", "bad"]


def test_renamed_sibling_variable_uses_source_name():
    report = approve(
        "    if (flag) {\n"
        '      let ok = confirm("a?");\n'
        "      if (ok) { return delete_file(p); }\n"
        "    }\n"
        '    let ok = confirm("b?");\n'
        "    if (ok) { return delete_file(p); }\n"
        "    return false;")
    assert verdicts(report) == ["approved", "approved"]
    assert [g.condition for g in report.tasks[0].guards] == ["ok", "ok"]
    assert [g.confirm_line for g in report.tasks[0].guards] == [6, 9]


def test_confirm_values_fixed_point():
    defs = {
        "a": [ir.Call(ir.Var("a"), "confirm", [ir.Const("x")])],
        "b": [ir.Assign(ir.Var("b"), ir.Var("a"))],
        "c": [ir.Assign(ir.Var("c"), ir.Var("b"))],
        "d": [ir.Assign(ir.Var("d"), ir.Const(True))],
        "e": [ir.Call(ir.Var("e"), "confirm", [ir.Const("x")]),
              ir.Assign(ir.Var("e"), ir.Var("d"))],
        "f": [ir.BinOp(ir.Var("f"), "==", ir.Var("a"), ir.Const(True))],
    }
    assert confirm_values(defs) == {"a", "b", "c"}
