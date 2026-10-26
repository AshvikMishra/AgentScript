"""FastAPI app serving the web editor and the compile/run API (brief section 7).

    GET  /           web/index.html
    GET  /static/*   files under web/
    GET  /examples   examples/manifest.json entries plus each file's source
    POST /compile    {"source"} -> CompileResult.to_dict()
    POST /run        {"source", "task", "args", "live", "confirm"} -> run_source(...)

User input never causes a 500: compile and run failures are diagnostics in a 200 response.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .pipeline import compile_source, run_source

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
EXAMPLES_DIR = ROOT / "examples"


class CompileRequest(BaseModel):
    source: str


class RunRequest(BaseModel):
    source: str
    task: str
    # any JSON: a non-object reaches the VM, which answers E604 instead of a 422
    args: Any = Field(default_factory=dict)
    live: bool = False
    confirm: bool = True


def load_examples() -> list[dict]:
    """Manifest entries in manifest order, each with its `source` text added."""
    manifest = json.loads((EXAMPLES_DIR / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for entry in manifest:
        item = dict(entry)
        item.setdefault("expect", None)
        item.setdefault("run", None)
        item["source"] = (EXAMPLES_DIR / entry["file"]).read_text(encoding="utf-8")
        out.append(item)
    return out


app = FastAPI(title="AgentScript", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


@app.get("/examples")
def examples() -> list[dict]:
    return load_examples()


@app.post("/compile")
def compile_endpoint(req: CompileRequest) -> dict:
    return compile_source(req.source).to_dict()


@app.post("/run")
def run_endpoint(req: RunRequest) -> dict:
    return run_source(req.source, req.task, req.args, live=req.live, confirm=req.confirm)
