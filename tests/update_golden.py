"""Regenerate tests/golden/<example>.json from compile_source for every example file.

Run only after an intended output change:  .venv/bin/python tests/update_golden.py
Each file holds {"diagnostics": [...], "phases": {name: text or null}}.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
GOLDEN = Path(__file__).resolve().parent / "golden"

sys.path.insert(0, str(ROOT))

from agentscript.pipeline import PHASES, compile_source  # noqa: E402


def golden_for(source: str) -> dict:
    result = compile_source(source)
    return {
        "diagnostics": [d.to_dict() for d in result.diagnostics],
        "phases": {
            name: None if result.phases[name] is None else result.phases[name]["text"]
            for name in PHASES
        },
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def example_files() -> list[Path]:
    return sorted(EXAMPLES.glob("*.as"))


def main() -> int:
    GOLDEN.mkdir(exist_ok=True)
    for path in example_files():
        out = GOLDEN / f"{path.stem}.json"
        out.write_text(render(golden_for(path.read_text(encoding="utf-8"))), encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
