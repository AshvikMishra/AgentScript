"""Golden tests: every example's diagnostics and phase texts match tests/golden/<stem>.json.

After an intended change, regenerate with `.venv/bin/python tests/update_golden.py` and
review the diff.
"""

from __future__ import annotations

import json

import pytest

from agentscript.pipeline import PHASES
from tests.update_golden import GOLDEN, example_files, golden_for, render

FILES = example_files()


def test_every_example_has_a_golden_file():
    stems = {p.stem for p in FILES}
    goldens = {p.stem for p in GOLDEN.glob("*.json")}
    assert stems == goldens


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_golden(path):
    expected = json.loads((GOLDEN / f"{path.stem}.json").read_text(encoding="utf-8"))
    actual = golden_for(path.read_text(encoding="utf-8"))
    assert list(actual["phases"]) == list(PHASES)
    assert actual["diagnostics"] == expected["diagnostics"]
    for name in PHASES:
        assert actual["phases"][name] == expected["phases"][name], f"{path.stem}: phase {name}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_golden_file_is_canonical(path):
    # the stored file is exactly what update_golden.py would write
    text = (GOLDEN / f"{path.stem}.json").read_text(encoding="utf-8")
    assert text == render(json.loads(text))
