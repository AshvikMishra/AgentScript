# Viva notes

Likely questions with prepared answers. Answers follow the corrected design in `docs/PRD.md`;
if this file and the PRD disagree, the PRD wins. Notes of the form "Filled in at M#" mark
the numbers and real output that are added once that milestone has run.

Keep answers short in the viva: say the first sentence, then give the example only if asked.

Contents:

1. The PRD's questions, revised
2. One question per phase
3. One question per limitation
4. Other design questions
5. Related work

---

## 1. The PRD's questions, revised

### Does this already exist?

Parts of it do, the combination does not. LLM programming tools such as DSPy, LMQL,
Guidance and BAML are about prompting and structured output. Taint tracking, dominator
analysis and capability-style permissions are long-established security and compiler
techniques. AgentScript applies them together at compile time to agent programs: an
unsafe program does not compile, so no tool fires before the problem is found. It is a new
application of known techniques, not new research (see section 5).

### Why not just use Python?

Python cannot check a permission list, a call budget, a taint rule or an approval rule
before the program runs: calls are dynamic, any value can come from anywhere, and loops are
unbounded. AgentScript is deliberately small so these properties can be decided: a fixed
set of built-in tools with known annotations, immutable variables, no functions, no
task-to-task calls, and one bounded loop form (`repeat`). Each restriction exists to make
one of the checks exact or simple.

### Is the budget check guaranteed?

At runtime, always: the VM counts every executed call and stops with E601 before the call
that would exceed the budget. At compile time, only when every `repeat` count is an
integer literal. In that case the static count is an upper bound for every possible run:
every tool call counts as 1 (including `sanitize` and `confirm`), an `if` counts the more
expensive branch, `repeat n` multiplies its body by `n`, and early returns are ignored, so
the worst path is never undercounted. When a `repeat` count is a variable, the body is
counted once and the compiler emits warning W306 saying the budget for that loop is
enforced at runtime (`runtime_budget.as`: W306 at 6:12, and with `times = 5` the VM stops
with E601 at 7:15). The optimizer only removes calls and the scheduler never adds any, so
the checked count also bounds the program that actually runs.

> Filled in at M2: the E306 diagnostic for `examples/sem_budget.as` and the W306 and E601 output for `examples/runtime_budget.as`, from `.venv/bin/python -m agentscript compile` and `run`.

### Can the taint check miss attacks?

Yes, in documented ways. It tracks explicit data flow, not model behaviour: taint does not
flow through `if` conditions (implicit flow), `sanitize` is trusted by definition, task
parameters are trusted, and an LLM given trusted input is assumed to produce trusted
output. Within those rules it is conservative: any value that may carry untrusted data on
any path is treated as untrusted, so it rejects some safe programs rather than accept an
unsafe one. It cannot prove that the LLM itself behaves well. Each gap has its own answer
in section 3.

### Why do safety checks run before optimization?

So a guarantee is about the program the programmer wrote, not about what the optimizer
happened to remove. Example: in `if (debug) { delete_file(p); }` with `debug = false`, the
optimizer deletes the branch. Checking afterwards would accept an unconfirmed
`delete_file` that is one edit (`debug = true`) away from running. The same holds for the
budget: `optimize_demo.as` is checked at 4 calls even though it runs 2. It also means an
optimizer bug can never turn a rejected program into an accepted one; the order is
permission, budget, taint, approval on the unoptimized IR, then the optimizer.

### Which phase does each safety feature belong to?

| Feature | Phase | Works on | Error codes |
| --- | --- | --- | --- |
| Types | semantic analysis | annotated AST | E303, E304 |
| Permissions | semantic analysis (plus a VM guard) | AST | E305 (E602 at runtime) |
| Budget | semantic analysis (plus a VM guard) | AST | E306, W306 (E601 at runtime) |
| Taint | data-flow analysis | CFG of the unoptimized IR | E401 |
| Approval | control-flow analysis (dominators) | CFG of the unoptimized IR | E501, E502 |

Permissions and budget are properties of the syntax tree (which tools are named, how many
calls appear on a path), so they belong to semantic analysis. Taint and approval are
properties of paths through the program, so they need the CFG.

---

## 2. One question per phase

### How does your lexer work?

A hand-written scanner reads the whole file into a token list before parsing starts,
tracking 1-based line and column (a tab counts as one column). It uses longest match for
operators (`<=` before `<`, `==` before `=`, `->` before `-`), skips whitespace and `//`
comments, and turns identifiers that match a keyword into keyword tokens. `>>` is lexed as
two `>` tokens so `list<list<string>>` parses. Two errors: E101 for a string that hits a
newline or end of file before its closing quote, reported at the opening quote
(`lex_unterminated.as`, 6:13), and E102 for any character outside the language, such as
`#` (`lex_illegal_char.as`, 6:15). The first lexical error stops compilation. Why
hand-written: the token set is tiny, and it gives exact positions with no dependency.

> Filled in at M1: the first lines of `.venv/bin/python -m agentscript compile examples/valid_report.as --phase tokens`, the token count, and the number of tests in `tests/test_lexer.py`.

### How does your parser work?

Recursive descent, one function per grammar rule, from the EBNF grammar in the PRD.
Expressions use one function per precedence level, lowest first: equality, relational,
additive, `*`, postfix indexing, primary; each level loops, which makes every binary
operator left-associative. A call is recognised in `primary` as an identifier followed by
`(`. The parser builds the AST dataclasses in `agentscript/ast_nodes.py`. It reports only
the first syntax error, E201 "expected X, found Y". When the unexpected token is on a later
line than the previous token, the error is placed just after the previous token, because
that is where the missing `;` or `}` belongs (`syntax_missing_semicolon.as`: 6:30, not
7:5). Why recursive descent: the grammar is LL(1), so the code mirrors the grammar and is
easy to explain and debug.

> Filled in at M1: a short excerpt of `.venv/bin/python -m agentscript compile examples/valid_report.as --phase ast` and the number of tests in `tests/test_parser.py`.

### How does your semantic analysis work?

One walk over the AST in source order with a chain of scopes: builtins (the 7 tools),
agent (task names), task (parameters), then one scope per block (task body, each `if` and
`else` block, each `repeat` body). Lookup walks outward; a missing name is E301. There is
no shadowing: declaring a name that is visible anywhere outward is E302. Every expression
gets a static type; `let` infers its type from the initializer. Operators, tool arguments,
`if` conditions, indices, `repeat` counts and returns are checked (E303), every path of a
task must return (E304, at the task's closing `}`), and every called tool must be in
`permit` (E305). After the walk, the budget is checked per task on the worst path (E306,
W306). The first error stops compilation.

> Filled in at M1: the symbol table printed by `.venv/bin/python -m agentscript compile examples/valid_report.as --phase symbols`.

> Filled in at M2: the budget line of the same artifact (worst-path count 5 of budget 5 for task `report`).

### How do your IR and CFG work?

The AST is lowered to three-address code: each instruction has at most one operator, and
intermediate values go into temporaries `t1, t2, ...`. Instructions: `Assign`, `BinOp`,
`Index`, `Call`, `Jump`, `Branch`, `Return` and `Label` (plus `ParallelCalls` at M7). `if`
becomes a `Branch` to a then-label and an else- or end-label; `repeat N` becomes a counter
with a loop head that compares it with `N`. A variable name reused in a sibling scope is
renamed (`name.2`), so each IR variable has one static definition. `build_cfg` then cuts the
listing into basic blocks at every label and after every terminator, gives the first block
the label `entry`, and makes every block end with exactly one terminator; the edges come
from the `Jump`, `Branch` and `Return` instructions. Why three-address code and a CFG: data
flow (taint) and dominators (approval) are textbook algorithms over basic blocks, and the
optimizer and codegen work on the same structure.

> Filled in at M2: the IR listing and the CFG (blocks and edges) of `examples/valid_report.as`, from `.venv/bin/python -m agentscript compile examples/valid_report.as --phase ir` and `--phase cfg`.

### How does your taint analysis work?

A forward data-flow analysis over the CFG of the unoptimized IR. The state at each block
entry maps each variable to a label (trusted or untrusted) and a provenance (where the
taint came from). Transfer rules: parameters and literals are trusted; `Assign`, `BinOp` and
`Index` take the join of their operands (untrusted if any operand is); a call to
`web_search` or `read_file` is untrusted; `llm` takes the join of its argument; `sanitize`
is trusted; the other tools return trusted booleans. At a join point the states of the
predecessors are merged (untrusted wins). The analysis repeats until no block's set of
untrusted variables changes; it terminates because labels only ever go from trusted to
untrusted. Then every argument of a privileged tool (`send_email`, `delete_file`) is
checked; an untrusted one is E401 at the sink, with the provenance chain as the path
(`taint_injection.as`: 9:14, source `web_search` on line 6).

> Filled in at M4: the E401 diagnostic with its path for `examples/taint_injection.as` and the taint report for `examples/valid_report.as` (`--phase taint`).

### How does your approval analysis work?

It uses dominators: block D dominates block B if every path from the entry to B passes
through D. A guard block is the true successor of a `Branch` whose condition is a confirm
value (a variable defined only by a `confirm(...)` call or a copy of one). The rule: every
call to an irreversible tool (`delete_file`) must sit in a block dominated by a guard
block. Dominators are computed with the simple iterative algorithm: `Dom(entry) = {entry}`,
every other block starts with all blocks, then repeatedly `Dom(B) = {B} ∪ ⋂ Dom(P)` over
the predecessors P until nothing changes. When the rule fails, the error is E502 if some
block containing a `confirm` can reach the call (there is a confirm, but it does not guard
every path) and E501 otherwise; the path is a shortest entry-to-call path that avoids all
guard blocks (or, if none exists, one that avoids the first guard block). Why dominators rather than "a confirm appears before": `confirm` can return
false, and a confirm on one branch says nothing about the other branch.

> Filled in at M5: the dominator sets and guard block from `.venv/bin/python -m agentscript compile examples/valid_cleanup.as --phase approval`, and the E501 and E502 diagnostics with paths for `approval_missing.as` (7:14) and `approval_one_branch.as` (9:12).

### How does your optimizer work?

It works on a copy of the CFG after all safety checks have passed, and repeats four passes
until nothing changes: constant folding with local constant and copy propagation (a
`Branch` on a constant becomes a `Jump`); removal of blocks unreachable from the entry;
removal of `Assign` and `BinOp` whose result is never used (never `Call`, which has side
effects and budget cost, and never `Index`, which may raise E603); and duplicate tool-call
elimination. The last one only merges a call to a mergeable (read-only) tool with exactly
the same arguments as an earlier call to the same tool in the same basic block, with no
other call between them; it is never applied to `send_email`, `delete_file` or `confirm`.
`optimize_demo.as` goes from 4 tool calls to 2. Why the restrictions: merging is only safe
when the second call cannot observe or cause a different effect than the first.

> Filled in at M3: the before and after instruction and call counts and the change list from `.venv/bin/python -m agentscript compile examples/optimize_demo.as --phase optimized_ir`.

### How do your code generator and VM work?

Codegen lays out the blocks in CFG order and translates each IR instruction into stack
code: push the operands (`PUSH_CONST`, `LOAD`), apply the operation (`ADD`, `LT`, `INDEX`,
`CALL tool argc`, ...), and `STORE` the destination. A `Branch` becomes
`LOAD cond; JUMP_IF_FALSE else; JUMP then`, with the `JUMP` dropped when the then-block is
next; a `Jump` to the next block is dropped. The VM is a loop over that instruction list
with an operand stack and a variable map. `CALL` goes through a tool registry (mock by
default, optional live mode), and runtime guards check the budget (E601), the permit list
(E602, defensive; compiled programs cannot reach it), list indices (E603) and the run
request itself (E604). Why a stack machine: code generation from three-address code is
direct and needs no register allocation.

> Filled in at M2: the bytecode of `examples/valid_report.as` (`--phase bytecode`) and its run output with the 5-call log, including the mock injection text in the `web_search` result and the sanitized `sanitize` result (this also answers "The tools are mocks. Is anything real?" in section 3).

### How do your editor and API work?

FastAPI serves one static page (CodeMirror and Mermaid from a CDN, vanilla JavaScript, no
build step) and three endpoints: `GET /examples` (the example picker, from
`examples/manifest.json`), `POST /compile` (source in, every phase artifact out) and
`POST /run` (source, task name, arguments as JSON, the live and confirm switches). Every
phase artifact has the same shape, `{"text": ..., "data": ...}`, so each tab simply shows
one artifact, and the phases after a failing one are `null`. Diagnostics carry phase, code,
message, line, column and an optional path, which is all the editor needs to draw a
squiggle and list the path. The CLI and the API both call `agentscript/pipeline.py`, so
they cannot disagree.

> Filled in at M6: the `/compile` response for `examples/valid_report.as` (shortened) and a description of one Compile click as seen in the browser's network tab.

### How does your scheduler work?

Per basic block of the optimized CFG, it builds a dependency graph from definitions and
uses of variables. Calls to barrier tools (privileged, irreversible or approval) keep their
order relative to every other call in the block. It then does list scheduling: emit every
ready non-call instruction, then all ready calls together as one round (a `ParallelCalls`
group when there are two or more), and repeat; the terminator goes last. The VM runs each
round's calls concurrently and pushes the results in the original order.
`parallel_demo.as` goes from 4 rounds to 2: three independent `web_search` calls in round 1,
`llm` in round 2. Why per block only: moving calls across branches would need speculation,
and the approval proof was made on the block structure, so calls must stay in their block.

> Filled in at M7: the schedule report from `.venv/bin/python -m agentscript compile examples/parallel_demo.as --phase schedule` and the call log with round numbers from its run.

---

## 3. One question per limitation

### Taint only follows explicit flows. Is that a hole?

Yes, a known one. In `if (raw[0] == "yes") { send_email("me@example.com", "approved"); }` the
attacker decides whether the email is sent, but no untrusted value reaches `send_email`, so
it compiles. Tracking implicit flows would taint everything under an untrusted condition,
which in agent code rejects almost every program. Explicit flows catch the attack the
project targets: injected text being passed into a privileged tool.

> Filled in at M4: a sentence confirming the sketch above compiles (run it through `.venv/bin/python -m agentscript compile` on a scratch file, not in `examples/`).

### A list has one label. Is that imprecise?

In principle: one untrusted element taints the whole list. With today's language it costs
nothing, because there are no list literals and no way to build a list: lists come only
from parameters (trusted, every element) or `web_search` (untrusted, every element). It
would become imprecise if list construction were added, which is out of scope.

### Why are task parameters trusted?

Parameters come from whoever starts the run (the user, through `/run` or the CLI), and the
threat model is third-party content fetched by tools. Marking parameters untrusted would
reject ordinary programs such as `send_email(recipient, "Done")`, where the user chose the
recipient. A caller that
passes untrusted input as a parameter is outside what the compiler can see; a future
`untrusted` parameter annotation would cover it.

### Can the LLM launder taint?

The rule is that `llm` output carries the join of its input labels: untrusted in, untrusted
out; trusted in, trusted out. The model cannot launder untrusted input, because only
`sanitize` clears taint. The remaining gap is the other direction: after `sanitize`, the
prompt is trusted, so whatever the model writes is trusted too, even if sanitized text still
manipulated it or the model invents something harmful. That is model behaviour, not data
flow, and no static analysis of the program can rule it out.

### Why do two confirms on two branches not count?

The rule asks for one guard block that dominates the irreversible call. Sketch (not in
`examples/`):

```
if (urgent) {
  if (confirm("Urgent delete?")) { } else { return false; }
} else {
  if (confirm("Delete?")) { } else { return false; }
}
return delete_file(path);
```

Every path to the delete does pass a "yes", but through two different guards, and neither
dominates the join, so it is rejected (E502). Accepting it would need path-sensitive
reasoning ("on every path, some guard") instead of one dominator query. The fix is easy and
clearer: ask one `confirm` before the branch.

> Filled in at M5: the actual diagnostic for this sketch, compiled from a scratch file with `.venv/bin/python -m agentscript compile`.

### Why is `confirm(...) == true` not accepted as a guard?

The accepted forms are exactly `if (confirm("..."))` and `let ok = confirm("..."); if (ok)`.
Once comparisons are allowed, the checker has to evaluate them: `== true` guards,
`== false` inverts the meaning, `!= false` guards again, and so on. Keeping the rule to "the
condition is the confirm value itself" makes it a syntactic check on the IR with no
constant reasoning, and immutability of `let` guarantees `ok` still holds the confirm
result when it is tested. `if (confirm("x") == true)` is rejected with E502: a confirm is
present on the path, but the branch condition is a comparison, not the confirm value.

> Filled in at M5: the diagnostic for `if (confirm("x") == true) { ... delete_file ... }` from a scratch file.

### What about `repeat` with a variable bound?

The compiler cannot know the count, so the static budget counts the body once and emits
W306; the VM enforces the budget at runtime with E601 before the call that would exceed it
(`runtime_budget.as`). A count of 0 or less runs the body zero times. Why not reject the
program: bounded-by-a-parameter loops are a real need (poll `times` times), and the runtime
guard keeps the budget guarantee, only later.

### Are the analyses conservative? Show a false positive.

Yes, by design ("if in doubt, reject"). Three examples:

| Check | Safe program it rejects or over-counts |
| --- | --- |
| Budget | `approval_missing.as` counts 3 calls (`if (force)` branch + `confirm` + second `delete_file`), but any run makes at most 2, because the first branch returns. Early returns are ignored to keep the count structural |
| Taint | `send_email("me@example.com", "Found: " + raw[0])` is rejected even when the user really wants the raw result forwarded; the fix is `sanitize` |
| Approval | the two-confirm sketch above |

Each false positive has a simple rewrite, which is the price of checks that are easy to
explain and never miss within their rules.

### Why only the first syntax error?

No error recovery keeps the parser small, and recovery tends to produce cascades of
follow-on errors that confuse more than they help. The same rule applies to every phase:
each reports at most one error and compilation stops, so the last filled tab in the editor
identifies the phase that failed. Warnings (W306) do not stop compilation.

### The tools are mocks. Is anything real?

The compiler is entirely real; only the tool registry is mocked. Mocks are deterministic,
so tests and golden files are stable and the demo needs no network or API key. The mock
`web_search` deliberately returns an injection attempt so the sanitizing path can be shown.
Live mode is optional: `llm` calls the Anthropic Messages API when `ANTHROPIC_API_KEY` is
set, and `web_search` calls the DuckDuckGo instant-answer API; `send_email` and
`delete_file` are always simulated, and live `read_file` reads only under `./sandbox/`. A
failing live call falls back to the mock result and says so in the call log. The call log
pasted under "How do your code generator and VM work?" shows the mock injection text and
the sanitized result.

### `sanitize` is trusted by fiat. Is that honest?

It is a stated assumption. The compiler guarantees that every untrusted value passes
through `sanitize` before a privileged tool; it does not judge how good `sanitize` is. The
mock replaces one known injection phrase, which is enough to demonstrate the flow, not a
real defence. In a real system `sanitize` would be a vetted filter or a human review step,
and the compiler's job, making sure it cannot be skipped, stays the same.

---

## 4. Other design questions

### Why add `repeat` when the original PRD had no loops?

The original PRD's risks, viva answers and error #10 ("call count depends on a runtime
value") all talk about loops, but the language had none, so the runtime budget error could
not happen. One bounded form, `repeat N { ... }` with `N` a literal or an int variable,
fixes that with the least new language: it always terminates, the static budget is
`N × body` for a literal, and a variable bound shows the runtime guard.

### Why does every tool call count against the budget, including `sanitize` and `confirm`?

One uniform rule is easier to state, check and explain than a list of exceptions, and each
call has a real cost (an API call or a human interruption). The PRD example still fits:
`web_search`, `sanitize`, `llm`, `confirm`, `send_email` is exactly 5 of 5.

### Why are tool annotations a built-in table and not syntax?

The tool set is fixed, and an annotation the programmer can write is an annotation the
programmer can get wrong or remove to make an error go away. Keeping the flags (untrusted
result, propagates taint, sanitizer, privileged, irreversible, approval, mergeable) in
`agentscript/tools.py` means the safety policy is not part of the program being checked.

### Why are variables immutable and why no shadowing?

The approval rule depends on it: `let ok = confirm(...)` can only be trusted as a guard if
`ok` cannot be reassigned before `if (ok)`. Immutability also gives each variable one
definition, which keeps taint provenance and the scheduler's dependency graph simple. No
shadowing removes a class of confusing programs and makes scope errors easy to explain.

### Why is `send_email` not irreversible?

The PRD's tool table marks it as a privileged sink only. So it is checked by taint (its
arguments must be trusted) but needs no `confirm`; the PRD example's `confirm` around it is
good practice, not a requirement. `delete_file` is both privileged and irreversible, so it
needs both.

### How many phases, and why does the PRD say "6 of 6"?

There are 10 pipeline stages (9 required plus the M7 scheduler): lexer, parser, semantic
analysis, IR and CFG, taint, approval, optimizer, scheduler, codegen and VM. The "6 of 6"
metric counts the six classic compiler phases (lexical, syntax, semantic, intermediate
code, optimization, code generation); every required stage also has its own editor tab.

---

## 5. Related work

Listed from memory: before the viva, confirm each row's description with a quick search,
since these projects change quickly.

| Work | What it is | Difference from AgentScript |
| --- | --- | --- |
| DSPy | Framework for building LLM pipelines from declarative modules, with automatic prompt optimization | Optimizes prompts and pipelines; no static safety checks on tool use |
| LMQL | Query language for LLMs with constraints on the generated output | Constrains what the model generates, not where data flows between tools |
| Guidance | Templating and constrained generation library | Output structure and control of generation, not program safety |
| BAML | DSL for typed LLM functions and structured outputs | Types the model's output; no taint, approval or budget analysis |
| Taint analysis and information-flow control (Denning's lattice model, Perl taint mode, Jif, TaintDroid, FlowDroid) | Tracking untrusted or secret data through programs | Same idea; here the lattice has two labels and the sinks are agent tools |
| Capability and effect systems (object capabilities, effect type systems such as Koka's) | Restricting which effects a program can perform, visible in its interface | `permit` is a capability list; `irreversible` and `privileged` are effect annotations on tools |
| Agent prompt-injection defences (for example the dual-LLM pattern and CaMeL) | Runtime designs that separate trusted control from untrusted data in LLM agents | These enforce policies while the agent runs; AgentScript rejects the program before it runs |
