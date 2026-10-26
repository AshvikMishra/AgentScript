"""API tests with FastAPI's TestClient (brief section 7)."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

with warnings.catch_warnings():
    # Starlette suggests httpx2; the brief pins httpx, so silence the notice here only
    warnings.filterwarnings("ignore", message=".*httpx2.*")
    from fastapi.testclient import TestClient

from agentscript.api import app
from agentscript.pipeline import PHASES

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text())

client = TestClient(app)


def src(name: str) -> str:
    return (EXAMPLES / name).read_text()


# ----------------------------------------------------------------- static files


def test_index_html():
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.text == (ROOT / "web" / "index.html").read_text()
    assert "/static/app.js" in r.text and "/static/style.css" in r.text


@pytest.mark.parametrize("name,ctype", [("app.js", "javascript"), ("style.css", "text/css")])
def test_static_files(name, ctype):
    r = client.get(f"/static/{name}")
    assert r.status_code == 200
    assert ctype in r.headers["content-type"]
    assert r.text == (ROOT / "web" / name).read_text()


def test_static_missing_is_404():
    assert client.get("/static/nope.js").status_code == 404


def test_static_cannot_escape_web_dir():
    r = client.get("/static/../agentscript/api.py")
    assert r.status_code == 404 or "FastAPI" not in r.text


# --------------------------------------------------------------------- examples


def test_examples():
    r = client.get("/examples")
    assert r.status_code == 200
    data = r.json()
    assert [e["file"] for e in data] == [e["file"] for e in MANIFEST]
    for item, entry in zip(data, MANIFEST):
        assert {"file", "title", "description", "expect", "run", "source"} <= set(item)
        assert item["source"] == src(entry["file"])
        assert item["expect"] == entry["expect"]
        assert item["run"] == entry["run"]


# ---------------------------------------------------------------------- compile


def test_compile_valid():
    r = client.post("/compile", json={"source": src("valid_report.as")})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert set(d) == {"ok", "diagnostics", "warnings_count", "phases", "stats", "tasks"}
    assert list(d["phases"]) == list(PHASES)
    assert all(set(a) == {"text", "data"} for a in d["phases"].values())
    assert d["stats"] == {
        "before": {"instructions": 10, "calls": 5},
        "after": {"instructions": 10, "calls": 5},
        "rounds_before": 5,
        "rounds_after": 5,
    }
    assert d["tasks"][0]["name"] == "report"


def test_compile_data_fields_the_editor_reads():
    d = client.post("/compile", json={"source": src("optimize_demo.as")}).json()
    phases = d["phases"]
    assert isinstance(phases["tokens"]["data"], list)
    assert phases["cfg"]["data"]["tasks"][0]["mermaid"].startswith("flowchart")
    assert "tainted_lines" in phases["taint"]["data"]
    assert phases["optimized_ir"]["data"]["tasks"][0]["report"]["changes"]
    assert "rounds_before" in phases["schedule"]["data"]


def test_compile_error():
    r = client.post("/compile", json={"source": src("taint_injection.as")})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    [diag] = d["diagnostics"]
    assert (diag["code"], diag["phase"], diag["line"], diag["col"]) == ("E401", "taint", 9, 14)
    assert diag["path"][0]["line"] == 6
    assert d["phases"]["taint"] is not None
    assert d["phases"]["approval"] is None and d["phases"]["bytecode"] is None
    assert d["stats"] is None
    assert d["tasks"][0]["name"] == "report"


@pytest.mark.parametrize("entry", [e for e in MANIFEST if e["expect"]], ids=lambda e: e["file"])
def test_compile_manifest_errors(entry):
    d = client.post("/compile", json={"source": src(entry["file"])}).json()
    errors = [x for x in d["diagnostics"] if x["severity"] == "error"]
    assert len(errors) == 1
    e = entry["expect"]
    assert (errors[0]["code"], errors[0]["line"], errors[0]["col"]) == (e["code"], e["line"], e["col"])


def test_compile_warning():
    d = client.post("/compile", json={"source": src("runtime_budget.as")}).json()
    assert d["ok"] is True
    assert d["warnings_count"] == 1
    assert d["diagnostics"][0]["code"] == "W306"
    assert d["diagnostics"][0]["severity"] == "warning"


def test_compile_empty_source_is_not_500():
    r = client.post("/compile", json={"source": ""})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_compile_missing_source_is_422():
    assert client.post("/compile", json={}).status_code == 422


# -------------------------------------------------------------------------- run


def run(name: str, task: str, args, **extra):
    body = {"source": src(name), "task": task, "args": args, **extra}
    r = client.post("/run", json=body)
    assert r.status_code == 200
    return r.json()


def test_run_valid_report():
    d = run("valid_report.as", "report", {"topic": "AI safety"}, live=False, confirm=True)
    assert set(d) == {"ok", "diagnostics", "value", "calls", "calls_used", "budget", "rounds"}
    assert d["ok"] is True and d["value"] is True
    assert d["diagnostics"] == []
    assert d["calls_used"] == 5 and d["budget"] == 5 and d["rounds"] == 5
    first = d["calls"][0]
    assert first["n"] == 1 and first["tool"] == "web_search"
    assert first["args"] == ["AI safety"] and first["line"] == 6
    assert first["round"] == 1 and first["note"] is None
    assert len(first["result"]) == 3


def test_run_defaults_live_false_confirm_true():
    r = client.post("/run", json={"source": src("valid_cleanup.as"), "task": "cleanup", "args": {"path": "/tmp/x"}})
    d = r.json()
    assert d["ok"] and d["value"] is True
    assert [c["tool"] for c in d["calls"]] == ["confirm", "delete_file"]


def test_run_confirm_denied():
    d = run("valid_cleanup.as", "cleanup", {"path": "/tmp/x"}, confirm=False)
    assert d["ok"]
    assert [c["tool"] for c in d["calls"]] == ["confirm"]


def test_run_parallel_rounds():
    d = run("parallel_demo.as", "scout", {"a": "rust", "b": "go", "c": "zig"})
    assert d["ok"] and d["rounds"] == 2
    assert [c["round"] for c in d["calls"]] == [1, 1, 1, 2]


def test_run_compile_error():
    d = run("taint_injection.as", "report", {"topic": "x"})
    assert d["ok"] is False and d["value"] is None and d["calls"] == []
    assert [x["code"] for x in d["diagnostics"]] == ["E401"]


def test_run_runtime_error():
    d = run("runtime_budget.as", "poll", {"topic": "news", "times": 5})
    assert d["ok"] is False and d["value"] is None
    runtime = [x for x in d["diagnostics"] if x["phase"] == "runtime"]
    assert [(x["code"], x["line"], x["col"]) for x in runtime] == [("E601", 7, 15)]
    assert len(d["calls"]) == 3 and d["calls_used"] == 3


def test_run_index_error():
    d = run("runtime_index.as", "tenth", {"topic": "AI"})
    assert d["diagnostics"][-1]["code"] == "E603"
    assert len(d["calls"]) == 1


@pytest.mark.parametrize(
    "task,args",
    [
        ("missing_task", {"topic": "x"}),
        ("report", {}),
        ("report", {"topic": 1}),
        ("report", {"topic": "x", "other": True}),
        ("report", "not an object"),
        ("report", None),
    ],
)
def test_run_e604_bad_requests(task, args):
    d = run("valid_report.as", task, args)
    assert d["ok"] is False
    assert d["diagnostics"][-1]["code"] == "E604"
    assert d["calls"] == []


def test_run_missing_fields_is_422():
    assert client.post("/run", json={"source": "x"}).status_code == 422


def test_lone_surrogate_in_string_is_a_diagnostic_not_500():
    source = 'agent A {\n permit llm;\n budget calls = 1;\n task t() -> string {\n return "\\ud800";\n }\n}\n'
    body = json.dumps({"source": source}).replace("\\\\ud800", "\\ud800").encode()
    assert b'"\\ud800' in body
    r = client.post("/compile", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 200
    assert [d["code"] for d in r.json()["diagnostics"]] == ["E102"]
    run_body = body[:-1] + b', "task": "t", "args": {}}'
    r = client.post("/run", content=run_body, headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.json()["ok"] is False
