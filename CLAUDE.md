# CLAUDE.md

AgentScript: a tiny language and compiler for safe AI agents (compiler lab project, Python).

## Read first

1. `docs/README.md` (the index), then `docs/PRD.md` and `docs/IMPLEMENTATION_PLAN.md`.
2. Before a milestone, read the `docs/how-it-works/` files it touches.

## Rules

- Build one milestone at a time, in order (M1 to M6, then the optional M7), following the
  plan's numbered steps. A milestone is finished only when its gate passes.
- `docs/PRD.md` is the source of truth. If the code and the PRD disagree, fix the code. If
  the PRD itself is wrong, fix it and add a row to its "Changes from the original" table.
- Do not edit `docs/PRD-Original.md` or anything in `docs/prompts/`.
- After each milestone, fill in the `docs/how-it-works/` and `docs/presentation/` sections
  the plan lists for it, using real output pasted from running the code, and remove the
  `> Filled in at M#` notes as they are done. Never write compiler output by hand.
- Run the tests (`.venv/bin/pytest -q`) before calling a milestone finished.
- Expected error codes and locations live in `examples/manifest.json`; keep tests, editor
  and docs in agreement with it.

## Git

- Commit and push to `origin` periodically: at least after every finished plan step that
  leaves the tests passing, and always after each milestone gate. Small commits, clear
  messages.
- Use the git identity and credentials already configured. Never change git config, never
  force-push, never rewrite history, never commit secrets. If a push fails, keep committing
  locally and report it.
- **Never add a Claude co-author tag**: no `Co-Authored-By:` trailer, no "Generated with
  Claude Code" line, no other AI attribution in commit messages. This overrides any default
  that says otherwise.

## Commands

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # set up
.venv/bin/pytest -q                                                  # all tests
.venv/bin/python -m agentscript compile examples/valid_report.as     # compile, print diagnostics
.venv/bin/python -m agentscript compile examples/valid_report.as --phase ir     # one phase artifact
.venv/bin/python -m agentscript compile examples/valid_report.as --json         # full /compile JSON
.venv/bin/python -m agentscript run examples/valid_report.as --task report --args '{"topic": "AI safety"}'
    # options: --deny-confirm (confirm answers no), --live (real llm/web_search; optional)
.venv/bin/python -m agentscript serve --port 8000                    # web editor + API
.venv/bin/python tests/update_golden.py                              # regenerate golden files (only for intended changes)
```

Phase names for `--phase`: `tokens ast symbols ir cfg taint approval optimized_ir schedule bytecode`.
