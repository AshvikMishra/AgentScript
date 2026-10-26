# AgentScript PRD

Oct 12, 2026 · @sahur

## Overview

AgentScript is a small language and compiler for AI agents, built so that unsafe agent programs fail to compile. A program declares which tools the agent may use, how many calls it may make, and which tools are irreversible. The compiler then proves two safety properties before anything runs: untrusted data (such as web search results) never reaches a privileged tool without sanitizing, and no irreversible action is reachable without a human approval step.

The compiler outputs bytecode for a stack VM, which dispatches to a tool registry (mocked by default, real APIs optional). It covers every classic phase (lexical analysis, parsing, semantic analysis, intermediate code generation, optimization, code generation) and connects to a web code editor that shows each phase's output.

## Problem and motivation

Agent frameworks today check safety at runtime, if at all, so mistakes surface only after a tool has already fired. Three failure modes matter most:

- **Prompt injection:** text fetched from the web or a file contains instructions, and the agent passes it into a tool like `send_email` or `run_shell`.
- **Irreversible actions:** the agent deletes a file or sends a message with no human confirmation.
- **Unbounded tool use:** the agent loops or repeats identical calls, wasting money and hitting rate limits.

A compiler can catch the first two with static analysis (data-flow and control-flow) and reduce the third with permission lists, call budgets and duplicate-call elimination. These checks run before execution and give the programmer a precise error message.

## Goals, non-goals and success metrics

The project succeeds if every compiler phase works end to end and the two headline safety checks catch real violations on demo programs.

**Goals**

- Implement all classic phases on a deliberately tiny language.
- Reject programs with an unsanitized untrusted-to-privileged data flow (taint tracking).
- Reject programs where an irreversible tool is reachable on a path without approval (approval-path checking).
- Show phase outputs side by side in a web editor.
- Stretch: run independent tool calls in parallel.

**Non-goals**

- A general-purpose language, a full standard library, or a package system.
- A formal soundness proof (limitations are documented instead).
- Production use or a hardened sandbox.

**Success metrics**

| Metric | Target |
| --- | --- |
| Phases implemented and visible in the editor | 6 of 6 |
| Distinct error types demonstrated, each with its own failing program | at least 8 |
| Injection example (untrusted data into a privileged tool) | rejected at compile time |
| Unapproved irreversible call | rejected at compile time |
| Optimizer demo | duplicate tool call removed, call count shown before and after |
| Stretch: parallel rounds | 3 independent calls run in 1 round |

## Language design

The language has agents, tasks, typed variables, `if`, and calls to a fixed set of built-in tools. Safety is expressed with three declarations: `permit` (allowed tools), `budget` (call limit) and tool annotations (`untrusted` sources, `privileged` sinks, `irreversible` actions).

**Types:** `string`, `int`, `bool`, `list<T>`. Each value also carries a hidden **taint label**: `trusted` or `untrusted`.

**Built-in tools (initial set)**

| Tool | Signature | Annotation |
| --- | --- | --- |
| `web_search` | string → list\<string> | returns untrusted |
| `read_file` | string → string | returns untrusted |
| `llm` | string → string | result inherits taint of its input |
| `send_email` | (string, string) → bool | privileged sink |
| `delete_file` | string → bool | privileged sink, irreversible |
| `sanitize` | string → string | clears taint |
| `confirm` | string → bool | human approval step |

**Example program (valid)**

```
agent Assistant {
  permit web_search, llm, sanitize, send_email, confirm;
  budget calls = 5;

  task report(topic: string) -> bool {
    let raw = web_search(topic);
    let clean = sanitize(raw[0]);
    let summary = llm("Summarize: " + clean);
    if (confirm("Send report?")) {
      return send_email("me@example.com", summary);
    }
    return false;
  }
}
```

If the `sanitize` line is removed, `raw[0]` (untrusted) flows through `llm` into `send_email` and compilation fails with a taint error. If `confirm` is removed and the tool were `delete_file`, compilation fails with an approval-path error.

## Functional requirements

The core pipeline and both safety analyses are P0; parallelization is P1 and is cut first if time runs short.

**P0: core pipeline**

| ID | Requirement |
| --- | --- |
| F1 | Lexer produces tokens with line and column; reports unterminated strings and illegal characters. |
| F2 | Recursive-descent parser builds an AST from a BNF grammar; reports syntax errors with location. |
| F3 | Symbol table with nested scopes (agent, task, block); detects undeclared and duplicate names. |
| F4 | Type checker for expressions, tool arguments, return types and `if` conditions. |
| F5 | Permission check: any call to a tool not in `permit` is an error. |
| F6 | Budget check: statically counted calls on the worst path must not exceed `budget`; the VM enforces it again at runtime. |
| F7 | Three-address code generator with basic blocks and a control flow graph (CFG). |
| F8 | Optimizer: constant folding, dead code elimination, duplicate tool-call elimination. |
| F9 | Bytecode generator and stack VM with a tool registry (mock by default, `--live` for real APIs). |

**P0: taint tracking (headline feature 1)**

| ID | Requirement |
| --- | --- |
| T1 | Tools declare whether their result is `untrusted` and whether they are `privileged` sinks. |
| T2 | Data-flow analysis over the IR propagates taint through assignments, string concatenation, indexing and `llm` calls. |
| T3 | `sanitize` clears taint; its output is `trusted`. |
| T4 | A tainted value reaching a privileged tool argument is a compile error that names the source line, the sink line and the path between them. |

**P0: approval-path checking (headline feature 2)**

| ID | Requirement |
| --- | --- |
| A1 | Tools can be marked `irreversible`. |
| A2 | Using the CFG and dominator analysis, every path from task entry to an irreversible call must pass a `confirm` call whose result guards the call. |
| A3 | A violation is a compile error that shows one offending path. |

**P1: automatic parallelization (stretch)**

| ID | Requirement |
| --- | --- |
| L1 | Build a dependency graph from the IR and group independent tool calls into parallel rounds. |
| L2 | The VM runs each round concurrently; the editor shows the number of rounds before and after. |
| L3 | Parallelization never reorders calls that have a data dependency or involve irreversible tools. |

**Editor (P0):** see the editor section.

## Compiler architecture

The source flows through a front end (lexer, parser, semantic analysis), a middle end (IR, CFG, analyses, optimizer) and a back end (bytecode and VM). Each phase hands a printable artifact to the next, which is what the editor displays.

&#91;embedded content: compiler pipeline · 10 stages, 1 stretch\]

Read the top row left to right, then the bottom row; the highlighted step is where both headline features run, before any optimization. The dashed step is the stretch goal.

| Phase | Input → output | Key techniques |
| --- | --- | --- |
| Lexical analysis | source text → tokens | Hand-written scanner or regex rules; line and column tracking |
| Syntax analysis | tokens → AST | Recursive descent, operator precedence, error recovery |
| Semantic analysis | AST → annotated AST + symbol table | Scoped symbol table, type checking, permission and budget checks |
| Intermediate code generation | annotated AST → three-address code | Temporaries, labels, basic blocks, CFG |
| Taint analysis | IR → taint report | Forward data-flow analysis to a fixed point over the CFG |
| Approval-path analysis | CFG → path report | Dominator computation; every irreversible call must be dominated by its `confirm` |
| Optimization | IR → smaller IR | Constant folding, dead code elimination, duplicate tool-call elimination |
| Parallel scheduling (stretch) | IR → rounds | Dependency graph, topological layering |
| Code generation | IR → bytecode | Stack-machine instruction selection |
| Runtime | bytecode → results | VM loop, tool registry, runtime permission and budget guards |

**Ordering rule:** safety analyses (permission, budget, taint, approval) run on the unoptimized program, so a guarantee never depends on what the optimizer happens to remove.

## Editor and demo experience

The editor is a web page with a code pane on the left and a results pane on the right, backed by a compiler API. Pressing Compile runs the pipeline and fills the tabs; pressing Run executes the bytecode.

- **Code pane:** Monaco or CodeMirror with syntax highlighting for AgentScript and inline error squiggles from the compiler's diagnostics.
- **Phase tabs:** Tokens, AST, Symbols, Errors, IR, CFG, Taint report, Optimized IR, Bytecode, Output.
- **Taint view:** untrusted values highlighted in the code, with the flow path from source to sink listed on error.
- **Optimization view:** instruction count and tool-call count before and after.
- **Run panel:** call log showing each tool called, its arguments, and the budget used. A `--live` toggle switches mock tools to real APIs.
- **Example picker:** one valid program plus one failing program per error type, so the demo can jump between them.

**Backend:** Python with Flask or FastAPI exposing `POST /compile` (returns every phase artifact as JSON) and `POST /run`. Optional later: a Language Server Protocol server for VS Code.

## Error taxonomy and test plan

Each phase owns a class of errors, and each class has at least one failing demo program. This is what lets an evaluator watch every phase catch its own mistakes.

| # | Phase | Error | Failing example |
| --- | --- | --- | --- |
| 1 | Lexical | Unterminated string, illegal character | `let s = "abc;` |
| 2 | Syntax | Missing semicolon or brace | `let a = web_search(topic)` |
| 3 | Semantic | Undeclared or duplicate variable | `return x;` with no `x` |
| 4 | Semantic | Type mismatch | `web_search(42)` |
| 5 | Semantic | Tool not permitted | `read_file(...)` without `permit read_file` |
| 6 | Semantic | Budget exceeded | four tool calls with `budget calls = 3` |
| 7 | Taint | Untrusted data reaches privileged tool | search result piped to `send_email` unsanitized |
| 8 | Approval path | Irreversible call without confirm | `delete_file(...)` on a path that skips `confirm` |
| 9 | Approval path | Confirm on only one branch | `confirm` inside `if`, `delete_file` after it |
| 10 | Runtime | Budget or permission guard trips in the VM | call count depends on a runtime value |

**Test approach**

- Unit tests per phase (token streams, AST shapes, symbol tables, IR snapshots).
- Golden tests: each demo program has an expected output for every phase.
- Negative tests: every row above must fail with the stated error and the correct line number.
- Optimizer tests: assert the instruction and tool-call counts before and after.

## Milestones and build order

Build a safe, demo-ready version first and add each headline feature on top, so there is always something working to present. Dates are left open until the submission deadline and team size are confirmed.

1. **M1: minimal pipeline.** Grammar, lexer, parser, AST printer, symbol table, basic type checking. Gate: the valid example parses and type-checks.
2. **M2: IR and VM.** Three-address code, basic blocks, CFG, bytecode, VM with mock tools, permission and budget checks. Gate: the valid example runs end to end.
3. **M3: optimizer.** Constant folding, dead code elimination, duplicate tool-call elimination. Gate: the before and after counts show on screen.
4. **M4: taint tracking.** Tool annotations, data-flow analysis, error with source-to-sink path. Gate: the injection example is rejected, and the sanitized version compiles.
5. **M5: approval-path checking.** Dominator analysis on the CFG, error with offending path. Gate: all three approval examples behave as specified.
6. **M6: editor.** Web UI, phase tabs, example picker, error squiggles. Gate: a full demo run without touching the terminal.

**Cut line:** M1 to M6 are required. **M7: parallel scheduling** is built only if M1 to M6 are done and tested; otherwise it is described as future work.

**Open questions**

- What is the submission or viva date, and how many people are on the team?
- Is Python acceptable for the lab, or must it be C/C++ with lex and yacc?

## Risks and limitations

The biggest risk is over-scoping, so the language stays tiny and the cut line above is enforced.

| Risk or limitation | Impact | Mitigation |
| --- | --- | --- |
| Over-scoping the language (loops, functions, many types) | Half-finished phases | Fix the feature set to the example grammar; add features only after M6 |
| Budget cannot be known statically when loop counts depend on runtime values | Static check is an estimate, not a proof | Count the worst case where bounds are literal; enforce the budget again in the VM; state this limit openly |
| Taint analysis is conservative (it may flag safe programs) | False positives | Provide `sanitize`; document the rule as "if in doubt, reject" |
| Taint through the LLM is approximate: the model may transform or launder text | Analysis assumes taint passes through `llm` | Treat `llm` output as tainted whenever its input is; only `sanitize` clears it |
| Real API calls fail or are slow during the demo | Broken live demo | Mock tools by default; `--live` is optional |
| Parser error recovery is hard | Only the first syntax error is shown | Report the first error clearly; add recovery only if time allows |
| The "AI agent" angle looks like a label on a toy language | Lower perceived value | Make the taint, approval and budget failures the center of the demo |

## Related work and viva preparation

AgentScript is a novel application of known techniques, not new research. Taint tracking, dominator analysis and capability-style permissions come from security and compiler theory; the contribution is combining them in a small, working compiler for agent programs. The tools below are listed from memory and need a quick search before the viva to confirm their current focus.

- **DSPy, LMQL, Guidance, BAML:** LLM programming tools, mostly about prompting and structured output rather than static safety guarantees.
- **Taint analysis and information-flow control:** established in security tooling; here applied to data flowing between agent tools.
- **Capability and effect systems:** the idea behind `permit` lists and irreversible-tool annotations.

**Likely viva questions**

| Question | Prepared answer |
| --- | --- |
| Does this already exist? | Related tools exist but focus on prompting; this focuses on compile-time safety. Name the prior art and the difference. |
| Why not just use Python? | Python cannot check a permission list, a call budget or a taint rule before running. |
| Is the budget check guaranteed? | Only for straight-line code and literal loop bounds; the VM enforces it again at runtime. |
| Can the taint check miss attacks? | It tracks data flow, not model behavior; it is conservative and cannot prove the LLM itself is safe. |
| Why do safety checks run before optimization? | So a guarantee never depends on which instructions the optimizer removes. |
| Which phase does each safety feature belong to? | Permissions, budget and types: semantic analysis. Taint and approval: data-flow and control-flow analysis on the IR. |