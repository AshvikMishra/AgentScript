"""End-to-end tests over examples/manifest.json plus the PRD success metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscript import pipeline
from agentscript.diagnostics import ERROR_CODES, AgentRuntimeError
from agentscript.pipeline import PHASES, CompileResult, compile_source, execute, run_source

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text())
BY_FILE = {e["file"]: e for e in MANIFEST}
RUNNABLE = [e for e in MANIFEST if e["run"]]


def source_of(name: str) -> str:
    return (EXAMPLES / name).read_text()


def compiled(name: str, parallel: bool = True) -> CompileResult:
    return compile_source(source_of(name), parallel=parallel)


def run_example(name: str, **kw) -> dict:
    entry = BY_FILE[name]
    return run_source(source_of(name), entry["run"]["task"], entry["run"]["args"], **kw)


VALID_TEMPLATE = """agent A {
  permit web_search, llm, sanitize, send_email, confirm;
  budget calls = 6;

  task t(topic: string) -> bool {
    let raw = web_search(topic);
%s
    return true;
  }
}
"""


# ------------------------------------------------------------ manifest-driven


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["file"])
def test_manifest_compile(entry):
    res = compiled(entry["file"])
    errors = [d for d in res.diagnostics if d.severity == "error"]
    expect = entry["expect"]
    if expect is None:
        assert res.ok, res.format_diagnostics()
        assert errors == []
        assert res.program is not None
        assert all(res.phases[p] is not None for p in PHASES)
    else:
        assert not res.ok
        assert len(errors) == 1
        err = errors[0]
        assert (err.code, err.phase, err.line, err.col) == (
            expect["code"],
            expect["phase"],
            expect["line"],
            expect["col"],
        )
        assert res.program is None


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["file"])
def test_manifest_warnings(entry):
    res = compiled(entry["file"])
    got = [
        {"code": d.code, "phase": d.phase, "line": d.line, "col": d.col}
        for d in res.diagnostics
        if d.severity == "warning"
    ]
    assert got == entry["warnings"]
    assert res.to_dict()["warnings_count"] == len(entry["warnings"])


@pytest.mark.parametrize("entry", RUNNABLE, ids=lambda e: e["file"])
def test_manifest_run(entry):
    resp = run_example(entry["file"])
    expect = entry["run"]["expect"]
    runtime = [d for d in resp["diagnostics"] if d["phase"] == "runtime"]
    if expect is None:
        assert resp["ok"], resp["diagnostics"]
        assert runtime == []
        assert resp["calls_used"] == len(resp["calls"]) <= resp["budget"]
    else:
        assert not resp["ok"]
        assert resp["value"] is None
        assert len(runtime) == 1
        d = runtime[0]
        assert (d["code"], d["phase"], d["line"], d["col"]) == (
            expect["code"],
            expect["phase"],
            expect["line"],
            expect["col"],
        )


@pytest.mark.parametrize("entry", MANIFEST, ids=lambda e: e["file"])
def test_failing_phase_and_later_phases_are_null(entry):
    res = compiled(entry["file"])
    if res.ok:
        return
    failing = {
        "lexer": "tokens",
        "parser": "ast",
        "semantic": "symbols",
        "taint": "taint",
        "approval": "approval",
    }[res.error.phase]
    idx = PHASES.index(failing)
    assert all(res.phases[p] is not None for p in PHASES[:idx])
    assert all(res.phases[p] is None for p in PHASES[idx + 1 :])
    # taint and approval attach their full report to the error
    assert (res.phases[failing] is not None) == (failing in ("taint", "approval"))
    assert res.stats is None


def test_compile_never_raises_on_garbage():
    for src in ["", "agent", "}}}", "agent A { budget calls = 1; }", "\x00\x01", "agent A {" * 50]:
        res = compile_source(src)
        assert not res.ok
        assert res.error is not None
        json.dumps(res.to_dict())


# ---------------------------------------------------------------- to_dict shape


def test_to_dict_shape_valid_report():
    d = compiled("valid_report.as").to_dict()
    assert set(d) == {"ok", "diagnostics", "warnings_count", "phases", "stats", "tasks"}
    assert d["ok"] is True
    assert d["diagnostics"] == []
    assert d["warnings_count"] == 0
    assert list(d["phases"]) == list(PHASES)
    for name, art in d["phases"].items():
        assert set(art) == {"text", "data"}, name
        assert isinstance(art["text"], str) and art["text"], name
    assert set(d["stats"]) == {"before", "after", "rounds_before", "rounds_after"}
    assert d["stats"]["before"] == {"instructions": 10, "calls": 5}
    assert d["tasks"] == [
        {"name": "report", "params": [{"name": "topic", "type": "string"}], "return_type": "bool"}
    ]
    json.dumps(d)  # JSON-serialisable


def test_to_dict_is_deterministic():
    for entry in MANIFEST:
        a = json.dumps(compiled(entry["file"]).to_dict(), sort_keys=True)
        b = json.dumps(compiled(entry["file"]).to_dict(), sort_keys=True)
        assert a == b, entry["file"]


def test_tasks_present_whenever_parsing_succeeded():
    assert compiled("sem_undeclared.as").tasks[0]["name"]
    assert compiled("taint_injection.as").tasks[0]["name"] == "report"
    assert compiled("syntax_missing_semicolon.as").tasks == []
    assert compiled("lex_unterminated.as").tasks == []


def test_diagnostic_dict_format():
    d = compiled("taint_injection.as").to_dict()["diagnostics"][0]
    assert set(d) == {"phase", "code", "severity", "message", "line", "col", "path"}
    assert d["severity"] == "error"
    assert all(set(s) == {"line", "col", "note"} for s in d["path"])


def test_warning_then_error_order():
    src = """agent A {
  permit web_search;
  budget calls = 1;
  task t(n: int) -> int {
    repeat n { let r = web_search("x"); }
    return missing;
  }
}
"""
    res = compile_source(src)
    # semantic errors are found in the walk before the budget check produces warnings
    assert [d.code for d in res.diagnostics] == ["E301"]


def test_tasks_with_list_param():
    src = """agent A {
  permit llm;
  budget calls = 1;
  task t(xs: list<list<string>>, n: int) -> string {
    return llm(xs[n][0]);
  }
}
"""
    res = compile_source(src)
    assert res.ok, res.format_diagnostics()
    assert res.tasks[0]["params"] == [
        {"name": "xs", "type": "list<list<string>>"},
        {"name": "n", "type": "int"},
    ]
    resp = run_source(src, "t", {"xs": [["a"], ["b"]], "n": 1})
    assert resp["ok"] and resp["value"] == "[llm] b"


# ------------------------------------------------------------- internal errors


def test_internal_error_becomes_e000(monkeypatch):
    def boom(cfg):
        raise RuntimeError("optimizer exploded")

    monkeypatch.setattr(pipeline, "optimize", boom)
    res = compile_source(source_of("valid_report.as"))
    assert not res.ok
    assert res.error.code == "E000"
    assert res.error.phase == "internal"
    assert "optimizer exploded" in res.error.message
    assert res.phases["approval"] is not None
    assert res.phases["optimized_ir"] is None and res.phases["bytecode"] is None
    assert "E000" in ERROR_CODES
    json.dumps(res.to_dict())


def test_internal_run_error_becomes_e000(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("vm exploded")

    monkeypatch.setattr(pipeline, "run", boom)
    resp = run_example("valid_report.as")
    assert not resp["ok"]
    assert resp["diagnostics"][-1]["code"] == "E000"


# ----------------------------------------------------------------- run_source


def test_run_response_shape():
    resp = run_example("valid_report.as")
    assert set(resp) == {"ok", "diagnostics", "value", "calls", "calls_used", "budget", "rounds"}
    call = resp["calls"][0]
    assert set(call) == {"n", "tool", "args", "result", "line", "round", "note"}
    assert call == {
        "n": 1,
        "tool": "web_search",
        "args": ["AI safety"],
        "result": resp["calls"][0]["result"],
        "line": 6,
        "round": 1,
        "note": None,
    }
    json.dumps(resp)


def test_run_compile_error():
    resp = run_source(source_of("taint_injection.as"), "report", {"topic": "x"})
    assert resp["ok"] is False
    assert resp["value"] is None
    assert resp["calls"] == []
    assert resp["calls_used"] == 0
    assert [d["code"] for d in resp["diagnostics"]] == ["E401"]


def test_run_lexer_error_has_zero_budget():
    resp = run_source(source_of("lex_unterminated.as"), "x", {})
    assert not resp["ok"] and resp["budget"] == 0


def test_run_runtime_error_keeps_calls_and_warning():
    resp = run_example("runtime_budget.as")
    assert [d["code"] for d in resp["diagnostics"]] == ["W306", "E601"]
    assert resp["calls_used"] == 3 == len(resp["calls"])
    assert resp["budget"] == 3
    assert resp["rounds"] == 3
    assert [c["n"] for c in resp["calls"]] == [1, 2, 3]


def test_runtime_budget_small_count_ok():
    resp = run_source(source_of("runtime_budget.as"), "poll", {"topic": "news", "times": 2})
    assert resp["ok"] and resp["value"] == 2 and resp["calls_used"] == 2


@pytest.mark.parametrize(
    "task,args,fragment",
    [
        ("nope", {"topic": "x"}, "unknown task"),
        ("report", {}, "missing"),
        ("report", {"topic": 3}, ""),
        ("report", {"topic": "x", "extra": 1}, "unexpected"),
        ("report", ["x"], ""),
    ],
)
def test_run_e604(task, args, fragment):
    resp = run_source(source_of("valid_report.as"), task, args)
    assert not resp["ok"]
    d = resp["diagnostics"][-1]
    assert d["code"] == "E604" and d["phase"] == "runtime"
    assert fragment in d["message"]
    assert resp["calls"] == [] and resp["calls_used"] == 0


def test_run_deny_confirm():
    resp = run_example("valid_report.as", confirm=False)
    assert resp["ok"] and resp["value"] is False
    assert [c["tool"] for c in resp["calls"]] == ["web_search", "sanitize", "llm", "confirm"]


def test_run_without_parallel_matches_parallel_value():
    seq = run_example("parallel_demo.as", parallel=False)
    par = run_example("parallel_demo.as")
    assert seq["value"] == par["value"]
    assert seq["rounds"] == 4 and par["rounds"] == 2


def test_execute_requires_ok_result():
    with pytest.raises(ValueError):
        execute(compiled("taint_injection.as"), "report", {"topic": "x"})


def test_execute_attaches_calls():
    with pytest.raises(AgentRuntimeError) as info:
        execute(compiled("runtime_index.as"), "tenth", {"topic": "AI"})
    assert info.value.diagnostic.code == "E603"
    assert info.value.calls_used == 1 and info.value.calls[0].tool == "web_search"


def test_live_flag_selects_live_registry():
    from agentscript.registry import LiveRegistry, MockRegistry

    assert isinstance(pipeline.make_registry(True, True), LiveRegistry)
    reg = pipeline.make_registry(False, False)
    assert isinstance(reg, MockRegistry) and reg.confirm_answer is False


# ------------------------------------------------------------ success metrics


def test_metric_valid_report_five_calls_true():
    resp = run_example("valid_report.as")
    assert resp["ok"] and resp["value"] is True
    assert resp["calls_used"] == 5 == resp["budget"]
    assert [c["tool"] for c in resp["calls"]] == [
        "web_search",
        "sanitize",
        "llm",
        "confirm",
        "send_email",
    ]
    # sanitize removed the injected instruction before it reached llm
    assert "IGNORE ALL PREVIOUS" not in resp["calls"][2]["args"][0]


def test_metric_optimize_demo_calls_4_to_2():
    res = compiled("optimize_demo.as")
    assert res.stats["before"]["calls"] == 4
    assert res.stats["after"]["calls"] == 2
    assert res.stats["before"]["instructions"] > res.stats["after"]["instructions"]
    changes = res.phases["optimized_ir"]["data"]["tasks"][0]["report"]["changes"]
    assert any("folded" in c for c in changes)
    assert any("unreachable" in c for c in changes)
    assert any("duplicate call" in c for c in changes)
    resp = run_example("optimize_demo.as")
    assert resp["ok"] and resp["calls_used"] == 2


def test_metric_optimizer_preserves_results():
    # the optimized program returns what the unoptimized semantics would
    resp = run_example("optimize_demo.as")
    assert resp["value"] == "[llm] Compare: compilers: overview article / compilers: recent news"


def test_metric_parallel_demo_rounds_4_to_2():
    res = compiled("parallel_demo.as")
    assert res.stats["rounds_before"] == 4
    assert res.stats["rounds_after"] == 2
    resp = run_example("parallel_demo.as")
    assert resp["ok"] and resp["rounds"] == 2
    round1 = [c for c in resp["calls"] if c["round"] == 1]
    assert len(round1) == 3 and {c["tool"] for c in round1} == {"web_search"}
    assert [c["args"][0] for c in round1] == ["rust", "go", "zig"]


def test_no_parallel_flag():
    res = compiled("parallel_demo.as", parallel=False)
    assert res.ok
    assert res.phases["schedule"] is None
    assert res.stats["rounds_after"] == res.stats["rounds_before"] == 4
    assert "CALL_PARALLEL" not in res.phases["bytecode"]["text"]
    assert "CALL_PARALLEL" in compiled("parallel_demo.as").phases["bytecode"]["text"]


def test_metric_taint_path_from_line_6_to_line_9():
    err = compiled("taint_injection.as").error
    assert err.code == "E401"
    assert err.path[0].line == 6
    assert err.path[-1].line == 9
    assert "web_search" in err.message and "send_email" in err.message


def test_metric_at_least_eight_error_codes_demonstrated():
    codes = set()
    for entry in MANIFEST:
        res = compiled(entry["file"])
        codes |= {d.code for d in res.diagnostics}
        if entry["run"]:
            codes |= {d["code"] for d in run_example(entry["file"])["diagnostics"]}
    errors = {c for c in codes if c.startswith("E")}
    assert len(errors) >= 8
    assert {"E101", "E102", "E201", "E301", "E302", "E303", "E304", "E305", "E306"} <= errors
    assert {"E401", "E501", "E502", "E601", "E603"} <= errors


def test_metric_six_classic_phases_have_artifacts():
    res = compiled("valid_report.as")
    for name in ("tokens", "ast", "symbols", "ir", "optimized_ir", "bytecode"):
        assert res.phases[name]["text"]


# ------------------------------------------------- safety runs before optimizing


def test_taint_checked_before_constant_folding_removes_the_sink():
    src = VALID_TEMPLATE % '    if (false) { send_email("x@example.com", raw[0]); }'
    res = compile_source(src)
    assert not res.ok
    assert res.error.code == "E401"
    assert res.phases["optimized_ir"] is None
    # the branch really is dead: with sanitize the program compiles and the call vanishes
    ok = compile_source(
        VALID_TEMPLATE % '    if (false) { send_email("x@example.com", sanitize(raw[0])); }'
    )
    assert ok.ok, ok.format_diagnostics()
    assert ok.stats["after"]["calls"] < ok.stats["before"]["calls"]


def test_approval_checked_before_constant_folding_removes_the_call():
    src = """agent A {
  permit delete_file;
  budget calls = 1;
  task t(p: string) -> bool {
    if (false) { delete_file(p); }
    return true;
  }
}
"""
    res = compile_source(src)
    assert res.error is not None and res.error.code == "E501"
    assert res.phases["taint"] is not None and res.phases["approval"] is not None


def test_budget_checked_on_unoptimized_program():
    src = """agent A {
  permit web_search;
  budget calls = 1;
  task t(q: string) -> string {
    let a = web_search(q);
    let b = web_search(q);
    return a[0];
  }
}
"""
    # the optimizer would merge the two calls into one, but the budget sees both
    assert compile_source(src).error.code == "E306"


# ------------------------------------------------------------------ robustness

TINY = "agent A {\n permit llm;\n budget calls = 1;\n task t(n: int) -> int {\n%s\n }\n}\n"


def test_deep_nesting_never_internal_error():
    for body in [
        "return " + "(" * 2000 + "1" + ")" * 2000 + ";",
        "return " + "+".join(["1"] * 3000) + ";",
        "if (true) {" * 600 + "return 1;" + "}" * 600 + "return 0;",
    ]:
        res = compile_source(TINY % body)
        assert res.error.code == "E201", res.error.format()
    assert compile_source(TINY % ("return " + "+".join(["1"] * 400) + ";")).ok


def test_compile_from_worker_threads():
    import threading

    results = []
    threads = [threading.Thread(target=lambda: results.append(compiled("parallel_demo.as").ok)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [True] * 4


def test_huge_int_literal_and_folding():
    res = compile_source(TINY % ("return " + "9" * 4301 + ";"))
    assert res.ok, res.format_diagnostics()
    body = (
        "let a = 9999999999;\nlet b = a*a*a*a*a*a*a*a*a*a;\nlet c = b*b*b*b*b*b*b*b*b*b;\n"
        "let d = c*c*c*c*c;\nreturn d;"
    )
    res = compile_source(TINY % body)
    assert res.ok, res.format_diagnostics()
    run = run_source(TINY % "let b = n*n*n*n*n*n*n*n*n*n;\nlet c = b*b*b*b*b*b*b*b*b*b;\nlet d = c*c*c*c*c;\nreturn d;",
                     "t", {"n": 9999999999})
    assert run["ok"] and run["value"] == 9999999999 ** 500
    json.dumps(run)


def test_long_straight_line_task_compiles_fast():
    import time

    body = "\n".join(f"let v{i} = {i};" for i in range(4000)) + "\nreturn v3999;"
    start = time.perf_counter()
    assert compile_source(TINY % body).ok
    assert time.perf_counter() - start < 8  # was ~4 s in the optimizer alone (quadratic _kill)


def test_call_free_loop_hits_step_limit():
    res = run_source(TINY % "repeat 999999999999 { }\nreturn 1;", "t", {"n": 1})
    assert not res["ok"]
    (err,) = [d for d in res["diagnostics"] if d["severity"] == "error"]
    assert err["code"] == "E601" and "execution step limit" in err["message"]


@pytest.mark.parametrize("task", [["t"], {"t": 1}])
def test_run_source_non_string_task_is_e604(task):
    res = run_source(TINY % "return n;", task, {"n": 1})
    assert [d["code"] for d in res["diagnostics"]] == ["E604"]


def test_scheduled_parallel_round_budget_matches_sequential():
    src = (
        "agent A { permit web_search; budget calls = 5; task t(k: int) -> int {\n"
        "  repeat k {\n"
        '    let a = web_search("x");\n'
        '    let b = web_search("y");\n'
        "  }\n"
        "  return k; } }\n"
    )
    seq = run_source(src, "t", {"k": 3}, parallel=False)
    par = run_source(src, "t", {"k": 3}, parallel=True)
    assert par["calls_used"] == seq["calls_used"] == 5
    assert par["diagnostics"][-1] == seq["diagnostics"][-1]
    assert (par["diagnostics"][-1]["line"], par["diagnostics"][-1]["code"]) == (4, "E601")
    assert [c["line"] for c in par["calls"]] == [c["line"] for c in seq["calls"]]


def test_parallel_demo_call_lines():
    res = run_example("parallel_demo.as")
    assert [(c["line"], c["round"]) for c in res["calls"]] == [(6, 1), (7, 1), (8, 1), (9, 2)]
