# AgentScript implementation plan

This is the build plan for AgentScript. It follows `docs/PRD.md` (the corrected PRD) and the Step 0
answers. It is sized for **one developer on a tight schedule (under 2 weeks)**. Each milestone
leaves a working, demonstrable compiler and ends with a gate: a command to run, the result to
expect, and the docs that must be updated before the gate counts as passed.

Contents:

1. Documentation rule
2. Assumptions and decisions
3. Tech stack and repository layout
4. Core data structures
5. Milestones M1 to M7
6. Algorithms
7. Demo programs
8. API contract
9. Requirements traceability
10. Out of scope

---

## 1. Documentation rule

Follow this for every milestone. It is part of every gate.

| When | Do this |
| --- | --- |
| Before starting a milestone | Read `docs/PRD.md` (in particular Grammar, Semantics, Error taxonomy and the requirements the milestone covers) and the `docs/how-it-works/` files that the milestone lists under "Docs to update". |
| While building | If the code and the docs disagree, **the PRD wins**: change the code. If the PRD itself is wrong, fix `docs/PRD.md` and add a row to its "Changes from the original" table, then change the code. |
| After finishing | Fill in the listed `docs/how-it-works/` sections (worked example, errors caught, where it lives in the code) and the listed `docs/presentation/demo-script.md` and `docs/presentation/viva-notes.md` sections. Use output **pasted from a real run** of the compiler. Delete each `> Filled in at M<n>: ...` note once it is filled in. |
| Gate | The gate passes only when its command gives the expected result **and** the docs above are updated. |

Never write compiler output by hand (token dumps, IR listings, diagnostics). If real output is not
available yet, leave the placeholder in the form `> Filled in at M<n>: <what to paste, from which command>.`

---

## 2. Assumptions and decisions

### Step 0 answers

| Question | Answer used in this plan |
| --- | --- |
| Implementation language | Python 3.12 (as the PRD assumes). |
| Deadline | "Right now, ASAP" (built in this session). Interpreted as under 2 weeks for one solo developer; total effort about 49 h. |
| Team size | Solo. |
| M7 parallel scheduling | Optional final milestone: planned in full, built only after M1 to M6 pass their gates. |
| Loops | Delegated to us. Decision: add exactly one bounded loop, `repeat N { ... }`, where N is an INT literal or an `int` variable. This makes PRD error #10 (runtime budget guard) demonstrable. |
| Editor stack | Delegated to us ("functioning demo, should look good and be usable"). Decision: one static HTML page with CodeMirror 5 and Mermaid from a CDN, vanilla JavaScript, served by FastAPI. No build tooling. |

### Our own decisions (one line each)

| # | Decision |
| --- | --- |
| D1 | Tool annotations are a fixed built-in table in `agentscript/tools.py`, not syntax. Programs cannot declare tools or flags. |
| D2 | Expressions: `+` (int add, string concat), `-`, `*` (int), `< <= > >=` (int), `== !=` (same type: int, bool or string), indexing `e[i]`. No `/`, no unary minus, no `!`, `&&`, `||`. |
| D3 | Variables are immutable (`let` only, no assignment statement) and cannot shadow any visible name, including tool and task names (E302). |
| D4 | Every tool call counts 1 toward the budget, including `sanitize` and `confirm`. The budget applies per task run. |
| D5 | Static budget = worst path over the AST: sequence sums, `if` takes the larger branch, `repeat n` multiplies, `repeat x` counts the body once and warns W306. Early returns are ignored (conservative). |
| D6 | Taint: two labels, explicit flows only, one label per value (a list has one label), task parameters and literals are trusted. |
| D7 | Approval rule: an irreversible call must sit in a block dominated by the **true successor** of a `Branch` on a confirm value (`if (confirm(..))` or `let ok = confirm(..); if (ok)`). Nothing else counts. |
| D8 | E502 vs E501: E502 when some block containing a `confirm` call can reach the offending block (a block reaches itself); E501 otherwise. |
| D9 | The approval check and its dominators cover only blocks reachable from `entry`; an unreachable block can never run, and there is no path to report for it. Taint and budget still look at unreachable code (conservative). |
| D10 | A run names one task and passes arguments as a JSON object. Tasks cannot call tasks (a call to a task name is E301 "unknown tool"). |
| D11 | Runtime errors: E601 budget, E602 permission (defensive; unreachable for compiled programs), E603 index out of range, E604 invalid run request. |
| D12 | The VM checks the permission guard (E602) before the budget guard (E601), so an unpermitted call is never counted. |
| D13 | E604 is about the request, not the source: it is reported at line 0, col 0, and the editor shows it in the Errors tab without a squiggle. |
| D14 | The compiler stops at the first error of any phase (no error recovery). Warnings never stop compilation. |
| D15 | Safety analyses (permission, budget, taint, approval) run on the unoptimized program. The optimizer and scheduler run only after they pass, on a deep copy of the CFG. |
| D16 | Duplicate-call elimination only merges a call to a `mergeable` (read-only) tool with identical operands, in the same basic block, with no other call in between. Never `send_email`, `delete_file` or `confirm`. |
| D17 | Mock tools are deterministic (fixed outputs in `registry.py`), so golden tests are stable. `--live` is optional and never needed by any test or gate. |
| D18 | Live mode: `llm` uses the Anthropic Messages API via `urllib` when `ANTHROPIC_API_KEY` is set (model from `AGENTSCRIPT_LLM_MODEL`, default `claude-haiku-5-5`); `web_search` uses the DuckDuckGo instant-answer API; `read_file` reads only under `./sandbox/`; `send_email` and `delete_file` are always simulated; a failing live call falls back to the mock and adds a note. |
| D19 | `confirm` at runtime returns the run request's `confirm` answer (default `true`; CLI `--deny-confirm` makes it `false`). |
| D20 | `repeat` with a count of 0 or less runs zero times. |
| D21 | One agent per file, exactly one `budget` after the `permit` lines, at least one task. |
| D22 | Every phase artifact is `{"text": str, "data": JSON}`; a phase that did not run is `null` in the compile result. |
| D23 | The CLI and `pipeline.py` exist from M1 and grow each milestone. CLI exit codes: 0 success, 1 compile or runtime error, 2 usage error or "phase not built yet". |
| D24 | `examples/manifest.json` is the single source of truth for each example's expected code, line and column; tests, the editor's picker and the docs all read it. |
| D25 | The permission check E305 is part of the single semantic walk, so it lands in M1 (the M1 gate needs `sem_not_permitted.as`). M2 adds the permission unit tests and the VM guard E602. |
| D26 | Golden files store each phase's `text` (not `data`) plus the diagnostics, so diffs stay readable. They are regenerated with `tests/update_golden.py` and the diff is reviewed before committing. |
| D27 | The "6 of 6 phases" metric means the six classic phases: lexing, parsing, semantic analysis, IR generation, optimization, code generation. All 9 required stages (10 with M7) get an editor tab anyway. |

---

## 3. Tech stack and repository layout

**Stack:** Python 3.12, standard library, plus `fastapi`, `uvicorn` (server), `pytest` (tests) and
`httpx` (needed only by FastAPI's `TestClient`). The frontend is static files with CodeMirror 5 and
Mermaid loaded from a CDN. No database, no frontend build tooling, no LSP.

Setup once: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

```
CLAUDE.md                        rules for any agent working in this repo (read docs first, gates, commits)
requirements.txt                 fastapi, uvicorn, pytest, httpx
.gitignore                       .venv/, __pycache__/, *.pyc, .pytest_cache/, sandbox/
agentscript/
  __init__.py                    package marker and version
  __main__.py                    CLI: compile FILE [--phase NAME] [--json] | run FILE --task T [--args JSON] [--live] [--deny-confirm] | serve [--port]
  diagnostics.py                 Diagnostic, PathStep, CompileError, AgentRuntimeError, ERROR_CODES, make_error()   (given)
  typesys.py                     Type, STRING, INT, BOOL, list_of()   (given)
  tools.py                       ToolSpec and the fixed TOOLS table with safety flags   (given)
  ast_nodes.py                   AST dataclasses, ast_to_dict(), format_ast()   (given)
  ir.py                          IR operands and instructions, IRFunction, BasicBlock, CFG, helpers, printers   (given)
  bytecode.py                    Op, BInstr, BytecodeTask, BytecodeProgram, format_program()   (given)
  lexer.py                       TokenKind, Token, tokenize(source), tokens_artifact(tokens)   (M1)
  parser.py                      parse(tokens) -> Agent, recursive descent   (M1)
  semantic.py                    Symbol, Scope, BudgetInfo, SemanticResult, analyze(agent)   (M1, budget at M2)
  irgen.py                       lower(agent) -> list[IRFunction]   (M2)
  cfg.py                         build_cfg, reachable, dominators, format_cfg, cfg_to_dict, cfg_to_mermaid   (M2)
  codegen.py                     generate(agent, cfgs) -> BytecodeProgram   (M2, CALL_PARALLEL at M7)
  registry.py                    ToolRegistry, MockRegistry, LiveRegistry   (M2)
  vm.py                          RunResult, run(program, task, args, registry)   (M2, rounds at M7)
  optimizer.py                   optimize(cfg) -> (CFG, OptReport)   (M3)
  taint.py                       analyze_taint(cfgs) -> TaintReport; E401   (M4)
  approval.py                    analyze_approval(cfgs) -> ApprovalReport; E501/E502   (M5)
  scheduler.py                   schedule(cfg) -> (CFG, ScheduleReport)   (M7)
  pipeline.py                    CompileResult, compile_source(), run_source()   (M1, grows every milestone)
  api.py                         FastAPI app: GET /, /static, GET /examples, POST /compile, POST /run   (M6)
web/
  index.html                     editor page: code pane, phase tabs, run panel, example picker   (M6)
  app.js                         calls the API, fills tabs, squiggles, taint highlights, call log   (M6)
  style.css                      layout and colours   (M6)
examples/
  manifest.json                  title, description, expected error/warnings and run request per example
  *.as                           4 valid programs + 14 failing ones (table in section 7)
tests/
  __init__.py                    package marker
  test_lexer.py                  token kinds, positions, escapes, E101, E102   (M1)
  test_parser.py                 AST shapes, precedence, E201 location rule   (M1)
  test_semantic.py               scopes, types, E301 to E305 (M1); budget E306/W306 and permission cases (M2)
  test_cli.py                    `python -m agentscript` subcommands and exit codes   (M1+)
  test_pipeline.py               end to end over examples/manifest.json   (M1, grows each milestone)
  test_irgen.py                  lowering of let/if/repeat/expr statements, renaming   (M2)
  test_cfg.py                    block splitting, succs/preds, reachable, dominators   (M2)
  test_codegen.py                bytecode per IR instruction, jump patching   (M2)
  test_vm.py                     execution, E601 to E604 (E602 with hand-made bytecode)   (M2)
  test_registry.py               mock tool outputs are exact and deterministic   (M2)
  test_golden.py                 every example's phase texts equal tests/golden/<example>.json   (M2+)
  golden/<example>.json          expected phase texts and diagnostics per example   (M2+)
  update_golden.py               regenerates the golden files   (M2)
  test_optimizer.py              folding, dead code, duplicate calls, counts   (M3)
  test_taint.py                  propagation rules, E401 and its path   (M4)
  test_approval.py               guard forms, dominators, E501/E502 and paths   (M5)
  test_api.py                    /compile, /run, /examples via TestClient   (M6)
  test_scheduler.py              rounds, dependencies, barriers   (M7)
sandbox/                         (git-ignored) files that live-mode read_file may read
docs/
  README.md                      index and reading order
  PRD-Original.md                original PRD, unchanged
  PRD.md                         corrected PRD: source of truth
  IMPLEMENTATION_PLAN.md         this file
  how-it-works/00-overview.md ... 11-parallel-scheduling.md   one file per topic, filled in per milestone
  presentation/demo-script.md    the live demo, step by step
  presentation/viva-notes.md     likely questions and prepared answers
  prompts/proofread-and-plan.md  the prompt that produced the docs (do not edit)
```

---

## 4. Core data structures

The six "given" modules (`diagnostics.py`, `typesys.py`, `tools.py`, `ast_nodes.py`, `ir.py`,
`bytecode.py`) already exist and are authoritative. The tables below summarise them and define
the rest.

### 4.1 Tokens (`lexer.py`)

`Token(kind: TokenKind, text: str, value: int | str | None, line: int, col: int)`. `text` is the
raw lexeme as written (a string token keeps its quotes and escapes, so `len(text)` is its width
in columns); `value` is the int for INT and the unescaped string for STRING. Lines and columns are
1-based; a tab is one column.

| Group | Kinds (TokenKind member: lexeme) |
| --- | --- |
| Literals and names | `IDENT`, `INT` (`[0-9]+`), `STRING` (`"..."`, one line) |
| Declaration keywords | `AGENT: agent`, `PERMIT: permit`, `BUDGET: budget`, `CALLS: calls`, `TASK: task` |
| Statement keywords | `LET: let`, `IF: if`, `ELSE: else`, `REPEAT: repeat`, `RETURN: return` |
| Literal keywords | `TRUE: true`, `FALSE: false` |
| Type keywords | `STRING_T: string`, `INT_T: int`, `BOOL_T: bool`, `LIST_T: list` (the `_T` suffix keeps them apart from the literal kinds `STRING` and `INT`) |
| Brackets | `LBRACE: {`, `RBRACE: }`, `LPAREN: (`, `RPAREN: )`, `LBRACKET: [`, `RBRACKET: ]` |
| Separators | `COMMA: ,`, `SEMI: ;`, `COLON: :`, `ASSIGN: =`, `ARROW: ->` |
| Operators | `PLUS: +`, `MINUS: -`, `STAR: *`, `EQ: ==`, `NE: !=`, `LT: <`, `LE: <=`, `GT: >`, `GE: >=` |
| End | `EOF` (always the last token) |

These are the member names in `agentscript/lexer.py`, which the parser and the tests import; the
token `kind` in JSON is the member name (`Token.to_dict()` uses `kind.name`).

Rules: longest match (`->`, `==`, `!=`, `<=`, `>=` before their one-character prefixes); `>>` is
two `GT` tokens (so `list<list<string>>` works); `//` starts a comment to end of line; whitespace
is space, tab, `\r`, `\n`. String escapes `\n`, `\t`, `\"`, `\\`; a backslash before any other
character yields that character. Errors: **E101** unterminated string (newline or EOF before the
closing quote, reported at the opening quote), **E102** illegal character (anything else,
including a lone `!` or `/`, reported at that character).

Why a hand-written scanner: the token set is tiny, and doing it by hand makes line/column tracking
and the two lexical errors explicit, which is what the lab examines.

### 4.2 AST (`ast_nodes.py`, given)

Every node has `line`, `col` (1-based) pointing at its main token. Every expression also has
`type: Type | None`, filled in by semantic analysis.

| Node | Fields | Position points at |
| --- | --- | --- |
| `IntLit` | `value: int` | the literal |
| `StrLit` | `value: str` (unescaped) | the literal |
| `BoolLit` | `value: bool` | the literal |
| `Name` | `name: str` | the identifier |
| `Call` | `tool: str`, `args: list[Expr]` | the tool name |
| `Index` | `base: Expr`, `index: Expr` | the `[` |
| `Binary` | `op: str` (`+ - * == != < <= > >=`), `left: Expr`, `right: Expr` | the operator |
| `Block` | `statements: list[Stmt]`, `end_line`, `end_col` | `{` (end = `}`) |
| `Let` | `name: str`, `value: Expr`, `name_line`, `name_col` | `let` (name = the identifier, used by E302) |
| `If` | `cond: Expr`, `then_block: Block`, `else_block: Block \| None` | `if` |
| `Repeat` | `count: IntLit \| Name`, `body: Block` | `repeat` |
| `Return` | `value: Expr` | `return` |
| `ExprStmt` | `expr: Expr` | its expression |
| `NameRef` | `name: str` (a tool name inside `permit`) | the name |
| `Permit` | `tools: list[NameRef]` | `permit` |
| `Budget` | `calls: int` | `budget` |
| `Param` | `name: str`, `declared_type: Type` | the name |
| `Task` | `name: str`, `params: list[Param]`, `return_type: Type`, `body: Block` | `task` |
| `Agent` | `name: str`, `permits: list[Permit]`, `budget: Budget`, `tasks: list[Task]`; `permitted_tools()` | `agent` |

Printers: `format_ast(node)` (indented tree, the AST tab text) and `ast_to_dict(node)` (JSON).

### 4.3 Types (`typesys.py`, given)

`Type(name: "string" | "int" | "bool" | "list", elem: Type | None)`; constants `STRING`, `INT`,
`BOOL`; `list_of(T)`. Types compare by value, so `list_of(STRING) == list_of(STRING)`.

### 4.4 Symbol table (`semantic.py`)

| Structure | Fields |
| --- | --- |
| `Symbol` | `name: str`, `kind: "tool" \| "task" \| "param" \| "variable"`, `type: Type` (tools and tasks: return type), `line: int`, `col: int` (0 for tools), `scope: Scope` |
| `Scope` | `kind: "builtins" \| "agent" \| "task" \| "block"`, `name: str` (e.g. `builtins`, `Assistant`, `report`, `if@9:5`), `parent: Scope \| None`, `symbols: dict[str, Symbol]`, `children: list[Scope]` |
| `BudgetInfo` | `task: str`, `worst_path: list[tuple[str, int, int]]` (tool, line, col of each call site on the worst path), `budget: int`, `runtime_checked: bool` (a `repeat x` was seen) |
| `SemanticResult` | `root: Scope` (builtins), `budgets: dict[str, BudgetInfo]`, `warnings: list[Diagnostic]`; `artifact()` returns `{"text": scope tree + budget lines, "data": nested scopes + budgets}` |

Scope chain: builtins (7 tools) -> agent (tasks) -> task (params) -> block (task body, each
`if`/`else` block, each `repeat` body). `lookup(name)` walks outward. `define(symbol)` raises
**E302** if `lookup(name)` finds anything (no shadowing). Why no shadowing: it removes a whole class
of "which `x` is this?" questions from the taint and approval explanations, at almost no cost in a
language this small.

### 4.5 Tool table (`tools.py`, given)

| Tool | Signature | Flags |
| --- | --- | --- |
| `web_search` | `(string) -> list<string>` | untrusted_result, mergeable |
| `read_file` | `(string) -> string` | untrusted_result, mergeable |
| `llm` | `(string) -> string` | propagates_taint, mergeable |
| `send_email` | `(string, string) -> bool` | privileged |
| `delete_file` | `(string) -> bool` | privileged, irreversible |
| `sanitize` | `(string) -> string` | sanitizer, mergeable |
| `confirm` | `(string) -> bool` | approval |

`ToolSpec.barrier` = privileged or irreversible or approval (used by the M7 scheduler).

### 4.6 Three-address IR (`ir.py`, given)

Operands: `Const(value: int | str | bool)` and `Var(name: str)` (user variable, parameter, loop
counter or temp `t1, t2, ...`). Every instruction has `line`, `col` of the source construct.

| Opcode (class) | Operands | Text form | Defines | Uses |
| --- | --- | --- | --- | --- |
| `Assign` | `dst: Var`, `src: Operand` | `x = y` | dst | src |
| `BinOp` | `dst: Var`, `op: str`, `left`, `right: Operand` | `x = a + b` | dst | left, right |
| `Index` | `dst: Var`, `base`, `index: Operand` | `x = xs[i]` | dst | base, index |
| `Call` | `dst: Var`, `tool: str`, `args: list[Operand]` | `x = call tool(a, b)` | dst | args |
| `Jump` | `target: str` | `goto L1` | - | - |
| `Branch` | `cond: Operand`, `if_true: str`, `if_false: str` | `if c goto L1 else L2` | - | cond |
| `Return` | `value: Operand` | `return x` | - | value |
| `Label` | `name: str` | `L1:` (linear listing only, never inside a block) | - | - |
| `ParallelCalls` (M7) | `calls: list[Call]` | `round { x = call ...; y = call ... }` | each call's dst | all args |

Terminators: `Jump`, `Branch`, `Return`. Helpers: `defined_var`, `defined_vars`, `operands`,
`used_vars`, `format_instr`, `format_function`, `count_instructions`, `count_calls`.

### 4.7 Basic blocks and CFG (`ir.py`, built by `cfg.py`)

| Structure | Fields |
| --- | --- |
| `IRFunction` | `name`, `params: list[(name, Type)]`, `return_type`, `instrs: list[Instr]` (linear, with `Label`s) |
| `BasicBlock` | `label: str`, `instrs: list[Instr]` (no `Label`; last one is the only terminator), `succs: list[str]` (Branch: `[if_true, if_false]`), `preds: list[str]` |
| `CFG` | `name`, `params`, `return_type`, `blocks: dict[str, BasicBlock]` (insertion order = layout order), `entry = "entry"` |

One CFG per task. Splitting rules (`build_cfg`): the first block is `entry`; a new block starts at
every `Label` and after every terminator; code after a terminator with no label gets a generated
label `U1, U2, ...` (it is unreachable); a block that falls through gets an explicit `Jump`, so
every block ends with exactly one terminator.

### 4.8 Bytecode (`bytecode.py`, given)

`BInstr(op: Op, arg, arg2, line, col)`; `BytecodeTask(name, params: [(name, type text)],
return_type, code)`; `BytecodeProgram(agent, permits, budget, tasks)`. Variables live in a
per-run environment dict keyed by IR variable name.

| Op | Argument(s) | Stack effect | Net |
| --- | --- | --- | --- |
| `PUSH_CONST` | value | `[] -> [v]` | +1 |
| `LOAD` | name | `[] -> [value of name]` | +1 |
| `STORE` | name | `[v] -> []` | -1 |
| `ADD` `SUB` `MUL` | - | `[a, b] -> [a op b]` (ADD also concatenates strings) | -1 |
| `EQ` `NE` `LT` `LE` `GT` `GE` | - | `[a, b] -> [bool]` | -1 |
| `INDEX` | - | `[list, i] -> [list[i]]`, E603 if `i < 0` or `i >= len` | -1 |
| `CALL` | tool, argc | `[a1 .. an] -> [result]`; guards E602 then E601 | 1 - argc |
| `CALL_PARALLEL` (M7) | `[(tool, argc), ...]` | pops all args of all calls in order, runs them concurrently, pushes results in order | sum(1 - argc_i) |
| `JUMP` | addr | `[] -> []` | 0 |
| `JUMP_IF_FALSE` | addr | `[cond] -> []` | -1 |
| `RETURN` | - | `[v] -> []`, ends the task with v | -1 |

Why a stack machine: instruction selection from three-address code becomes one small template per
IR opcode, and the VM is a single `while` loop over a list.

### 4.9 Diagnostics (`diagnostics.py`, given)

`Diagnostic(phase, code, message, line, col, severity="error", path=None)`, `PathStep(line, col,
note)`. Phases: `lexer`, `parser`, `semantic`, `taint`, `approval`, `runtime`, plus `internal`
for `E000`. `make_error(code,
...)` returns `CompileError` (codes E1xx to E5xx) or `AgentRuntimeError` (E6xx); `W306` is built
with `make_diagnostic` and has severity `warning`.

JSON (API and editor squiggles):

```json
{"phase": "taint", "code": "E401", "severity": "error", "message": "...",
 "line": 9, "col": 14,
 "path": [{"line": 6, "col": 15, "note": "..."}, {"line": 9, "col": 14, "note": "..."}]}
```

`path` is `null` except for E306 (call sites on the worst path), E401 (source to sink) and
E501/E502 (entry to the irreversible call). Text form: `E401 [taint] 9:14: message`, then one
line per path step indented by four spaces: `line:col  note`.

Where each diagnostic points:

| Code | Location |
| --- | --- |
| E101 | the opening `"` |
| E102 | the illegal character |
| E201 | the found token; if it is on a later line than the previous token, just after the previous token (`prev.line`, `prev.col + len(prev.text)`) |
| E301 | the undeclared name, unknown tool, or unknown name inside `permit` |
| E302 | the second declaration (Let: `name_line:name_col`; Param: the name; Task: `task`; permit: the repeated name) |
| E303 | operator mismatch: the operator; argument type: that argument; argument count: the tool name; `if` condition: the condition; `repeat` count: the count; index: the `[`; return: the returned expression |
| E304 | the closing `}` of the task body |
| E305 | the tool name of the call |
| E306 | the (budget+1)-th call site on the worst path |
| W306 | the `repeat` count identifier |
| E401 | the tool name of the privileged (sink) call |
| E501, E502 | the tool name of the irreversible call |
| E601, E602 | the tool name of the call that trips the guard |
| E603 | the `[` of the index |
| E604 | 0:0 (not a source location, D13) |
| E000 | internal compiler error: the position of the IR or bytecode instruction involved, or 0:0 |

`E000` is never expected for a valid or invalid program; it means a bug in the compiler. The VM
raises it for internal faults (stack underflow, unknown opcode), and `compile_source` and
`run_source` turn any unexpected Python exception into an E000 diagnostic instead of crashing, so
the CLI and the editor always get a diagnostic back.

### 4.10 Phase artifacts (`pipeline.py`)

Every phase produces `{"text": <printable string>, "data": <JSON>}`. The compile result has one key
per phase; a key is `null` when its phase did not run.

| Key | Built at | `text` | `data` |
| --- | --- | --- | --- |
| `tokens` | M1 | one token per line: position, kind, lexeme | list of `{kind, text, value, line, col}` (`Token.to_dict()`) |
| `ast` | M1 | `format_ast(agent)` | `ast_to_dict(agent)` |
| `symbols` | M1 (budget at M2) | scope tree, then per-task budget line and warnings | nested scopes, budgets |
| `ir` | M2 | `format_function` per task | per task: list of `{text, line, col}` |
| `cfg` | M2 | `format_cfg` per task | `cfg_to_dict` per task, plus `mermaid` (from `cfg_to_mermaid`) |
| `taint` | M4 | untrusted variables with their source, sinks checked | per task: untrusted vars `{var, line, col, source}` |
| `approval` | M5 | dominator sets, guard blocks, verdict per irreversible call | same as JSON |
| `optimized_ir` | M3 | optimized listing, before/after counts, list of changes | `OptReport.to_dict()` plus blocks |
| `schedule` | M7 | rounds per block, rounds before/after | `ScheduleReport` as JSON |
| `bytecode` | M2 | `format_program(program)` | `program.to_dict()` |

The run result (Output tab) comes from `/run` (section 8).

---

## 5. Milestones

Effort is for one developer and includes tests and docs.

| Milestone | Covers | Effort |
| --- | --- | --- |
| M1 minimal pipeline | F1 to F4 (and the E305 check, D25) | 10 h |
| M2 IR and VM | F5, F6, F7, F9 | 12 h |
| M3 optimizer | F8 | 5 h |
| M4 taint tracking | T1 to T4 | 5 h |
| M5 approval-path checking | A1 to A3 | 5 h |
| M6 editor and API | editor requirements, success metrics | 8 h |
| M7 (optional) parallel scheduling | L1 to L3 | 4 h |
| **Total** | | **about 49 h** |

The CLI (`python -m agentscript`) and `pipeline.py` are created at M1 (lex, parse, semantic only)
and extended at every milestone. The pipeline order is always: lexer, parser, semantic, irgen +
CFG, taint, approval, optimizer, scheduler, codegen, VM. M4 and M5 insert their analyses
**before** the optimizer call that M3 adds.

### M1: minimal pipeline (about 10 h)

**Requirements:** F1, F2, F3, F4 (plus the compile-time half of F5, see D25).

**Files:** create `agentscript/lexer.py`, `agentscript/parser.py`, `agentscript/semantic.py`,
`agentscript/pipeline.py`, `agentscript/__main__.py`, `tests/test_lexer.py`,
`tests/test_parser.py`, `tests/test_semantic.py`, `tests/test_cli.py`, `tests/test_pipeline.py`.

**Steps**

1. In `lexer.py`, define `TokenKind` (every kind in 4.1), the `Token` dataclass and a `KEYWORDS`
   dict from lexeme to kind.
2. Write `tokenize(source)`: a loop over the source with `pos`, `line`, `col`; skip whitespace and
   `//` comments; scan IDENT (then look it up in `KEYWORDS`) and INT; match the two-character
   operators before one-character ones; raise `make_error("E102", ...)` on any other character;
   append `EOF`.
3. Write `_scan_string()`: handle the four escapes and "backslash + other char"; raise E101 at the
   opening quote on a newline or end of file.
4. Write `tokens_artifact(tokens)` returning `{"text", "data"}` (4.10).
5. In `parser.py`, write the `Parser` class with `peek()`, `advance()`, `check(kind)` and
   `expect(kind, what)`, which raises `CompileError(E201)` "expected {what}, found {token}" using
   the E201 location rule (4.9).
6. Write `parse_program()`, `parse_permit()`, `parse_budget()` (`budget calls = INT ;`),
   `parse_task()`, `parse_param()` and `parse_type()` (recursive for `list<T>`).
7. Write `parse_block()` and `parse_statement()` covering `let`, `if` with optional `else`,
   `repeat` (count must be INT or IDENT, otherwise E201), `return` and expression statements,
   raising E201 on a missing `;` or `}`.
8. Write the expression parsers `parse_expr -> parse_equality -> parse_relational -> parse_additive
   -> parse_term -> parse_postfix -> parse_primary`, each a left-associative loop; in
   `parse_primary`, an IDENT followed by `(` is a `Call`, otherwise a `Name`; set node positions as
   in 4.2. `parse(tokens)` returns the `Agent`.
9. In `semantic.py`, write `Symbol`, `Scope` (`define` raising E302 when `lookup` finds the name,
   `lookup` walking parents, `new_child(kind, name)`) and the builtins scope built from `TOOLS`.
10. Write `analyze(agent)` declarations pass: each `permit` name must be a tool (E301) and appear
    once (E302); define every task in the agent scope (E302 on duplicates); define params in a
    task scope (E302).
11. Write `check_stmt()`: `let` (check the initializer, then define the name with its inferred
    type), `if` (condition must be `bool`, else E303; a new block scope for each branch), `repeat`
    (count is an IntLit or a Name of type `int`, else E303; new block scope), `return` (type must
    equal the task's return type, else E303), expression statements.
12. Write `check_expr()`, which sets `.type` on every node: the operator table from PRD
    "Semantics"; `Index` (base `list<T>`, index `int`, result T); `Call` (unknown tool or a task
    name: E301; wrong argument count or type: E303; tool not in `agent.permitted_tools()`: E305).
13. Write `always_returns(block)` (a `return` statement, or an `if` with `else` where both blocks
    always return; `repeat` never counts) and raise E304 at the body's `end_line:end_col`.
14. Write `SemanticResult` and `artifact()` (scope tree text and JSON).
15. In `pipeline.py`, write `CompileResult` (`ok`, `diagnostics`, `phases` with all ten keys,
    `stats`, `tasks`) and `compile_source(source, parallel=True)`, which runs lexer, parser and
    semantic, catches `CompileError` into `diagnostics`, turns any other exception into an E000
    diagnostic (4.9), never raises, and leaves later phases `null`. `to_dict()` gives the section 8 shape.
16. In `__main__.py`, write the argparse CLI: `compile FILE [--phase NAME] [--json]` prints the
    diagnostics in text form first, then all phase texts (or only the `--phase` one; `--json`
    prints the JSON instead), exit 1 on an error. Diagnostics first, so the error is the first
    thing on screen and tests can match the first line;
    `run` and `serve` print "available from M2/M6" and exit 2.
17. Write the tests listed below, then update the docs.

**Tests**

| File | Cases |
| --- | --- |
| `test_lexer.py` | every keyword and operator kind; `->` vs `-`, `<=` vs `<`; `>>` gives two GT; positions on line 2 after a comment; string escapes produce the right `value`; E101 at the opening quote (also at EOF); E102 for `#`, a lone `!`, a lone `/`; last token is EOF |
| `test_parser.py` | `valid_report.as` gives an Agent with 1 permit, budget 5, 1 task with 5 statements; `1 + 2 * 3` nests `*` under `+`; `a - b - c` is left-associative; `xs[0][1]` nests Index; `if` without and with `else`; `repeat 3` and `repeat n`; `list<list<string>>` parses; E201 at 6:30 for `syntax_missing_semicolon.as`; E201 when `repeat` has no count |
| `test_semantic.py` | every `.type` set on `valid_report.as`; E301 undeclared name and call to a task name; E302 duplicate `let`, shadowing a param, a tool name, a duplicate permit; E303 for each case in the 4.9 table; E304 for `if` without `else`; no E304 for `if/else` that both return; E305 |
| `test_cli.py` | `compile examples/valid_report.as --phase symbols` exits 0 and prints the scope tree; `compile examples/sem_undeclared.as` exits 1 and the output starts with `E301 [semantic] 6:12`; `--json` output parses |
| `test_pipeline.py` | for every manifest entry whose expected code is in the done set (`E101` to `E305` at M1): the first error diagnostic has that code, phase, line and col; every valid example compiles with `ok: true`; the done set is a constant at the top of the file, extended each milestone |

**Docs to update:** `docs/how-it-works/02-lexer.md`, `03-parser.md`, `04-semantic-analysis.md`
(scopes and types parts); `demo-script.md` section "Front-end errors"; `viva-notes.md` lexer,
parser and semantic questions.

**Gate:** `.venv/bin/pytest -q tests/test_lexer.py tests/test_parser.py tests/test_semantic.py
tests/test_cli.py` all pass; `.venv/bin/python -m agentscript compile examples/valid_report.as
--phase symbols` prints the symbol table and exits 0; `.venv/bin/pytest -q tests/test_pipeline.py`
all pass with the done set `E101` to `E305`, which checks that the 8 front-end error examples
(E101, E102, E201, E301, E302, E303, E304, E305) fail with their manifest code, line and col; docs
updated.

### M2: IR and VM (about 12 h)

**Requirements:** F5 (runtime guard and tests), F6, F7, F9.

**Files:** create `agentscript/irgen.py`, `agentscript/cfg.py`, `agentscript/codegen.py`,
`agentscript/registry.py`, `agentscript/vm.py`, `tests/test_irgen.py`, `tests/test_cfg.py`,
`tests/test_codegen.py`, `tests/test_vm.py`, `tests/test_registry.py`, `tests/test_golden.py`,
`tests/update_golden.py`, `tests/golden/*.json`; change `agentscript/semantic.py` (budget),
`agentscript/pipeline.py`, `agentscript/__main__.py`, `tests/test_semantic.py`,
`tests/test_pipeline.py`, `tests/test_cli.py`.

**Steps**

1. In `semantic.py`, write `worst_path(stmts)` returning the list of call sites on the worst path
   (algorithm 6.4), emitting W306 for `repeat x`; after the walk, raise E306 at
   `path[budget]` when `len(path) > budget`, with `path` steps; store `BudgetInfo` per task and add
   it to `artifact()`.
2. In `irgen.py`, write the `Lowerer` for one task: `new_temp()` (`t1, t2, ...`), `new_label()`
   (`L1, L2, ...`), a scope stack mapping source names to IR names, and the renaming rule (a name
   already used earlier in the task becomes `name.2`, `name.3`, ...).
3. Write `lower_expr(expr, dst=None) -> Operand`: literals become `Const`, names `Var`; `Binary`,
   `Index` and `Call` lower their operands left to right and write into `dst` or a fresh temp.
4. Write `lower_stmt()` for `let`, `if`, `repeat`, `return` and expression statements, exactly as
   in the lowering rules (6.1). `lower(agent)` returns one `IRFunction` per task.
5. In `cfg.py`, write `build_cfg(fn)` (4.7 splitting rules, then fill `succs` and `preds`),
   `reachable(cfg)` (DFS from entry) and `dominators(cfg)` (algorithm 6.2).
6. Write `format_cfg(cfg)`, `cfg_to_dict(cfg)` and `cfg_to_mermaid(cfg)` (one node per block with
   its instructions, edges labelled `true`/`false` for branches).
7. In `registry.py`, write `ToolRegistry.call(tool, args)` dispatching to `_tool_<name>` methods
   and a `notes` list; `MockRegistry(confirm_answer=True)` with the exact mock behaviour from the
   PRD (web_search's three results, `"Contents of " + p`, `"[llm] " + p` cut to 120 chars,
   sanitize's case-insensitive replacement, `true` for send_email and delete_file, the confirm
   answer).
8. Write `LiveRegistry` (D18) with mock fallback and notes. It is optional: skip it if short of
   time; no test or gate depends on it.
9. In `codegen.py`, write `generate(agent, cfgs)`: lay out blocks in CFG order, emit the template
   for each IR instruction (algorithm 6.9) with label placeholders, then patch jump addresses in a
   second pass.
10. In `vm.py`, write `run(program, task, args, registry)`: validate the request (unknown task,
    missing or extra argument, wrong JSON type: E604), load args into the environment, then the
    dispatch loop: `CALL` checks permission (E602) then budget (E601) before calling the registry
    and appends a call-log entry `{n, tool, args, result, line, round, note}`; `INDEX` raises E603;
    `RETURN` ends the run. Return `RunResult(value, calls, calls_used, budget, rounds)`.
11. In `pipeline.py`, add the `ir`, `cfg` and `bytecode` phases and `stats`; write
    `run_source(source, task, args, live=False, confirm=True)` returning the `/run` dict
    (section 8).
12. In `__main__.py`, implement `run FILE --task T [--args JSON] [--live] [--deny-confirm]`: print
    one line per call and then the returned value; exit 1 on a compile or runtime error.
13. Write `tests/update_golden.py` (for each example, store `{"diagnostics": [...], "phases":
    {key: text or null}}` in `tests/golden/<stem>.json`) and `test_golden.py` (compare); generate
    the goldens and read every one before committing.
14. Write the tests below, then update the docs.

**Tests**

| File | Cases |
| --- | --- |
| `test_semantic.py` (added) | `valid_report.as` worst path = 5 call sites in source order; `if` takes the larger branch; `repeat 3` with 1 call counts 3; `repeat x` counts once and gives W306 at the identifier; E306 at 9:12 for `sem_budget.as` with a 4-step path; nested call in an argument counts; permission cases (E305 for each unpermitted tool) |
| `test_irgen.py` | `let x = call` writes into `x` with no temp; `let x = y` emits Assign; `if` without `else` branches to `Lend`; `repeat` emits counter, compare, branch and increment; expression statement result goes into a fresh temp; a name reused in sibling blocks becomes `name.2`; temps and labels restart per task |
| `test_cfg.py` | `valid_report.as` blocks and edges; code after `return` lands in a `U1` block that `reachable` excludes; a fall-through block gets an explicit Jump; every block has exactly one terminator; dominators of a diamond and of a loop |
| `test_codegen.py` | Branch to the next block omits the `JUMP`; a Jump to the next block is omitted; jump addresses point at the right instruction; stack effects of each template sum to 0 per IR instruction |
| `test_vm.py` | `valid_report.as` returns `true` with 5 calls; `--deny-confirm` returns `false` with 4 calls; E601 at 7:15 for `runtime_budget.as` with `times = 5`, after 3 logged calls; `times = 2` succeeds; `times = 0` runs zero times; E602 with a hand-made `BytecodeProgram` whose permit list omits the tool; E603 at 7:19 for `runtime_index.as`; E604 for an unknown task, a missing arg, an extra arg, `true` passed as an int |
| `test_registry.py` | each mock returns exactly the documented value; two calls with the same args give equal results; sanitize removes the injected instruction in any case |
| `test_golden.py` | every example matches its golden file |
| `test_pipeline.py` | add E306, the W306 warning, and run expectations (E601, E603, valid runs succeed) |
| `test_cli.py` | `run examples/valid_report.as --task report --args '{"topic": "AI safety"}'` exits 0 and prints `true`; `run` on `runtime_index.as` exits 1 with `E603` |

**Docs to update:** `04-semantic-analysis.md` (permission and budget parts), `05-ir-and-cfg.md`,
`09-codegen-and-vm.md`; `demo-script.md` sections "Valid program end to end" and "Budget";
`viva-notes.md` IR, CFG, VM and budget questions.

**Gate:** `.venv/bin/pytest -q` all pass; `.venv/bin/python -m agentscript run
examples/valid_report.as --task report --args '{"topic": "AI safety"}'` prints `true` and 5 calls;
`.venv/bin/python -m agentscript compile examples/sem_budget.as` prints `E306 [semantic] 9:12`
and exits 1; `.venv/bin/python -m agentscript compile examples/runtime_budget.as` prints
`W306 [semantic] 6:12` and exits 0; `.venv/bin/python -m agentscript run examples/runtime_budget.as
--task poll --args '{"topic": "news", "times": 5}'` fails with E601 at 7:15 after 3 calls and exits
1; docs updated.

### M3: optimizer (about 5 h)

**Requirements:** F8.

**Files:** create `agentscript/optimizer.py`, `tests/test_optimizer.py`; change
`agentscript/pipeline.py` (optimize after the analyses, codegen from the optimized CFG, `stats`),
`tests/golden/*.json` (regenerate), `tests/test_pipeline.py`.

**Steps**

1. Write `optimize(cfg)`: `copy.deepcopy` the input, run the four passes below in a loop until none
   changes anything, return `(new_cfg, OptReport)`. Never mutate the input.
2. Write `fold_and_propagate(block)` (algorithm 6.6, part 1): a per-block environment of known
   constants and copies; substitute operands; fold `BinOp` of two constants into `Assign`; turn a
   `Branch` on a constant into a `Jump` and update `succs`/`preds`.
3. Write `remove_unreachable(cfg)` using `cfg.reachable`, and fix the `preds` of remaining blocks.
4. Write `remove_dead_assignments(cfg)`: drop `Assign`/`BinOp` whose destination no instruction in
   the task uses; never drop `Call` or `Index`.
5. Write `merge_duplicate_calls(block)` (algorithm 6.6, part 3) with its safety restrictions.
6. Write `OptReport` (instructions and calls before and after via `count_instructions` and
   `count_calls`, plus a list of human-readable changes) and `to_dict()`.
7. In `pipeline.py`, add the `optimized_ir` phase and fill `stats.before`/`stats.after`; codegen
   now takes the optimized CFGs. Make `compile --phase optimized_ir` print the report.
8. Regenerate and review the goldens; write the tests; update the docs.

**Tests (`test_optimizer.py`)**: `2 * 3` folds to `6`; `"a" + "b"` folds to `"ab"`; `3 < 4` folds
to `true`; a constant branch becomes a Jump and the dead block disappears; an unused `pages`
assignment is removed; an unused `Call` result is kept; an unused `Index` is kept; two
`web_search(topic)` in one block merge; two `confirm("x")` never merge; two `send_email` never
merge; a call in between prevents merging; calls in different blocks do not merge; the input CFG is
unchanged after `optimize`; `optimize_demo.as` goes from 4 calls to 2; `valid_report.as` call count
is unchanged at 5; the optimized program still runs and returns the same value.

**Docs to update:** `08-optimizer.md`; `demo-script.md` section "Optimizer"; `viva-notes.md`
optimizer questions.

**Gate:** `.venv/bin/pytest -q` all pass; `.venv/bin/python -m agentscript compile
examples/optimize_demo.as --phase optimized_ir` shows calls 4 -> 2; docs updated.

### M4: taint tracking (about 5 h)

**Requirements:** T1, T2, T3, T4.

**Files:** create `agentscript/taint.py`, `tests/test_taint.py`; change `agentscript/pipeline.py`
(taint after CFG construction, before the optimizer), `tests/golden/*.json`,
`tests/test_pipeline.py`.

**Steps**

1. Write the transfer function `transfer(instr, state)` for `Assign`, `BinOp`, `Index` and `Call`
   using the tool flags (algorithm 6.3); untrusted entries carry a provenance list of `PathStep`s.
2. Write `analyze_task(cfg)`: the worklist fixed point over the blocks in layout order, with the
   union meet and deterministic provenance from the first predecessor that supplies it.
3. Write the sink check: walk blocks in layout order with the final entry states; the first
   untrusted argument of a `privileged` call raises E401 at the call, with a message naming the
   source tool and line and the sink tool and line, and `path` = provenance + the sink step.
4. Write `TaintReport` (untrusted variables per task with their source) and `artifact()`;
   `analyze_taint(cfgs)` runs every task.
5. In `pipeline.py`, add the `taint` phase on the **unoptimized** CFGs, before `optimize`.
6. Regenerate goldens, write tests, update docs.

**Tests (`test_taint.py`)**: `taint_injection.as` fails E401 at 9:14 with a path whose first step
is the `web_search` on line 6 and last step the `send_email` on line 9; `valid_report.as` passes;
`llm` of a trusted argument is trusted; `llm` of an untrusted argument is untrusted; concatenation
with an untrusted operand is untrusted; indexing an untrusted list is untrusted; an untrusted
index makes the result untrusted; `sanitize` result is trusted; `read_file` result is untrusted;
params are trusted; a value tainted on one branch is untrusted after the join; taint through a
`repeat` body reaches the fixed point; branching on an untrusted condition does not taint values
assigned inside it (no implicit flows); untrusted data passed to `confirm` is allowed (not
privileged).

**Docs to update:** `06-taint-analysis.md`; `demo-script.md` section "Prompt injection";
`viva-notes.md` taint questions and the taint limitations.

**Gate:** `.venv/bin/pytest -q` all pass; `.venv/bin/python -m agentscript compile
examples/taint_injection.as` fails with E401 at 9:14 with a path and exits 1;
`.venv/bin/python -m agentscript compile examples/valid_report.as` exits 0; docs updated.

### M5: approval-path checking (about 5 h)

**Requirements:** A1, A2, A3.

**Files:** create `agentscript/approval.py`, `tests/test_approval.py`; change
`agentscript/pipeline.py` (approval after taint, before the optimizer), `tests/golden/*.json`,
`tests/test_pipeline.py`.

**Steps**

1. Write `confirm_values(cfg)`: variables defined only by a `confirm` call or only by a copy of a
   confirm value (iterate until stable).
2. Write `guard_blocks(cfg)`: the `if_true` target of every `Branch` whose condition is a confirm
   value.
3. Write the check (algorithm 6.5): for every irreversible call in a reachable block, in layout
   order, test whether some guard block dominates the block (using `cfg.dominators`); otherwise
   choose E502 or E501 (D8).
4. Write `offending_path(cfg, target, avoid)`: BFS from entry that never enters a block in
   `avoid`, returning `PathStep`s with a note per block and branch edge, ending with the call.
5. Write `ApprovalReport` (dominator sets, guard blocks, verdict per irreversible call) and
   `artifact()`; `analyze_approval(cfgs)` runs every task.
6. In `pipeline.py`, add the `approval` phase on the unoptimized CFGs, after taint.
7. Regenerate goldens, write tests, update docs.

**Tests (`test_approval.py`)**: `valid_cleanup.as` passes (`let ok = confirm(..); if (ok)`);
`valid_report.as` passes (no irreversible call); `if (confirm(..)) { delete_file(..) }` passes;
`approval_missing.as` fails E501 at 7:14 with a path through the `force` true edge;
`approval_one_branch.as` fails E502 at 9:12; a delete in the `else` of `if (confirm(..))` fails;
`if (confirm(..) == true)` is not accepted; a bare `confirm(..);` before a delete gives E502; a
delete nested inside an inner `if` within the guard block passes; a delete inside `repeat` within
the guard passes; two confirms on two branches before a join fail (documented limitation); the
path never passes through a guard block when one avoiding all guards exists.

**Docs to update:** `07-approval-analysis.md`; `demo-script.md` section "Approval";
`viva-notes.md` dominator questions and the approval limitations.

**Gate:** `.venv/bin/pytest -q` all pass; `.venv/bin/python -m agentscript compile
examples/valid_cleanup.as` exits 0; `.venv/bin/python -m agentscript compile
examples/approval_missing.as` fails with E501 at 7:14 and exits 1; `.venv/bin/python -m agentscript
compile examples/approval_one_branch.as` fails with E502 at 9:12 and exits 1; docs updated.

### M6: editor and API (about 8 h)

**Requirements:** the PRD editor section and every success metric.

**Files:** create `agentscript/api.py`, `web/index.html`, `web/app.js`, `web/style.css`,
`tests/test_api.py`; change `agentscript/__main__.py` (`serve`).

**Steps**

1. In `api.py`, write the FastAPI app: `GET /` returns `web/index.html`, `/static` serves `web/`,
   `GET /examples` reads `examples/manifest.json` and adds each file's source, `POST /compile`
   returns `compile_source(source).to_dict()`, `POST /run` returns `run_source(...)` (section 8).
2. In `__main__.py`, implement `serve [--port]` (default 8000) with `uvicorn.run`.
3. Write `web/index.html`: toolbar (example picker, Compile, Run, task select, args JSON box, live
   toggle, deny-confirm toggle), code pane on the left, tabs on the right (Tokens, AST, Symbols,
   Errors, IR, CFG, Taint, Approval, Optimized IR, Rounds, Bytecode, Output). Load CodeMirror 5
   and Mermaid from cdnjs with exact versions.
4. In `app.js`, write the AgentScript CodeMirror simple mode (keywords, tool names, strings,
   numbers, comments).
5. Write `compile()`: POST `/compile`, put each phase's `text` in its tab, `null` phases show
   "not run (stopped at <phase>)", render the CFG tab's `mermaid` text with Mermaid, and fill the
   task select and args box from `tasks`.
6. Write the squiggles: for each diagnostic with `line >= 1`, `markText` a wavy underline from
   `col` to the end of the token and add a gutter marker with the message; list every diagnostic
   and its `path` steps in the Errors tab; clicking a step moves the cursor there.
7. Write the taint view: highlight untrusted variables from the taint artifact's `data`, and on
   E401 highlight each path step.
8. Write the approval view: list guard blocks and the verdict per irreversible call from the
   approval artifact's `data`, and on E501/E502 highlight each `path` step from entry to the call.
9. Write the optimization view: show `stats.before` and `stats.after` (instructions and calls) at
   the top of the Optimized IR tab.
10. Write `run()`: POST `/run`, show the call log table (n, round, tool, args, result, note),
    `calls_used / budget`, the returned value, or the runtime diagnostic.
11. Write the example picker from `GET /examples` (title, description, expected result) that
    loads the source and pre-fills the run request.
12. Write `style.css`: two-pane layout, readable monospace, tab bar, error colours.
13. Write the tests below, rehearse the full demo script in the browser, update the docs.

**Tests (`test_api.py`)**: `GET /` returns HTML; `GET /examples` returns every manifest entry
with its source; `POST /compile` on `valid_report.as` returns `ok: true` and all phase keys with
`text` and `data`; on `taint_injection.as` returns `ok: false`, one E401 diagnostic with a path,
and `optimized_ir: null`; `POST /run` on `valid_report.as` returns `value: true` and 5 calls; on a
compile error returns `calls: []`; on `runtime_budget.as` with `times = 5` returns E601 and the 3
calls made; an unknown task returns E604.

**Docs to update:** `10-editor-and-api.md`; `00-overview.md` (final notes or screenshots,
optional); `demo-script.md` section "Setup" and the real output of every step; `viva-notes.md`
editor and API questions.

**Gate:** `.venv/bin/pytest -q` all pass; `.venv/bin/python -m agentscript serve`, then the full
demo script runs in the browser without touching the terminal; docs updated.

### M7 (optional): parallel scheduling (about 4 h)

Start only when M1 to M6 have passed their gates.

**Requirements:** L1, L2, L3.

**Files:** create `agentscript/scheduler.py`, `tests/test_scheduler.py`; change
`agentscript/codegen.py` (`ParallelCalls` -> `CALL_PARALLEL`), `agentscript/vm.py` (concurrent
rounds, `round` in the call log), `agentscript/pipeline.py` (`schedule` phase, `rounds_before`,
`rounds_after`), `web/app.js` (Rounds tab), `tests/golden/*.json`, `tests/test_vm.py`.

**Steps**

1. Write `build_deps(instrs)` for one block: an edge i -> j (i before j) for read-after-write,
   write-after-read and write-after-write on any variable, and between two calls when either tool
   is a `barrier`.
2. Write `schedule_block(block)`: the list scheduler (algorithm 6.7), producing `ParallelCalls`
   for rounds of two or more calls.
3. Write `schedule(cfg)` (deep copy, every block) and `ScheduleReport` (rounds before = number of
   calls, rounds after = rounds emitted, rounds per block).
4. In `codegen.py`, emit `ParallelCalls` as: push all args of all calls in order,
   `CALL_PARALLEL [(tool, argc), ...]`, then `STORE` each destination in reverse order.
5. In `vm.py`, run `CALL_PARALLEL` with `concurrent.futures.ThreadPoolExecutor`: check permission
   for each call, check `calls_used + k <= budget` (E601 at the first call that would exceed),
   log the calls with the same `round` number in their original order.
6. In `pipeline.py`, add the `schedule` phase (when `parallel=True`) and the rounds stats; codegen
   takes the scheduled CFGs.
7. In `app.js`, fill the Rounds tab and show rounds before/after.
8. Regenerate goldens, write tests, update docs.

**Tests (`test_scheduler.py`)**: `parallel_demo.as` has rounds 4 -> 2 with the three
`web_search` calls in round 1; a call using the result of another call stays in a later round;
`send_email` and `confirm` are never in a round with another call; `delete_file` keeps its order;
`valid_report.as` keeps 5 rounds; the scheduled program returns the same value as the unscheduled
one; the VM log shows round numbers.

**Docs to update:** `11-parallel-scheduling.md`; `demo-script.md` section "Parallel rounds";
`viva-notes.md` scheduling questions.

**Gate:** `.venv/bin/pytest -q` all pass; `.venv/bin/python -m agentscript compile
examples/parallel_demo.as --phase schedule` shows rounds 4 -> 2; docs updated.

### Gate summary

| Milestone | Command | Expected |
| --- | --- | --- |
| M1 | `.venv/bin/pytest -q tests/test_lexer.py tests/test_parser.py tests/test_semantic.py tests/test_cli.py` | all pass |
| M1 | `.venv/bin/python -m agentscript compile examples/valid_report.as --phase symbols` | symbol table, exit 0 |
| M1 | `.venv/bin/pytest -q tests/test_pipeline.py` | all pass with done set `E101` to `E305` (the 8 front-end error examples give their manifest code, line, col) |
| M2 | `.venv/bin/pytest -q` | all pass |
| M2 | `.venv/bin/python -m agentscript run examples/valid_report.as --task report --args '{"topic": "AI safety"}'` | `true`, 5 calls |
| M2 | `.venv/bin/python -m agentscript compile examples/sem_budget.as` | `E306 [semantic] 9:12`, exit 1 |
| M2 | `.venv/bin/python -m agentscript compile examples/runtime_budget.as` | `W306 [semantic] 6:12`, exit 0 |
| M2 | `.venv/bin/python -m agentscript run examples/runtime_budget.as --task poll --args '{"topic": "news", "times": 5}'` | E601 at 7:15 after 3 calls, exit 1 |
| M3 | `.venv/bin/python -m agentscript compile examples/optimize_demo.as --phase optimized_ir` | calls 4 -> 2 |
| M4 | `.venv/bin/python -m agentscript compile examples/taint_injection.as` | E401 at 9:14 with a path, exit 1 |
| M4 | `.venv/bin/python -m agentscript compile examples/valid_report.as` | exit 0 |
| M5 | `.venv/bin/python -m agentscript compile examples/valid_cleanup.as` | exit 0 |
| M5 | `.venv/bin/python -m agentscript compile examples/approval_missing.as` | E501 at 7:14, exit 1 |
| M5 | `.venv/bin/python -m agentscript compile examples/approval_one_branch.as` | E502 at 9:12, exit 1 |
| M6 | `.venv/bin/python -m agentscript serve` | full demo in the browser, no terminal |
| M7 | `.venv/bin/python -m agentscript compile examples/parallel_demo.as --phase schedule` | rounds 4 -> 2 |

Every row also requires `.venv/bin/pytest -q` (M2 onwards) and the milestone's docs.

---

## 6. Algorithms

### 6.1 IR lowering rules (`irgen.py`)

Temps (`t1, t2, ...`) and labels (`L1, L2, ...`) are numbered per task in creation order. A user
name already used earlier in the same task (in a sibling scope) is renamed `name.2`, `name.3`, ...,
so every IR variable except loop counters has exactly one static definition. That property is what
makes the approval rule's "confirm value" and the optimizer's dead-assignment check simple.

| Source | IR |
| --- | --- |
| `let x = <call \| binop \| index>;` | the instruction writes straight into `x` (no extra temp) |
| `let x = <name \| literal>;` | `x = <operand>` (Assign) |
| `e;` (expression statement) | the call's result goes into a fresh temp |
| `return e;` | lower `e` to an operand `v`; `return v` |
| `if (c) { A }` | `if c goto Lthen else Lend`; `Lthen:` A; `goto Lend`; `Lend:` |
| `if (c) { A } else { B }` | `if c goto Lthen else Lelse`; `Lthen:` A; `goto Lend`; `Lelse:` B; `goto Lend`; `Lend:` |
| `repeat N { A }` | `tK = 0`; `tN = N`; `goto Lhead`; `Lhead:` `tC = tK < tN`; `if tC goto Lbody else Lexit`; `Lbody:` A; `tK = tK + 1`; `goto Lhead`; `Lexit:` |

Operands are lowered left to right, arguments before the call, so the IR call order equals the
source evaluation order (the budget path and the call log both rely on this). The then block always
gets its own label, so it is always its own basic block: that is the block the approval rule
inspects.

### 6.2 Dominators (iterative, `cfg.py`)

```
R = reachable(cfg)                         # DFS from entry
dom[entry] = {entry}
for b in R - {entry}: dom[b] = R
changed = true
while changed:
    changed = false
    for b in R - {entry}, in layout order:
        new = {b} ∪ ⋂ { dom[p] for p in preds(b) if p in R }
        if new != dom[b]: dom[b] = new; changed = true
return dom                                 # only reachable blocks are keys (D9)
```

Why this algorithm: the CFGs have a handful of blocks, so the simple set-based version is fast
enough and easy to explain; Lengauer-Tarjan would add complexity for no visible gain.

### 6.3 Taint fixed point with provenance (`taint.py`)

State: a map from variable to its provenance (the list of `PathStep`s from the source call). A
variable that is absent is trusted. The join of `trusted` and `untrusted` is `untrusted`.

```
label(op, S)  = S[op.name] if op is Var and op.name in S else None      # None = trusted

transfer(instr, S):                         # returns the new S
    case Assign / BinOp / Index:
        src = first untrusted operand (in operand order), if any
        if src: S[dst] = S[src] + [step(instr, "flows into dst")]
        else:   remove dst from S
    case Call with spec = TOOLS[tool]:
        if spec.untrusted_result: S[dst] = [step(instr, "untrusted result of tool")]
        elif spec.propagates_taint and some arg untrusted:
            S[dst] = S[that arg] + [step(instr, "passes through llm")]
        else: remove dst from S              # sanitizer and the bool-returning tools: trusted
    others: no change

IN[b] = {} and OUT[b] = {} for all b  (params trusted)
repeat:
    changed = false
    for b in blocks in layout order:
        IN[b] = merge(OUT[p] for p in preds(b))     # union of keys; provenance from the
                                                    # first predecessor (preds order) that has it
        OUT[b] = fold transfer over b.instrs starting from IN[b]
        if the key set of OUT[b] changed: changed = true
until not changed

sink check (layout order, using IN[b] and transfer step by step):
    for Call c with TOOLS[c.tool].privileged:
        for arg in c.args: if label(arg) untrusted:
            raise E401 at c; path = S[arg] + [step(c, "reaches privileged tool")]
```

Termination: the set of untrusted variables per block only grows, and it is bounded by the number
of variables. No implicit flows: `Branch` conditions never taint anything (D6).

### 6.4 Worst-path budget count (`semantic.py`)

Works on the AST, before IR, because budget is a semantic-analysis check (PRD phase table).

```
calls(expr):                                  # call sites in evaluation order
    Call:   concat(calls(a) for a in args) + [(tool, line, col)]
    Binary: calls(left) + calls(right)
    Index:  calls(base) + calls(index)
    other:  []

worst(stmts):
    path = []
    for s in stmts:
        Let / Return / ExprStmt: path += calls(s's expression)
        If:     t = worst(then); e = worst(else) or []
                path += calls(cond) + (t if len(t) >= len(e) else e)
        Repeat INT n: path += worst(body) * max(n, 0)
        Repeat Name x: path += worst(body); warn W306 at x
    return path

per task: p = worst(body.statements)
    if len(p) > budget: raise E306 at p[budget]   # the (budget+1)-th call
                        message: task name, len(p), budget; path = p
```

Early returns are ignored, so the count is an upper bound (conservative). For `repeat x` the VM
enforces the budget (E601). Check on `valid_report.as`: web_search, sanitize, llm, confirm (the
`if` condition), send_email (then branch) = 5, equal to the budget, so it passes.

### 6.5 Approval check (`approval.py`)

```
CV = {v | the only definitions of v are Call confirm, or Assign v = w with w in CV}   # iterate
G  = [b.if_true for b in blocks (layout order) if b.terminator is Branch(cond=Var v), v in CV]
dom = dominators(cfg); R = reachable(cfg)
C  = {blocks containing a Call to confirm}

for b in blocks in layout order, b in R:
    for Call c in b with TOOLS[c.tool].irreversible:
        if any(g in dom[b] for g in G): continue                 # guarded
        code = E502 if any(b in reach_from(k) for k in C) else E501   # k reaches itself
        p = bfs_path(entry, b, avoid=set(G))
        if p is None: p = bfs_path(entry, b, avoid={G[0]})       # exists: G[0] does not dominate b
        raise code at c; path = steps(p) + [step(c, "irreversible call")]

bfs_path(start, target, avoid):
    standard BFS over succs (in succs order, so the path is deterministic), never entering
    a block in avoid; returns the block list or None.
steps(p): one PathStep per block on the path, at its first instruction, with a note naming the
    edge taken (for example which side of which `if` condition).
```

Why the true successor and not the `confirm` call: `confirm` can return `false`. Dominance by the
call only proves the question was asked; dominance by the true edge proves the human said yes.

### 6.6 Optimizations (`optimizer.py`)

Driver: `cfg = deepcopy(input)`; repeat the four passes until none reports a change.

**Part 1: constant folding, local propagation, branch folding (per block)**

```
env = {}                                     # var -> Const or Var, valid inside this block only
for instr in block.instrs:
    replace each Var operand v by env[v] if v in env
    if BinOp with two Const operands: instr = Assign(dst, Const(eval(op, l, r)))
    if Branch with Const cond: instr = Jump(if_true if cond else if_false); fix succs/preds
    if instr defines d: drop every env entry whose key or value is d
    if Assign(dst, src): env[dst] = src
```

Only within a block, because a block can be entered from several predecessors; cross-block
propagation would need a full data-flow pass for little gain in these programs.

**Part 2: unreachable blocks and dead assignments**

```
remove every block not in reachable(cfg); drop it from the preds of the rest
used = {all used_vars(i) for every instruction in the task}
remove Assign / BinOp whose dst not in used          # never Call (side effects, budget)
                                                     # never Index (may raise E603)
```

**Part 3: duplicate tool-call elimination (per block)**

```
prev = None
for i, instr in enumerate(block.instrs):
    if instr is Call:
        if prev and prev.tool == instr.tool and TOOLS[instr.tool].mergeable
           and prev.args == instr.args
           and no instruction between them redefines prev.dst or a Var in prev.args:
            block.instrs[i] = Assign(instr.dst, prev.dst)       # prev stays the reference call
        else:
            prev = instr
```

Safety restrictions: only `mergeable` (read-only) tools, so `send_email`, `delete_file` and
`confirm` are never merged; same block and no other call in between, so no side effect can change
the answer between the two calls. Merging only lowers the runtime call count, so the static budget
proven before optimization still holds.

Report: instruction count (non-label) and call count before and after, and a list of changes.

### 6.7 List scheduler (M7, `scheduler.py`)

```
for each block:
    body = block.instrs[:-1]; term = block.instrs[-1]
    deps = build_deps(body)              # RAW, WAR, WAW; call-call edge if either is a barrier
    out = []; done = set()
    while len(done) < len(body):
        loop: emit every ready non-call (deps all done) in original order, until none is ready
        ready_calls = ready calls in original order
        if len(ready_calls) >= 2: out.append(ParallelCalls(ready_calls))
        elif ready_calls:       out.append(ready_calls[0])
        mark them done
    out.append(term)
rounds_before = count_calls; rounds_after = number of call rounds emitted
```

Barrier tools (`privileged`, `irreversible`, `approval`) keep their order relative to every other
call (L3), and data dependencies always hold, so the visible order of side effects never changes.

### 6.8 VM loop (`vm.py`)

```
validate(task, args)                       # E604
env = dict(args); stack = []; pc = 0; calls_used = 0
while true:
    ins = code[pc]; pc += 1
    PUSH_CONST/LOAD/STORE/arith/compare: as in 4.8
    INDEX: i = pop; xs = pop; if not 0 <= i < len(xs): E603 at ins; push xs[i]
    CALL:  if tool not in permits: E602;  if calls_used + 1 > budget: E601
           args = pop argc values; result = registry.call(tool, args); calls_used += 1; log; push
    JUMP a: pc = a;   JUMP_IF_FALSE a: if not pop: pc = a
    RETURN: return RunResult(pop, log, calls_used, budget, rounds)
```

### 6.9 Code generation templates (`codegen.py`)

| IR | Bytecode |
| --- | --- |
| `x = y` | push y; `STORE x` |
| `x = a op b` | push a; push b; `ADD`/`SUB`/... (from `BINARY_OPS`); `STORE x` |
| `x = xs[i]` | push xs; push i; `INDEX`; `STORE x` |
| `x = call t(a1..an)` | push a1 .. an; `CALL t n`; `STORE x` |
| `goto L` | `JUMP addr(L)`, omitted when L is the next block |
| `if c goto T else F` | push c; `JUMP_IF_FALSE addr(F)`; `JUMP addr(T)`, the JUMP omitted when T is the next block |
| `return v` | push v; `RETURN` |
| `round {...}` (M7) | push all args in order; `CALL_PARALLEL [(t, n), ...]`; `STORE` each dst in reverse order |

"push" is `PUSH_CONST v` for a `Const` and `LOAD name` for a `Var`. Every `BInstr` copies the IR
instruction's `line`/`col`, so runtime errors point at source.

---

## 7. Demo programs

The files already exist under `examples/`, and `examples/manifest.json` records each one's
expected result. They are not copied here, so there is one source of truth. Line:col values below
are from the manifest.

| File | Purpose | Expected result (code, line:col) | Run args |
| --- | --- | --- | --- |
| `valid_report.as` | The PRD example: search, sanitize, summarize, confirm, email; exactly 5 calls | compiles | `report`, `{"topic": "AI safety"}`, returns `true` |
| `valid_cleanup.as` | `delete_file` guarded by `let ok = confirm(..); if (ok)` | compiles | `cleanup`, `{"path": "/tmp/old.log"}` |
| `optimize_demo.as` | Folding removes the debug branch, duplicate `web_search` merged: 4 calls -> 2 | compiles | `research`, `{"topic": "compilers"}` |
| `parallel_demo.as` | M7: three independent searches in one round: 4 rounds -> 2 | compiles | `scout`, `{"a": "rust", "b": "go", "c": "zig"}` |
| `lex_unterminated.as` | Error 1: string never closes | E101 lexer 6:13 | - |
| `lex_illegal_char.as` | Error 1: `#` is not in the language | E102 lexer 6:15 | - |
| `syntax_missing_semicolon.as` | Error 2: `let` without `;` | E201 parser 6:30 | - |
| `sem_undeclared.as` | Error 3: `return x;` with no `x` | E301 semantic 6:12 | - |
| `sem_duplicate.as` | Error 3: `let a` twice | E302 semantic 7:9 | - |
| `sem_type_mismatch.as` | Error 4: `web_search(42)` | E303 semantic 6:23 | - |
| `sem_missing_return.as` | Error 4: no return when `flag` is false | E304 semantic 9:3 | - |
| `sem_not_permitted.as` | Error 5: `read_file` without `permit read_file` | E305 semantic 6:16 | - |
| `sem_budget.as` | Error 6: four calls with `budget calls = 3` | E306 semantic 9:12 | - |
| `taint_injection.as` | Error 7: the PRD example without `sanitize` | E401 taint 9:14 | - |
| `approval_missing.as` | Error 8: `delete_file` on a path that skips `confirm` | E501 approval 7:14 | - |
| `approval_one_branch.as` | Error 9: `confirm` only inside one branch, delete after it | E502 approval 9:12 | - |
| `runtime_budget.as` | Error 10: `repeat times` warns, VM guard trips at the 4th call | W306 semantic 6:12; run E601 runtime 7:15 | `poll`, `{"topic": "news", "times": 5}` |
| `runtime_index.as` | Runtime: `results[9]` on a 3-element list | run E603 runtime 7:19 | `tenth`, `{"topic": "AI"}` |

That is 14 failing programs with 14 distinct codes (E101, E102, E201, E301, E302, E303, E304, E305,
E306, E401, E501, E502, E601, E603), against the PRD target of at least 8. E602 (unreachable from
compiled code) is shown by a unit test with hand-made bytecode, and E604 by API and VM tests.

---

## 8. API contract (`api.py`)

**`POST /compile`**

Request: `{"source": "..."}`. Response (`CompileResult.to_dict()`):

```json
{"ok": true,
 "diagnostics": [],
 "warnings_count": 0,
 "phases": {"tokens": {"text": "...", "data": []}, "ast": {"text": "...", "data": {}},
            "symbols": {}, "ir": {}, "cfg": {}, "taint": {}, "approval": {},
            "optimized_ir": {}, "schedule": {}, "bytecode": {}},
 "stats": {"before": {"instructions": 14, "calls": 5}, "after": {"instructions": 14, "calls": 5},
           "rounds_before": 5, "rounds_after": 5},
 "tasks": [{"name": "report", "params": [{"name": "topic", "type": "string"}], "return_type": "bool"}]}
```

`diagnostics` holds the warnings and at most one error (Diagnostic JSON, 4.9). Phases after the
failing one are `null`; `ok` is `false` when there is an error. (The numbers above show the shape
only.)

**`POST /run`**

Request: `{"source": "...", "task": "report", "args": {"topic": "AI safety"}, "live": false,
"confirm": true}`. Response:

```json
{"ok": true, "diagnostics": [], "value": true,
 "calls": [{"n": 1, "tool": "web_search", "args": ["AI safety"], "result": ["..."],
            "line": 6, "round": 1, "note": null}],
 "calls_used": 5, "budget": 5, "rounds": 5}
```

On a compile error: `ok: false`, the compile diagnostics, `value: null`, `calls: []`. On a runtime
error: `ok: false`, the runtime diagnostic, and the calls made before it.

**`GET /examples`**

```json
[{"file": "valid_report.as", "title": "...", "description": "...", "expect": null,
  "run": {"task": "report", "args": {"topic": "AI safety"}}, "source": "..."}]
```

Built from `examples/manifest.json` plus each file's source. `expect` is
`{"code", "phase", "line", "col"}` or `null`.

JSON-to-type mapping for run arguments: `string` <-> str, `int` <-> int (not bool), `bool` <->
bool, `list<T>` <-> array of T. Anything else is E604.

---

## 9. Requirements traceability

### PRD requirements

| Requirement | Milestone | Code | Tests |
| --- | --- | --- | --- |
| F1 lexer with line/col, E101, E102 | M1 | `lexer.py` | `test_lexer.py`; `test_pipeline.py` (lex examples) |
| F2 recursive-descent parser from the grammar, E201 with location | M1 | `parser.py` | `test_parser.py`; `test_pipeline.py` |
| F3 nested scopes, E301, E302 | M1 | `semantic.py` (`Scope`, `Symbol`) | `test_semantic.py`; `sem_undeclared.as`, `sem_duplicate.as` |
| F4 type checker (expressions, arguments, returns, conditions), E303, E304 | M1 | `semantic.py` | `test_semantic.py`; `sem_type_mismatch.as`, `sem_missing_return.as` |
| F5 permission check E305; VM guard E602 | M1 (E305), M2 (E602) | `semantic.py`, `vm.py` | `test_semantic.py`, `test_vm.py` (hand-made bytecode); `sem_not_permitted.as` |
| F6 static worst-path budget E306, W306; VM guard E601 | M2 | `semantic.py`, `vm.py` | `test_semantic.py`, `test_vm.py`; `sem_budget.as`, `runtime_budget.as` |
| F7 three-address code, basic blocks, CFG | M2 | `irgen.py`, `cfg.py`, `ir.py` | `test_irgen.py`, `test_cfg.py`, `test_golden.py` |
| F8 constant folding, dead code, duplicate calls | M3 | `optimizer.py` | `test_optimizer.py`; `optimize_demo.as` |
| F9 bytecode, stack VM, registry (mock default, `--live`) | M2 | `codegen.py`, `bytecode.py`, `vm.py`, `registry.py` | `test_codegen.py`, `test_vm.py`, `test_registry.py`, `test_cli.py` |
| T1 tools declare untrusted results and privileged sinks (built-in table) | M4 (table given) | `tools.py`, `taint.py` | `test_taint.py` |
| T2 propagation through assignment, concatenation, indexing, `llm` | M4 | `taint.py` | `test_taint.py` |
| T3 `sanitize` clears taint | M4 | `taint.py`, `tools.py` | `test_taint.py`; `valid_report.as` |
| T4 E401 naming source line, sink line and the path | M4 | `taint.py`, `diagnostics.py` | `test_taint.py`; `taint_injection.as` |
| A1 irreversible tools (built-in table) | M5 (table given) | `tools.py`, `approval.py` | `test_approval.py` |
| A2 dominator-based confirm guard rule | M5 | `cfg.py` (`dominators`), `approval.py` | `test_cfg.py`, `test_approval.py`; `valid_cleanup.as` |
| A3 violation shows one offending path, E501/E502 | M5 | `approval.py` | `test_approval.py`; `approval_missing.as`, `approval_one_branch.as` |
| L1 dependency graph, parallel rounds | M7 | `scheduler.py` | `test_scheduler.py`; `parallel_demo.as` |
| L2 VM runs rounds concurrently; editor shows rounds before/after | M7 | `vm.py`, `pipeline.py`, `web/app.js` | `test_vm.py`, `test_scheduler.py` |
| L3 no reordering across data dependencies or barrier tools | M7 | `scheduler.py` | `test_scheduler.py` |

### Editor requirements

| Requirement | Milestone | Code | Tests |
| --- | --- | --- | --- |
| Code pane with AgentScript highlighting | M6 | `web/app.js`, `web/index.html` | manual (M6 gate, demo script) |
| Inline error squiggles from diagnostics | M6 | `web/app.js` | `test_api.py` (diagnostic shape); manual |
| Phase tabs: Tokens, AST, Symbols, Errors, IR, CFG, Taint, Approval, Optimized IR, Rounds, Bytecode, Output | M6 (Rounds at M7) | `pipeline.py`, `web/app.js` | `test_api.py` (every phase key present); manual |
| CFG view (Mermaid) | M6 | `cfg.py` (`cfg_to_mermaid`), `pipeline.py`, `web/app.js` | `test_api.py` (cfg `data` has `mermaid`); manual |
| Taint view: untrusted values highlighted, path on error | M6 | `taint.py` (data), `web/app.js` | `test_api.py` (E401 path); manual |
| Approval view: guard blocks and checked irreversible calls, offending path on error | M6 | `approval.py` (artifact), `web/app.js` | `test_api.py` (E501/E502 diagnostic with `path`); manual |
| Optimization view: instruction and call counts before/after | M6 | `optimizer.py`, `pipeline.py` (`stats`), `web/app.js` | `test_optimizer.py`, `test_api.py` |
| Run panel: call log, budget used, live toggle | M6 | `api.py`, `vm.py`, `web/app.js` | `test_api.py` (`/run`); manual |
| Example picker: valid program + one failing program per error type | M6 | `api.py` (`/examples`), `examples/manifest.json` | `test_api.py`; `test_pipeline.py` |
| Backend `POST /compile`, `POST /run` | M6 | `api.py` | `test_api.py` |

### Success metrics

| Metric | Milestone | Code | Test or check |
| --- | --- | --- | --- |
| 6 of 6 classic phases implemented and visible in the editor (D27) | M1 to M3, shown at M6 | `lexer.py`, `parser.py`, `semantic.py`, `irgen.py`, `optimizer.py`, `codegen.py`, `web/` | `test_api.py` (phase keys); M6 gate |
| At least 8 distinct error types, each with its own failing program (14 delivered) | M1, M2, M4, M5 | `examples/`, `manifest.json` | `test_pipeline.py` over the manifest |
| Injection example rejected at compile time | M4 | `taint.py` | `test_taint.py`, `test_pipeline.py` (`taint_injection.as`) |
| Unapproved irreversible call rejected at compile time | M5 | `approval.py` | `test_approval.py`, `test_pipeline.py` (`approval_missing.as`) |
| Optimizer demo: duplicate call removed, counts before and after shown | M3, shown at M6 | `optimizer.py`, `web/app.js` | `test_optimizer.py` (4 -> 2); M3 gate |
| Stretch: 3 independent calls in 1 round | M7 | `scheduler.py`, `vm.py` | `test_scheduler.py` (`parallel_demo.as`, 4 -> 2) |

### PRD test approach

| Test approach item | Where |
| --- | --- |
| Unit tests per phase | `test_lexer.py` ... `test_scheduler.py` |
| Golden tests per demo program and phase | `test_golden.py`, `tests/golden/*.json`, `tests/update_golden.py` (from M2) |
| Negative tests with the right code and line | `test_pipeline.py` over `examples/manifest.json` |
| Optimizer count tests | `test_optimizer.py` |

---

## 10. Out of scope

Do not add any of these. They are left out on purpose to keep the language and the compiler small
enough to finish and explain.

| Left out | Why |
| --- | --- |
| `else if` chains | Nest an `if` inside `else` instead; one form keeps the grammar and CFG small. |
| Assignment statements, mutable variables | Single definitions make taint, approval and optimization simpler to state and prove. |
| `!`, `&&`, `\|\|`, `/`, `%`, unary minus | Not needed by any example; `/` would add division by zero. |
| List literals, maps, records, other types | Lists only come from `web_search`; four types are enough. |
| User functions, task-to-task calls, recursion | Each task is one CFG; no interprocedural analysis. |
| More than one agent per file, imports, modules | One file, one agent. |
| User-declared tools or annotations | The tool table is fixed (D1). |
| Loops other than `repeat N` (`while`, `for`, `break`) | `repeat` is enough to demonstrate error #10. |
| Implicit-flow taint, per-element list taint | Documented limitations (D6). |
| Parser error recovery, multiple errors per run | First error only (D14). |
| Language Server Protocol, VS Code extension | Optional future work in the PRD. |
| Database, user accounts, saved programs | Not needed for the demo. |
| Frontend frameworks or build tooling (React, npm, bundlers) | One static page (Step 0 answer). |
| Real email sending, real file deletion | Always simulated, even with `--live` (D18). |
| A hardened sandbox, production use, soundness proof | PRD non-goals. |
| Cross-block constant propagation, SSA, register allocation | Not required by F8; local passes are enough for the demo. |
