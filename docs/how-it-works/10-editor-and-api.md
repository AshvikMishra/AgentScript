# 10. The web editor and the API

## 1. What this phase does

| | |
| --- | --- |
| Input | Source text typed or loaded in the browser; button clicks (Compile, Run); the run form (task, arguments, confirm answer, live toggle). |
| Output | Filled phase tabs, error squiggles in the code, taint highlighting, the before/after counts, and the run panel's call log and budget. |
| Place in the pipeline | Not a compiler phase: a thin layer around the whole pipeline. The browser holds no compiler logic; it sends the source to the FastAPI backend, which calls `compile_source()` / `run_source()` in `agentscript/pipeline.py`, the same functions the CLI and the tests use. |
| Requirements | The PRD's editor section, M6 gate ("a full demo run without touching the terminal"), success metric "phases implemented and visible in the editor: 6 of 6", L2 ("the editor shows the number of rounds before and after"). |

## 2. Key data structures

**API endpoints** (`agentscript/api.py`, served by `python -m agentscript serve`).

| Method and path | Request | Response |
| --- | --- | --- |
| `GET /` | – | `web/index.html` |
| `GET /static/...` | – | `web/app.js`, `web/style.css` |
| `GET /examples` | – | `[{"file", "title", "description", "expect", "run", "source"}, ...]`, read from `examples/manifest.json` plus each file's source |
| `POST /compile` | `{"source": "..."}` | `CompileResult.to_dict()`: `ok`, `diagnostics`, `warnings_count`, `phases`, `stats`, `tasks` |
| `POST /run` | `{"source", "task", "args", "live", "confirm"}` | `ok`, `diagnostics`, `value`, `calls`, `calls_used`, `budget`, `rounds` |

**The `/compile` response** (fixed in the API contract, IMPLEMENTATION_PLAN.md section 8):

| Field | Content | Used by |
| --- | --- | --- |
| `ok` | true when no error (warnings allowed) | status line |
| `diagnostics` | warnings plus at most one error, each `{phase, code, severity, message, line, col, path}` | Errors tab, squiggles, path highlighting |
| `phases` | one `{text, data}` artifact per key: `tokens, ast, symbols, ir, cfg, taint, approval, optimized_ir, schedule, bytecode`; `null` after the failing phase | one tab each |
| `stats` | `before {instructions, calls}`, `after {instructions, calls}`, `rounds_before`, `rounds_after` | Optimized IR and Rounds tabs |
| `tasks` | `[{name, params: [{name, type}], return_type}]` | run form |

**The `/run` response.** `calls` is the call log, one entry
`{n, tool, args, result, line, round, note}` per executed call. On a compile error: `ok: false`,
the compile diagnostics, `value: null`, `calls: []`. On a runtime error: `ok: false`, the runtime
diagnostic, and the calls made before it.

**Front-end state** (`web/app.js`, vanilla JavaScript): the CodeMirror instance, the list of
examples, the last compile response, the selected tab, and the run form values. Nothing is
stored on the server between requests.

**Page layout.**

```
+---------------------------------------------------------------------------------+
| AgentScript   [Example: valid_report.as v]   [Compile]  [Run]   [ ] live        |
|   title and description of the chosen example, expected outcome (e.g. E401 9:14)|
+--------------------------------------+------------------------------------------+
| code pane (CodeMirror 5)             | Tokens | AST | Symbols | Errors | IR |   |
|  - AgentScript syntax highlighting   | CFG | Taint | Approval | Optimized IR |   |
|  - red squiggle: error               | Rounds | Bytecode | Output              |
|  - yellow squiggle: warning (W306)   |------------------------------------------|
|  - orange: untrusted values / path   | selected tab's artifact                  |
|  - gutter marker with the message    |                                          |
+--------------------------------------+------------------------------------------+
```

| Tab | Shows | From |
| --- | --- | --- |
| Tokens, AST, Symbols, IR, Bytecode | the artifact's `text` in a `<pre>` | `phases.tokens`, `.ast`, `.symbols`, `.ir`, `.bytecode` |
| Errors | every diagnostic: code, phase, line:col, message, path steps; clicking one moves the cursor there | `diagnostics` |
| CFG | the control-flow graph drawn with Mermaid, from the text produced by `cfg_to_mermaid()` carried in the `cfg` artifact | `phases.cfg` |
| Taint | the taint report; on E401 the source-to-sink path as a list | `phases.taint`, the E401 `path` |
| Approval | guard blocks, approved irreversible calls; on E501/E502 the offending path | `phases.approval`, the error `path` |
| Optimized IR | the optimized IR, plus "instructions a → b, tool calls c → d" | `phases.optimized_ir`, `stats` |
| Rounds (M7) | the scheduled IR, plus "rounds a → b" | `phases.schedule`, `stats` |
| Output | the run panel: task selector, JSON arguments box, confirm answer, live toggle, the returned value, the call log table and a budget meter `calls_used / budget` | `tasks`, the `/run` response |

A tab whose phase did not run (its key is `null`) says so and names the error that stopped the
pipeline.

## 3. Algorithm

**Squiggles from diagnostics.** For each diagnostic with `line >= 1`, convert the 1-based `line`/`col` to
CodeMirror's 0-based position and mark from there to the end of the token at that position (at
least one character), using `markText` with an error or warning class and a gutter marker whose
tooltip is the message. Diagnostics carry only a start position, so the end of the mark is found
in the browser by scanning to the end of the identifier, number or string at that position. Each
step of an error's `path` gets a lighter mark, so the whole source-to-sink chain (E401) or the
offending path (E501, E502) is visible in the code.

**Taint highlighting.** On a successful compile the taint artifact's data lists the untrusted
variables with their definition positions; those spots get an orange background, so the audience
sees `raw` light up in `valid_report.as` and stop at `clean`.

**Example picker.** At page load `GET /examples` fills the drop-down from the manifest. Choosing an
example replaces the editor content with its `source`, shows its title, description and expected
outcome (`expect` code and line:col, or "valid"), and presets the run form from its `run` entry
(task and arguments). The user then presses Compile, as the PRD describes.

**Run panel.** After a compile, the task selector is filled from `tasks`, and the JSON arguments
box is pre-filled from the example's `run.args` (or, for edited code, from the selected task's
`params` with placeholder values). One JSON box keeps the page simple for every parameter type,
including `list<T>`, and matches the CLI's `--args JSON`. Run sends `/run` with the parsed
arguments, the confirm checkbox as `confirm` and the live toggle as `live`. The
call log table shows `n`, tool, arguments, result, line, round and note (live fallbacks appear in
`note`); the budget meter shows `calls_used / budget`. A runtime error is shown in the Errors tab
and squiggled like a compile error. Only diagnostics with `line >= 1` are squiggled: E604 is about
the run request, not the source, so it is reported at line 0 and appears only in the Errors tab
(IMPLEMENTATION_PLAN.md decision D13).

**A Compile click through the system.**

```mermaid
sequenceDiagram
    actor U as User
    participant B as Browser (web/app.js)
    participant A as FastAPI (agentscript/api.py)
    participant P as pipeline.compile_source
    participant Ph as Phases (lexer ... codegen)
    U->>B: click Compile
    B->>A: POST /compile {"source": ...}
    A->>P: compile_source(source)
    loop each phase in order: lexer, parser, semantic, irgen+cfg, taint, approval, optimizer, scheduler, codegen
        P->>Ph: run phase on the previous artifact
        alt phase succeeds
            Ph-->>P: result and {text, data} artifact
        else CompileError raised
            Ph-->>P: one Diagnostic
            Note over P: stop, later phases stay null
        end
    end
    P-->>A: CompileResult (never raises)
    A-->>B: CompileResult.to_dict() as JSON
    B->>B: fill tabs, mark squiggles and path steps, show counts, fill the run form
    B-->>U: updated page
```

A Run click follows the same route through `POST /run` and `run_source()`, which compiles the
source again, then calls the VM with a `MockRegistry` or `LiveRegistry`.

```
on Compile:
    res = POST /compile {source: editor.getValue()}
    clear old marks
    for d in res.diagnostics:
        if d.line >= 1: squiggle(d)
        for s in d.path or []: mark_step(s)
    for tab in tabs: tab.show(res.phases[tab.key] or "not run: " + first error)
    show_counts(res.stats); fill_run_form(res.tasks)
    if res.ok: highlight_untrusted(res.phases.taint.data)

on Run:
    res = POST /run {source, task, args, live, confirm}
    show value, res.calls as a table, res.calls_used + " / " + res.budget
    for d in res.diagnostics:
        if d.line >= 1: squiggle(d)          # E604 (line 0): Errors tab only
```

## 4. Worked example

> Filled in at M6: with `.venv/bin/python -m agentscript serve` running, load `valid_report.as` from the picker, press Compile and Run, and paste the (trimmed) `/compile` and `/run` responses plus a short description or screenshot of each filled tab.

## 5. Errors this phase catches

> Filled in at M6: paste the `/run` response for a request with a missing argument (E604) from `tests/test_api.py`, and describe how the editor shows the E401 squiggle and path for `taint_injection.as` (9:14) when served by `.venv/bin/python -m agentscript serve`.

## 6. Design decisions and limitations

**Why it works this way**

| Decision | Why |
| --- | --- |
| One static HTML page, CodeMirror 5 and Mermaid from a CDN, vanilla JS | The Step 0 answer: a working, good-looking demo with no build tooling. Nothing to install for the frontend; the page is three files. |
| FastAPI backend calling `pipeline.py` | The editor shows exactly what the CLI prints and what the tests check, because all three go through `compile_source()` / `run_source()`. There is one compiler, not a second one in JavaScript. |
| Every phase artifact is `{text, data}` | `text` is printed in the tab as is; `data` is structured JSON the page needs for squiggles, the CFG graph and taint highlighting. |
| Errors are data, not HTTP errors | `compile_source()` never raises; a compile or runtime error comes back as `ok: false` with diagnostics in a normal response, so the page has one code path. (HTTP error codes are left to FastAPI for malformed request bodies; the PRD and plan are silent; this is the simplest choice.) |
| Stateless server | Each request carries the full source; programs are tiny, so recompiling on every click is instant, and there is nothing to keep in sync. |
| Example picker from `examples/manifest.json` | The manifest is the single source of truth for the tests, the docs and the demo, so the picker always shows the expected code and position the tests assert. |
| Live toggle off by default | The demo must not depend on the network or an API key; mock results are deterministic. |

**Limitations**

| Limitation | Consequence |
| --- | --- |
| The page loads CodeMirror and Mermaid from a CDN | It needs internet access; check the demo machine beforehand. |
| Squiggle width is estimated in the browser | Diagnostics carry only a start position; the mark covers the token there. |
| No language server, no autocompletion, no incremental compile | Out of scope (the PRD lists an LSP server as a non-goal). |
| Local, single-user server with no authentication | Fine for a lab demo; not for exposing on a network. |
| `confirm` is a checkbox | The "human approval" at runtime is simulated by the run request. |

## 7. Where it lives in the code

> Filled in at M6: list `agentscript/api.py` (the FastAPI app and its routes), `agentscript/pipeline.py` (`compile_source`, `CompileResult.to_dict`, `run_source`), the `serve` command in `agentscript/__main__.py`, `web/index.html`, `web/app.js` and `web/style.css` with their main functions, and the tests in `tests/test_api.py`.
