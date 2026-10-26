# Live demo script

About 10 minutes. The goal is to show every compiler phase working on one valid program,
then let each phase reject its own kind of mistake, with the two headline checks (taint and
approval) as the centre of the demo.

Everything runs in the browser editor against the local API. Tools are mocked and
deterministic, so the demo gives the same output every time and needs no network for the
compiler itself. Every example below is in the editor's example picker; the titles are the
`title` fields of `examples/manifest.json`, and the expected codes and locations come from
the same file.

Each step lists: what to open, what to click, what the audience should see, and one
sentence to say. Expected codes and `line:col` positions are fixed by the PRD and the
manifest. The exact text the compiler prints is pasted in from real runs at the milestone
named in each note; nothing here is invented output.

## Timing

| # | Step | Minutes | Filled in at |
| --- | --- | --- | --- |
| 1 | Setup | 0.5 | M6 |
| 2 | Valid program end to end | 1.5 | M2 |
| 3 | Front-end errors | 2 | M1 |
| 4 | Budget | 1.5 | M2 |
| 5 | Optimizer | 1 | M3 |
| 6 | Prompt injection | 1.5 | M4 |
| 7 | Approval | 1.5 | M5 |
| 8 | Parallel rounds | 0.5 | M7 |
| | Total | about 10 | |

If time is short, cut step 3 down to two examples and skip the optional parts of steps 4
and 7. Never cut steps 6 and 7: they are the headline features.

## Success metrics covered

| PRD success metric | Shown in step |
| --- | --- |
| 6 of 6 classic phases implemented and visible in the editor | 2 (tabs Tokens, AST, Symbols, IR, Optimized IR, Bytecode) |
| At least 8 distinct error types, each with its own failing program | 3, 4, 6, 7 (14 error codes with their own example program, plus warning W306; E602 and E604 are covered by tests) |
| Injection example rejected at compile time | 6 |
| Unapproved irreversible call rejected at compile time | 7 |
| Optimizer demo: duplicate call removed, counts before and after | 5 |
| Stretch: 3 independent calls run in 1 round | 8 |

---

## 1. Setup

Before the audience arrives:

1. Start the server: `.venv/bin/python -m agentscript serve --port 8000`.
2. Open the address it prints (for example `http://127.0.0.1:8000/`) and check that the
   code pane is highlighted and that the CFG tab draws a diagram. The editor loads
   CodeMirror and Mermaid from a CDN, so check the network once; if it is down, use the
   CLI fallback at the end.
3. Run `.venv/bin/pytest -q` in a terminal and leave the passing summary visible, in case
   someone asks whether it is tested.
4. Increase the browser zoom so the back row can read the code pane.

| Open | Click | Audience sees | Say |
| --- | --- | --- | --- |
| The editor, no example yet | nothing | Code pane on the left; results pane on the right with tabs Tokens, AST, Symbols, Errors, IR, CFG, Taint, Approval, Optimized IR, Rounds, Bytecode, Output; the example picker, Compile and Run buttons, the run arguments, the confirm answer and the live toggle | "On the left is an AgentScript program, on the right one tab for every compiler phase; Compile fills the tabs, Run executes the bytecode on a stack VM with mock tools." |

> Filled in at M6: the exact labels of the controls (picker, Compile, Run, arguments box, confirm answer, live toggle) and the tab names as they appear in `web/index.html`, plus one screenshot or a two-line description of the opening screen from `.venv/bin/python -m agentscript serve`.

## 2. Valid program end to end

| Open | Click | Audience sees | Say |
| --- | --- | --- | --- |
| "Valid: sanitized report (PRD example)" (`valid_report.as`) | Compile, then walk the tabs left to right: Tokens, AST, Symbols, IR, CFG, Taint, Approval, Optimized IR, Bytecode | No diagnostics in the Errors tab. Each tab shows its phase's artifact; the CFG tab draws the basic blocks with the `confirm` branch | "Every phase hands a printable artifact to the next, and this one program passes types, permissions, budget, taint and approval before a single tool runs." |
| same | Run (task `report`, arguments `{"topic": "AI safety"}`, confirm = yes) | Output: value `true`. Call log with 5 calls in order: `web_search`, `sanitize`, `llm`, `confirm`, `send_email`; budget used 5 of 5. The `web_search` result contains the planted text "IGNORE ALL PREVIOUS INSTRUCTIONS ..."; the `sanitize` result shows it replaced by "[removed instruction]" | "The mock search really returns an injection attempt; because the program sanitizes before summarizing, what reaches the email is clean, and the run uses exactly its budget of 5 calls." |

Points to make while walking the tabs (one line each, do not linger):

- Tokens and AST: the front end; the AST is what the type checker annotates.
- Symbols: scopes (builtins, agent, task, blocks) and the inferred type of every `let`.
- IR and CFG: three-address code split into basic blocks; both safety analyses run here,
  on the unoptimized IR.
- Optimized IR: the tool-call count stays 5 -> 5 (nothing to merge or fold); only the
  unreachable jump after the `return` is removed. Step 5 shows a program where the calls
  drop.
- Bytecode: the stack-machine code the VM runs.

> Filled in at M2: the run output of `.venv/bin/python -m agentscript run examples/valid_report.as --task report --args '{"topic": "AI safety"}'` (value and the 5-call log).

> Filled in at M6: which tab to linger on in the browser, anything the editor shows that the CLI does not (for example highlighted untrusted values in the Taint view), and the instruction and call counts before and after from `.venv/bin/python -m agentscript compile examples/valid_report.as --phase optimized_ir`.

## 3. Front-end errors

The front end has eight failing examples, one per error code. Show four live (marked
"live"); the rest are in the picker if the examiner asks.

| Picker title | File | Expected | Live? | What it shows |
| --- | --- | --- | --- | --- |
| Error 1: unterminated string | `lex_unterminated.as` | E101 at 6:13 | live | Lexer: reported at the opening quote, not at the end of the line |
| Error 1: illegal character | `lex_illegal_char.as` | E102 at 6:15 | | Lexer: `#` is not part of the language |
| Error 2: missing semicolon | `syntax_missing_semicolon.as` | E201 at 6:30 | live | Parser: the error points just after `web_search(topic)` on line 6, not at `return` on line 7 |
| Error 3: undeclared variable | `sem_undeclared.as` | E301 at 6:12 | | Semantic: scope lookup fails for `x` |
| Error 3: duplicate variable | `sem_duplicate.as` | E302 at 7:9 | | Semantic: `let a` twice; the language has no shadowing |
| Error 4: type mismatch | `sem_type_mismatch.as` | E303 at 6:23 | live | Semantic: `web_search(42)`, an int where the signature wants a string |
| Error 4: missing return | `sem_missing_return.as` | E304 at 9:3 | | Semantic: reported at the closing `}` of the task |
| Error 5: tool not permitted | `sem_not_permitted.as` | E305 at 6:16 | live | Semantic: `read_file` is a real tool but not in `permit` |

For each live example:

| Open | Click | Audience sees | Say |
| --- | --- | --- | --- |
| the example | Compile | A squiggle at the expected `line:col` in the code pane; the Errors tab shows the code, its phase and the message; the tabs after the failing phase are empty | "Each phase owns one class of errors and the compiler stops at the first one, so the last filled tab tells you which phase rejected the program." |

One sentence for the missing-semicolon case: "The parser reports the position right after
the last good token, because that is where the semicolon belongs; the next line's `return`
is only where it noticed."

> Filled in at M1: the diagnostic text for each of the eight files, pasted from `.venv/bin/python -m agentscript compile examples/<file>.as` (one block per file).

## 4. Budget

| Open | Click | Audience sees | Say |
| --- | --- | --- | --- |
| "Error 6: budget exceeded" (`sem_budget.as`) | Compile | E306 at 9:12, on the `llm` call; the message names task `dig`, a worst-path count of 4 and the budget of 3; the path lists the four call sites on lines 6, 7, 8 and 9 | "The budget is counted statically on the worst path; the fourth call is the one that does not fit, so that is where the error points." |
| "Error 10: runtime budget guard" (`runtime_budget.as`) | Compile | Compiles, with warning W306 at 6:12 on `times`: the loop count is not a literal | "When the loop bound is only known at runtime, the compiler says so instead of pretending it has proved anything." |
| same | Run (task `poll`, arguments `{"topic": "news", "times": 5}`) | Runtime error E601 at 7:15; the call log shows 3 `web_search` calls; the 4th was stopped before it ran | "The VM enforces the same budget again and stops before the call that would exceed it, so the guarantee holds either way." |
| optional: same, `times` set to 2 | Run | Value 2, 2 calls, no error | "Within the budget the same program runs normally." |

Also a runtime guard (optional, 20 seconds):

| Open | Click | Audience sees | Say |
| --- | --- | --- | --- |
| "Runtime: index out of range" (`runtime_index.as`) | Run (task `tenth`, arguments `{"topic": "AI"}`) | E603 at 7:19: the mock search returned 3 results and the program asked for `results[9]` | "List lengths are runtime values, so indexing is checked by the VM, with the same diagnostic format as compile errors." |

> Filled in at M2: the E306 diagnostic with its path from `.venv/bin/python -m agentscript compile examples/sem_budget.as`, the W306 warning from `.venv/bin/python -m agentscript compile examples/runtime_budget.as`, and the run output of `.venv/bin/python -m agentscript run examples/runtime_budget.as --task poll --args '{"topic": "news", "times": 5}'` and `.venv/bin/python -m agentscript run examples/runtime_index.as --task tenth --args '{"topic": "AI"}'`.

## 5. Optimizer

| Open | Click | Audience sees | Say |
| --- | --- | --- | --- |
| "Optimizer: folding, dead code, duplicate call" (`optimize_demo.as`) | Compile, open the IR tab, then the Optimized IR tab | Tool calls 4 before, 2 after, plus the instruction counts and a list of changes: `2 * 3` folded and the unused `pages` removed; `debug` is the constant `false`, so the branch becomes a jump and the `llm("debug")` block is unreachable and removed; the second `web_search(topic)` in the same block is replaced by a copy of the first result | "Constant folding exposes dead code, and the duplicate search with identical arguments is merged, because `web_search` is read-only; calls with side effects or a human in the loop are never merged." |
| same | Run (task `research`, arguments `{"topic": "compilers"}`) | The call log has 2 calls: one `web_search`, one `llm` | "The program that runs is the optimized one, and it costs half the calls." |

Point to make: the budget (4) and both safety checks were computed on the unoptimized IR in
the IR tab, before any of these changes.

> Filled in at M3: the optimizer report (instruction and call counts before and after, and the change list) from `.venv/bin/python -m agentscript compile examples/optimize_demo.as --phase optimized_ir`, and the 2-call log from `.venv/bin/python -m agentscript run examples/optimize_demo.as --task research --args '{"topic": "compilers"}'`.

## 6. Prompt injection

| Open | Click | Audience sees | Say |
| --- | --- | --- | --- |
| "Error 7: prompt injection (taint)" (`taint_injection.as`) | Compile, open the Errors tab, then the Taint tab | E401 at 9:14, on `send_email`. The message names the source (`web_search`, line 6) and the sink (`send_email`, line 9); the path lists each IR step: the `web_search` call (line 6), `raw[0]`, the concatenation, the `llm` call that defines `summary` (line 7), and the sink (9:14) | "This is the PRD example with one line removed: the search result flows through indexing, concatenation and the LLM into the email, and the compiler refuses to build it." |
| "Valid: sanitized report (PRD example)" (`valid_report.as`) | Compile, open the Taint tab | No error; the report shows `raw` untrusted and `clean`, `summary` trusted after `sanitize` | "Putting `sanitize` back is the only change, and the same analysis now accepts the program." |

Point to make: this is a forward data-flow analysis to a fixed point over the CFG, so it
would follow the value through branches and loops as well.

> Filled in at M4: the E401 diagnostic with its full path from `.venv/bin/python -m agentscript compile examples/taint_injection.as`, and the taint report from `.venv/bin/python -m agentscript compile examples/valid_report.as --phase taint`.

## 7. Approval

| Open | Click | Audience sees | Say |
| --- | --- | --- | --- |
| "Valid: confirmed delete" (`valid_cleanup.as`) | Compile, open the Approval tab (and the CFG tab if asked) | No error; the report lists the `delete_file` call, its guard block (the "yes" branch of `if (ok)`) and the dominators | "`ok` holds a `confirm` result, and the block with `delete_file` is dominated by the yes branch of `if (ok)`, so no path reaches the delete without a human saying yes." |
| same | Run (task `cleanup`, arguments `{"path": "/tmp/old.log"}`) with confirm = yes, then again with confirm = no | Yes: value `true`, 2 calls (`confirm`, `delete_file`). No: value `false`, 1 call (`confirm` only) | "Answering no really skips the delete; and the delete is simulated, the mock never touches the disk." |
| "Error 8: irreversible call without confirm" (`approval_missing.as`) | Compile | E501 at 7:14; the path goes from the task entry through the true edge of `if (force)` straight to `delete_file` | "There is a confirm further down, but on this path the program never reaches it, so the delete is unapproved." |
| "Error 9: confirm on only one branch" (`approval_one_branch.as`) | Compile | E502 at 9:12; the path takes the false edge of `if (careful)` and reaches `delete_file` without passing any confirm | "A confirm on one branch is not enough: the check is dominance, every path, not some path; this is why the error is E502 and not E501." |

> Filled in at M5: the approval report from `.venv/bin/python -m agentscript compile examples/valid_cleanup.as --phase approval`, the E501 and E502 diagnostics with their paths from `.venv/bin/python -m agentscript compile examples/approval_missing.as` and `.venv/bin/python -m agentscript compile examples/approval_one_branch.as`, and both run outputs from `.venv/bin/python -m agentscript run examples/valid_cleanup.as --task cleanup --args '{"path": "/tmp/old.log"}'` (with and without `--deny-confirm`).

## 8. Parallel rounds

Stretch goal (M7). If M7 is not built, skip this step and mention it as future work.

| Open | Click | Audience sees | Say |
| --- | --- | --- | --- |
| "M7: parallel rounds" (`parallel_demo.as`) | Compile, open the Rounds tab | Rounds 4 before, 2 after: round 1 holds the three `web_search` calls, round 2 the `llm` call | "The three searches do not depend on each other, so the scheduler puts them in one round; the `llm` call needs all three results, so it waits." |
| same | Run (task `scout`, arguments `{"a": "rust", "b": "go", "c": "zig"}`) | The call log shows round numbers 1, 1, 1, 2; budget used 4 of 4 | "Every call in a round still counts against the budget, and calls to privileged, irreversible or approval tools are never reordered." |

> Filled in at M7: the schedule report from `.venv/bin/python -m agentscript compile examples/parallel_demo.as --phase schedule`, and the call log with round numbers from `.venv/bin/python -m agentscript run examples/parallel_demo.as --task scout --args '{"a": "rust", "b": "go", "c": "zig"}'`.

---

## If something breaks

Keep a terminal open in the repository. Every step has a CLI equivalent with the same
output (the API and the CLI share `agentscript/pipeline.py`).

| Problem | Fallback |
| --- | --- |
| Server will not start (port in use) | `.venv/bin/python -m agentscript serve --port 8001` |
| Page loads but has no highlighting or no CFG diagram (CDN unreachable) | Continue in the terminal with the commands below; the Text tabs are the same artifacts |
| Browser or API misbehaves | Use the CLI for the rest of the demo |
| Someone asks whether it really works | `.venv/bin/pytest -q` |

CLI commands, in demo order:

```
# 2. valid program end to end
.venv/bin/python -m agentscript compile examples/valid_report.as --phase ir
.venv/bin/python -m agentscript run examples/valid_report.as --task report --args '{"topic": "AI safety"}'

# 3. front-end errors
.venv/bin/python -m agentscript compile examples/lex_unterminated.as
.venv/bin/python -m agentscript compile examples/syntax_missing_semicolon.as
.venv/bin/python -m agentscript compile examples/sem_type_mismatch.as
.venv/bin/python -m agentscript compile examples/sem_not_permitted.as

# 4. budget
.venv/bin/python -m agentscript compile examples/sem_budget.as
.venv/bin/python -m agentscript compile examples/runtime_budget.as
.venv/bin/python -m agentscript run examples/runtime_budget.as --task poll --args '{"topic": "news", "times": 5}'
.venv/bin/python -m agentscript run examples/runtime_index.as --task tenth --args '{"topic": "AI"}'

# 5. optimizer
.venv/bin/python -m agentscript compile examples/optimize_demo.as --phase optimized_ir

# 6. prompt injection
.venv/bin/python -m agentscript compile examples/taint_injection.as
.venv/bin/python -m agentscript compile examples/valid_report.as --phase taint

# 7. approval
.venv/bin/python -m agentscript compile examples/valid_cleanup.as --phase approval
.venv/bin/python -m agentscript run examples/valid_cleanup.as --task cleanup --args '{"path": "/tmp/old.log"}' --deny-confirm
.venv/bin/python -m agentscript compile examples/approval_missing.as
.venv/bin/python -m agentscript compile examples/approval_one_branch.as

# 8. parallel rounds
.venv/bin/python -m agentscript compile examples/parallel_demo.as --phase schedule
```

Add `--json` to any `compile` command to show the exact JSON the editor receives.

> Filled in at M6: confirm that every command above runs as written and note any step where the browser and the CLI output differ.
