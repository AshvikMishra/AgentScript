"""Build docs/site/index.html: every doc in docs/ plus the examples, bundled into one static page.

Run: python docs/site/build.py      (standard library only)
The page renders Markdown in the browser (marked, Mermaid, highlight.js from a CDN) and
works opened straight from disk or from any static host such as GitHub Pages.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent
DOCS = SITE.parent
ROOT = DOCS.parent
SRC = SITE / "src"
REPO_URL = "https://github.com/AshvikMishra/AgentScript"

# (group, path relative to docs/, short navigation title or None to use the H1)
PAGES = [
    ("Start here", "README.md", "Docs index"),
    ("Start here", "how-it-works/00-overview.md", "Overview"),
    ("Start here", "how-it-works/01-language.md", "The language"),
    ("Specification", "PRD.md", "Product requirements (PRD)"),
    ("Specification", "IMPLEMENTATION_PLAN.md", "Implementation plan"),
    ("How it works", "how-it-works/02-lexer.md", "Lexer"),
    ("How it works", "how-it-works/03-parser.md", "Parser"),
    ("How it works", "how-it-works/04-semantic-analysis.md", "Semantic analysis"),
    ("How it works", "how-it-works/05-ir-and-cfg.md", "IR and CFG"),
    ("How it works", "how-it-works/06-taint-analysis.md", "Taint analysis"),
    ("How it works", "how-it-works/07-approval-analysis.md", "Approval analysis"),
    ("How it works", "how-it-works/08-optimizer.md", "Optimizer"),
    ("How it works", "how-it-works/09-codegen-and-vm.md", "Codegen and VM"),
    ("How it works", "how-it-works/10-editor-and-api.md", "Editor and API"),
    ("How it works", "how-it-works/11-parallel-scheduling.md", "Parallel scheduling"),
    ("Presentation", "presentation/demo-script.md", "Demo script"),
    ("Presentation", "presentation/viva-notes.md", "Viva notes"),
    ("Reference", "PRD-Original.md", "Original PRD (reference only)"),
]


def first_heading(md: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md, re.M)
    return m.group(1).strip() if m else fallback


def doc_id(rel: str) -> str:
    return rel.removesuffix(".md").replace("/", "--").lower()


# The landing page shows these two programs and the compiler's real output for them. The output is
# produced here by running the compiler (never typed by hand) and cached in src/landing.json so the
# site still builds on a machine where the compiler cannot run.
LANDING = {
    "red": {"file": "taint_injection.as", "cmds": [["compile"]]},
    "green": {"file": "valid_report.as",
              "cmds": [["compile"], ["run", "--task", "report", "--args", '{"topic": "AI safety"}']]},
}
LANDING_CACHE = SRC / "landing.json"


def tail_from(text: str, marker: str) -> tuple[str, bool]:
    """Keep the output from the last `marker` line on; report whether anything was cut."""
    i = text.rfind(marker)
    return (text[i:], True) if i > 0 else (text, False)


def landing() -> dict:
    out = {}
    try:
        for side, spec in LANDING.items():
            rel = "examples/" + spec["file"]
            runs = []
            for cmd in spec["cmds"]:
                argv = [sys.executable, "-m", "agentscript", cmd[0], rel, *cmd[1:]]
                proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=60)
                text = proc.stdout.rstrip("\n")
                if not text:
                    raise RuntimeError(proc.stderr.strip() or "no output")
                cut = False
                if cmd[0] == "compile":
                    text, cut = tail_from(text, "== diagnostics ==")
                shown = " ".join(a if " " not in a and "{" not in a else "'" + a + "'" for a in cmd[1:])
                runs.append({"cmd": f"python -m agentscript {cmd[0]} {rel}" + (" " + shown if shown else ""),
                             "exit": proc.returncode, "output": text, "cut": cut})
            out[side] = {"file": spec["file"], "source": (ROOT / rel).read_text(encoding="utf-8"), "runs": runs}
        LANDING_CACHE.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:  # compiler unavailable: fall back to the last real output
        print(f"note: could not run the compiler ({exc}); using {LANDING_CACHE.name}", file=sys.stderr)
        out = json.loads(LANDING_CACHE.read_text(encoding="utf-8"))
    return out


def collect() -> dict:
    pages = []
    for group, rel, title in PAGES:
        path = DOCS / rel
        if not path.exists():
            continue
        md = path.read_text(encoding="utf-8")
        pages.append({
            "id": doc_id(rel),
            "path": "docs/" + rel,
            "group": group,
            "title": first_heading(md, rel) if rel.startswith("how-it-works/") else (title or first_heading(md, rel)),
            "nav": title or first_heading(md, rel),
            "md": md,
        })
    manifest = json.loads((ROOT / "examples" / "manifest.json").read_text(encoding="utf-8"))
    examples = []
    for entry in manifest:
        src = (ROOT / "examples" / entry["file"]).read_text(encoding="utf-8")
        examples.append({**entry, "source": src})
    return {"repo": REPO_URL, "pages": pages, "examples": examples, "landing": landing()}


def build() -> Path:
    template = (SRC / "template.html").read_text(encoding="utf-8")
    css = (SRC / "style.css").read_text(encoding="utf-8")
    js = (SRC / "app.js").read_text(encoding="utf-8")
    data = json.dumps(collect(), ensure_ascii=False)
    # keep the JSON inert inside <script>: "<" only occurs inside strings, so escape it
    data = data.replace("<", "\\u003c")
    html = (template.replace("/*__CSS__*/", css)
            .replace("/*__JS__*/", js)
            .replace("__DATA__", data))
    out = SITE / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    out = build()
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
