"""CLI tests: `python -m agentscript ...` run as a subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentscript.__main__ import build_parser, main
from agentscript.pipeline import PHASES

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agentscript", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def ex(name: str) -> str:
    return str(EXAMPLES / name)


# -------------------------------------------------------------------- compile


def test_compile_valid_prints_every_phase():
    r = cli("compile", ex("valid_report.as"))
    assert r.returncode == 0, r.stderr
    for name in PHASES:
        assert f"== {name} ==" in r.stdout
    assert "== diagnostics ==\n(none)" in r.stdout
    assert r.stdout.rstrip().endswith("compiled OK")


def test_compile_phase_symbols():
    r = cli("compile", ex("valid_report.as"), "--phase", "symbols")
    assert r.returncode == 0
    assert "==" not in r.stdout
    assert "report" in r.stdout and "web_search" in r.stdout
    assert "Permitted tools:" in r.stdout


def test_compile_phase_optimized_ir_shows_4_to_2():
    r = cli("compile", ex("optimize_demo.as"), "--phase", "optimized_ir")
    assert r.returncode == 0
    assert "tool calls 4 -> 2" in r.stdout


def test_compile_phase_schedule_shows_rounds_4_to_2():
    r = cli("compile", ex("parallel_demo.as"), "--phase", "schedule")
    assert r.returncode == 0
    assert "rounds 4 -> 2" in r.stdout


def test_compile_phase_bytecode_text():
    r = cli("compile", ex("valid_report.as"), "--phase", "bytecode")
    assert r.returncode == 0
    assert r.stdout.startswith("agent Assistant")
    assert "CALL send_email 2" in r.stdout


def test_compile_error_exit_1_and_diagnostic():
    r = cli("compile", ex("taint_injection.as"))
    assert r.returncode == 1
    assert "E401 [taint] 9:14:" in r.stdout
    assert "== taint ==" in r.stdout  # the failing analysis still shows its report
    assert "== optimized_ir ==" not in r.stdout
    assert r.stdout.rstrip().endswith("compilation failed")


def test_compile_phase_that_did_not_run():
    r = cli("compile", ex("lex_illegal_char.as"), "--phase", "ir")
    assert r.returncode == 1
    assert r.stdout == ""
    assert "phase 'ir' did not run" in r.stderr
    assert "E102 [lexer] 6:15:" in r.stderr


def test_compile_warning_exit_0():
    r = cli("compile", ex("runtime_budget.as"))
    assert r.returncode == 0
    assert "W306 [semantic] 6:12:" in r.stdout


def test_compile_json():
    r = cli("compile", ex("valid_report.as"), "--json")
    assert r.returncode == 0
    d = json.loads(r.stdout)
    assert d["ok"] is True
    assert list(d["phases"]) == list(PHASES)
    assert d["stats"]["rounds_before"] == 5


def test_compile_json_error_exit_1():
    r = cli("compile", ex("sem_budget.as"), "--json")
    assert r.returncode == 1
    d = json.loads(r.stdout)
    assert d["ok"] is False
    assert d["diagnostics"][0]["code"] == "E306"
    assert d["phases"]["ir"] is None


def test_compile_no_parallel():
    r = cli("compile", ex("parallel_demo.as"), "--json", "--no-parallel")
    d = json.loads(r.stdout)
    assert d["phases"]["schedule"] is None
    assert d["stats"]["rounds_after"] == 4


def test_compile_missing_file():
    r = cli("compile", ex("does_not_exist.as"))
    assert r.returncode == 1
    assert "cannot read" in r.stderr


def test_compile_unknown_phase_is_usage_error():
    r = cli("compile", ex("valid_report.as"), "--phase", "nope")
    assert r.returncode == 2


# ------------------------------------------------------------------------ run


def test_run_valid_report():
    r = cli("run", ex("valid_report.as"), "--task", "report", "--args", '{"topic": "AI safety"}')
    assert r.returncode == 0, r.stderr
    assert "calls: 5 of budget 5" in r.stdout
    assert r.stdout.rstrip().endswith("value: true")
    for tool in ("web_search", "sanitize", "llm", "confirm", "send_email"):
        assert tool in r.stdout


def test_run_deny_confirm():
    r = cli(
        "run", ex("valid_report.as"), "--task", "report", "--args", '{"topic": "x"}', "--deny-confirm"
    )
    assert r.returncode == 0
    assert "calls: 4 of budget 5" in r.stdout
    assert r.stdout.rstrip().endswith("value: false")


def test_run_runtime_budget_error():
    r = cli("run", ex("runtime_budget.as"), "--task", "poll", "--args", '{"topic": "n", "times": 5}')
    assert r.returncode == 1
    assert "W306" in r.stderr
    assert "calls: 3 of budget 3" in r.stdout
    assert "E601 [runtime] 7:15:" in r.stdout


def test_run_compile_error():
    r = cli("run", ex("approval_missing.as"), "--task", "purge")
    assert r.returncode == 1
    assert "E501" in r.stderr
    assert "nothing was run" in r.stderr


def test_run_bad_task_is_e604():
    r = cli("run", ex("valid_report.as"), "--task", "nope")
    assert r.returncode == 1
    assert "E604" in r.stdout


def test_run_invalid_json_args():
    r = cli("run", ex("valid_report.as"), "--task", "report", "--args", "{topic")
    assert r.returncode == 1
    assert "not valid JSON" in r.stderr


def test_run_requires_task():
    r = cli("run", ex("valid_report.as"))
    assert r.returncode == 2


# --------------------------------------------------------- in-process main()


def test_main_in_process(capsys):
    assert main(["compile", ex("valid_cleanup.as"), "--phase", "approval"]) == 0
    out = capsys.readouterr().out
    assert "approved" in out


def test_serve_parser_defaults():
    args = build_parser().parse_args(["serve"])
    assert (args.host, args.port) == ("127.0.0.1", 8000)
    args = build_parser().parse_args(["serve", "--port", "8765", "--host", "0.0.0.0"])
    assert (args.host, args.port) == ("0.0.0.0", 8765)


def test_serve_calls_uvicorn(monkeypatch):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    assert main(["serve", "--port", "9999"]) == 0
    assert seen == {"app": "agentscript.api:app", "host": "127.0.0.1", "port": 9999}


@pytest.mark.parametrize("argv", [[], ["bogus"]])
def test_usage_errors(argv):
    with pytest.raises(SystemExit) as info:
        main(argv)
    assert info.value.code == 2


def test_run_args_with_huge_int_does_not_crash():
    big = "9" * 5000
    r = cli("run", ex("runtime_budget.as"), "--task", "poll", "--args", '{"topic": "x", "times": %s}' % big)
    assert "Traceback" not in r.stderr
    assert "E601" in r.stdout


def test_run_prints_huge_int_result(tmp_path):
    prog = tmp_path / "big.as"
    prog.write_text(
        "agent A {\n permit llm;\n budget calls = 1;\n task t(n: int) -> int {\n"
        " let b = n*n*n*n*n*n*n*n*n*n;\n let c = b*b*b*b*b*b*b*b*b*b;\n let d = c*c*c*c*c;\n return d;\n }\n}\n"
    )
    r = cli("run", str(prog), "--task", "t", "--args", '{"n": 9999999999}')
    assert r.returncode == 0, r.stderr
    assert f"value: {9999999999 ** 500}" in r.stdout
