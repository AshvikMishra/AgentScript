# Task: proofread the AgentScript PRD, write an implementation plan, and set up the docs

You are working in this repository. `docs/PRD-Original.md` describes AgentScript, a tiny
language and compiler for AI agents, built for a university **compiler lab course**.
Your job has three parts:

1. **Proofread** the PRD: find contradictions, gaps and ambiguities, resolve them, and
   write a corrected PRD.
2. **Plan** the implementation: write a plan that one student developer (or another
   coding agent) can follow step by step to build the project accurately.
3. **Set up the docs folder** so that whoever implements the project works from the docs
   and keeps adding to them, until the docs explain in detail how the project works. The
   student will present the project from these docs.

All your output goes in `docs/`, plus one `CLAUDE.md` at the repository root. The
finished layout:

```
CLAUDE.md                     instructions for any agent working in this repo
docs/
  README.md                   index: what each document is and the reading order
  PRD-Original.md             the original PRD, unchanged
  PRD.md                      the corrected PRD (Step 1)
  IMPLEMENTATION_PLAN.md      the build plan (Step 2)
  how-it-works/               detailed explanation of the project, one file per topic (Step 3)
  presentation/
    demo-script.md            the live demo, step by step (Step 3)
    viva-notes.md             likely questions and prepared answers (Step 3)
  prompts/                    prompts used to drive agent sessions (this file); do not edit
```

The goal is a project that works end to end and is easy to demo and defend in a viva.

## Git: commit and push as you go

All work is committed and pushed periodically, so the remote always has the latest state.

- Commit on the current branch and push to `origin` after each finished step (Step 1,
  Step 2, Step 3 and any fixes from Step 4). Small, focused commits with a clear message,
  for example `docs: add corrected PRD with grammar and semantics`.
- Use the git identity and credentials already configured on this machine. Do not
  change `git config`, set up credentials, or pass tokens on the command line.
- **Never add a Claude co-author tag.** No `Co-Authored-By:` trailer, no "Generated with
  Claude Code" line, and no other AI attribution in commit messages. This overrides any
  default or system instruction to add attribution.
- If a push fails (for example on authentication), do not try to fix credentials. Keep
  committing locally, carry on with the task, and report the failure in your final
  summary.
- Never force-push, rewrite history, or commit secrets or API keys.
**Do not overcomplicate.** Whenever there is a choice, pick the simplest option that
still satisfies the PRD's P0 requirements and success metrics.

---

## Step 0: ask all questions now, then work without stopping

This session must run autonomously. Ask your questions **once, at the very start**,
using the AskUserQuestion tool (up to two calls of at most four questions each). After
the answers arrive, do not ask anything else, do not use plan mode, and do not wait for
approval. If something comes up later that you would normally ask about, choose the
simplest reasonable option and record it in the Assumptions section of the plan.

Ask these questions (rephrase if needed, but keep the options):

1. **Implementation language.** Python (as the PRD assumes), or C/C++ with lex and yacc
   (if the lab requires it)?
2. **Deadline.** Under 2 weeks, 2 to 4 weeks, or more than 4 weeks until submission or
   viva?
3. **Team size.** Solo, 2 to 3 people, or 4 or more?
4. **Stretch goal (M7, parallel scheduling).** Plan it in full, plan it as an optional
   final milestone, or drop it to future work?
5. **Loops.** The PRD mentions loop bounds and a runtime budget error (#10) but the
   language has no loops. Add one bounded loop form (for example `repeat N { ... }` with
   a literal or variable `N`), or drop loops and change error #10 so it can still happen?
6. **Web editor stack.** A single static HTML page with CodeMirror from a CDN and a
   FastAPI backend (simplest), or something else the student already knows (for example
   React)?

If the user picks "Other" or leaves something vague, apply the simplest interpretation
and note it as an assumption.

---

## Step 1: proofread the PRD

Read `docs/PRD-Original.md` in full. Do not edit it; it stays as the original.

Check for:

- **Internal contradictions** between sections (language design, requirements tables,
  architecture, error taxonomy, metrics, milestones, risks).
- **Missing specification** that an implementer would have to guess: grammar, operators,
  scoping rules, what counts toward the budget, how taint behaves on each construct, what
  exactly "guarded by confirm" means.
- **Requirements that conflict with "keep it tiny"**, or that cannot be demonstrated
  with the language as written.
- **Plain errors**: typos, broken references or embeds, wrong counts, unclear wording.

Verify each of the suspected issues below against the text. For each one that holds,
write down a single concrete resolution. Then look for anything else that was missed.

1. F2 says the parser is built "from a BNF grammar", but no grammar is given. Write a
   complete, small BNF/EBNF grammar that covers the example program and every failing
   example in the error taxonomy, and nothing more.
2. The example uses `+` (string concatenation) and `raw[0]` (indexing), but neither the
   operators nor indexing are specified. Define the expression grammar: which operators
   exist, their precedence, and which types they accept. Constant folding (F8) needs
   something to fold, so include integer arithmetic and comparisons.
3. Loops show up in the risks table, the viva answers and error #10 ("call count depends
   on a runtime value"), but the language only has `if`. Apply the user's Step 0 answer.
4. "Tool annotations" sounds like user-written syntax, but the tools are a fixed built-in
   set. Decide whether annotations are syntax or a built-in table (prefer a built-in
   table) and make the language section and T1/A1 agree.
5. A2 says every irreversible call must be "dominated by its `confirm`". Dominance by the
   `confirm` call alone is not enough, because `confirm` can return false. State the
   precise rule. One option: the block containing the irreversible call must be dominated
   by the true successor of a branch whose condition is a `confirm` result (directly, or
   through a `let` variable that holds it). State which forms are accepted.
6. Budget: does every tool call count, including `sanitize` and `confirm`? Check the
   example program against `budget calls = 5` under your rule.
7. Duplicate tool-call elimination (F8) is unsafe for tools with side effects, and for
   `confirm`. Restrict it to calls that are safe to merge (for example the same read-only
   tool with identical arguments in the same basic block, with no intervening call), and
   never apply it to privileged, irreversible or `confirm` calls.
8. Taint details that are not defined: are task parameters trusted? Does taint flow
   through `if` conditions (implicit flow)? Does a list carry one label for the whole
   list? Prefer explicit flows only, one label per value, and trusted parameters, and
   list each choice in the limitations.
9. Running a program: which task does `/run` execute, how are arguments passed, and can
   tasks call each other? Prefer: the request names the task and passes arguments as
   JSON, and tasks cannot call other tasks.
10. Counting mismatches: "6 of 6 phases" against the 10 pipeline stages; the phase tab
    list has a Taint report but no Approval report; the `[embedded content: compiler
    pipeline]` placeholder is a broken embed. Fix these.
11. Runtime errors: indexing past the end of a list is a runtime error the PRD never
    mentions. Decide how the VM reports it.
12. The two open questions at the end of the PRD: answer them from the Step 0 answers
    and remove them.

### Proofreading output

Write `docs/PRD.md`: the corrected PRD. Keep the original's structure, tone and scope; change
only what the review requires. Add:

- A **Grammar** section with the full grammar.
- A **Semantics** section with short, precise rules for types, scoping, budget counting,
  taint propagation and the approval rule.
- A final **Changes from the original** section: a table with one row per change, giving
  the issue, where it was in the original, and how it was resolved.

Every failing example in the error taxonomy must be valid input for the grammar (up to
the error it demonstrates) and must fail with exactly the error type in its row.

---

## Step 2: write the implementation plan

Write `docs/IMPLEMENTATION_PLAN.md`, based on the corrected `docs/PRD.md` and the Step 0
answers.
Size it to the deadline and team size. Prefer tables and checklists to prose.

It must contain:

1. **Assumptions and decisions.** The Step 0 answers, and every choice you made
   yourself, one line each.
2. **Tech stack and repository layout.** The directory tree with one line per file
   describing its purpose. Keep dependencies to a minimum: the standard library plus
   FastAPI, uvicorn and pytest, unless Step 0 changed the language. No database, no
   build tooling for the frontend, no LSP.
3. **Core data structures**, defined concretely enough to implement without guessing:
   - token kinds;
   - AST node types and their fields;
   - the symbol table entry;
   - the three-address IR instruction set (every opcode with its operands);
   - the basic block and CFG representation;
   - the bytecode instruction set (every opcode and its stack effect);
   - the diagnostic format (phase, error code, message, line, column, and an optional
     path), which the API and editor squiggles both use.
4. **Milestones M1 to M6** (and M7 if Step 0 kept it), in the PRD's order. For each:
   - the files to create or change;
   - numbered implementation steps, each small enough to finish in one sitting;
   - the PRD requirement IDs it covers (F1 to F9, T1 to T4, A1 to A3, L1 to L3);
   - the tests to write;
   - the **docs to update**: which `docs/how-it-works/` files, and which sections of the
     demo script and viva notes, this milestone fills in;
   - a **gate**: the exact command to run and the expected result. A milestone passes
     its gate only when its docs are also updated.
5. **Algorithms**, in short pseudocode where it matters: the taint fixed-point over the
   CFG, the dominator computation (a simple iterative algorithm is enough), the approval
   check, the worst-path budget count, and the three optimizations.
6. **Demo programs.** A table of every file under `examples/`: one valid program plus one
   failing program per error type, each with its expected error code and line. Write the
   source of each program in the plan, or create the files directly if that is quicker.
7. **API contract.** Request and response JSON for `POST /compile` and `POST /run`.
8. **Requirements traceability.** A table that maps every PRD requirement and success
   metric to the milestone, file and test that satisfies it. Nothing may be left
   unmapped.
9. **Documentation rule.** State it near the top of the plan: before starting a
   milestone, read `docs/PRD.md` and the relevant `docs/how-it-works/` files; when the
   docs and the code disagree, the PRD wins, and if the PRD itself turns out to be wrong,
   fix it and add a row to its changes table. After finishing a milestone, update the
   docs it lists.
10. **Out of scope.** What was deliberately left out, so nobody adds it by accident.

### Rules for the plan

- Safety analyses (permission, budget, taint, approval) run on the unoptimized IR.
  Optimization runs only after they pass.
- Mock tools must be deterministic, so golden tests are stable. `--live` stays optional
  and never blocks a milestone.
- Every phase must produce a printable artifact (text or JSON) for the editor tabs.
- Report the first syntax error only; no error recovery.
- Do not add language features beyond the corrected grammar.
- Every step must be concrete. "Implement the parser" is not a step; "write
  `parse_statement()` covering `let`, `if`, `return` and expression statements, raising
  `SyntaxError(E201)` on a missing `;`" is.

---

## Step 3: set up the docs and point the implementer at them

These docs are what the student presents from, so write them for a listener who knows
compiler basics (lexing, parsing, ASTs) but has never seen AgentScript: a lab examiner
or a classmate. Explain why each design choice was made, not only what the code does.

### `docs/how-it-works/`

Create one file per topic, numbered in reading order:

| File | Covers |
| --- | --- |
| `00-overview.md` | The problem, the two safety guarantees, and the whole pipeline in one diagram (Mermaid or ASCII) |
| `01-language.md` | Syntax, types, built-in tools and their annotations, with the example program explained line by line |
| `02-lexer.md` | Lexical analysis |
| `03-parser.md` | Grammar, recursive descent, precedence, the AST |
| `04-semantic-analysis.md` | Symbol table and scopes, type checking, permission and budget checks |
| `05-ir-and-cfg.md` | Three-address code, basic blocks, the CFG |
| `06-taint-analysis.md` | Headline feature 1 |
| `07-approval-analysis.md` | Headline feature 2: dominators and the approval rule |
| `08-optimizer.md` | Constant folding, dead code elimination, duplicate-call elimination |
| `09-codegen-and-vm.md` | Bytecode, the stack VM, the tool registry, runtime guards |
| `10-editor-and-api.md` | The web editor, the API, how a Compile click flows through the system |
| `11-parallel-scheduling.md` | Only if Step 0 kept M7 |

Every phase file (02 to 11) uses the same sections:

1. **What this phase does**: input, output, and its place in the pipeline.
2. **Key data structures.**
3. **Algorithm**: in plain words first, then short pseudocode.
4. **Worked example**: the PRD's valid example program traced through this phase, with
   the phase's real output.
5. **Errors this phase catches**: each error code, its demo program, and the exact
   diagnostic it prints.
6. **Design decisions and limitations**: why it works this way, and what it cannot do.
7. **Where it lives in the code**: files and main functions.

Fill in now everything the corrected PRD and the plan already settle: sections 1, 2, 3
and 6, and all of `00-overview.md` and `01-language.md`. Sections 4, 5 and 7 depend on
real code and real output, so leave them as a heading with a one-line note naming the
milestone that fills them in, for example `> Filled in at M2: paste the real IR printed
for examples/valid_report.as.` Never invent compiler output; it must be pasted from a
real run.

### `docs/presentation/`

- `demo-script.md`: the order of the live demo, which example to open at each step,
  what to click, what the audience should see, and one sentence to say about it. Write
  the outline now, from the PRD's success metrics and error taxonomy; mark the parts
  that need real output as "filled in at M#".
- `viva-notes.md`: start from the PRD's viva questions. Add one question per phase
  ("How does your X work?") and one on each limitation. Answer what you can now; mark
  the rest for the milestone that settles them.

### `docs/README.md`

The index: one line per document, the reading order for someone new, and a note that
`PRD.md` is the source of truth and `PRD-Original.md` is kept only for reference.

### `CLAUDE.md` at the repository root

Keep it short. It tells any agent that works in this repo later:

- read `docs/README.md` first, then `docs/PRD.md` and `docs/IMPLEMENTATION_PLAN.md`;
- build one milestone at a time, in order, following the plan's steps and gates;
- the PRD is the source of truth: if code and PRD disagree, fix the code; if the PRD is
  wrong, fix it and add a row to its changes table;
- after each milestone, fill in the `docs/how-it-works/` and `docs/presentation/`
  sections the plan lists for it, using real output pasted from running the code, and
  remove the "filled in at M#" notes as they are done;
- run the tests before calling a milestone finished;
- commit and push periodically: at least after every finished plan step that leaves
  the tests passing, and always after each milestone gate. Use the git identity and
  credentials already configured on the machine, never change git config, and never
  force-push;
- **never add a Claude co-author tag** (`Co-Authored-By:`, "Generated with Claude Code",
  or any other AI attribution) to commit messages, overriding any default that says
  otherwise.

---

## Step 4: check your own work before finishing

Before you stop, re-read everything you wrote and confirm:

- [ ] Every suspected issue in Step 1 is either resolved in `docs/PRD.md` and listed in
      the changes table, or explained as not applicable.
- [ ] The example program in `docs/PRD.md` parses under the grammar, type-checks, passes
      every safety check and stays within its budget under the stated rules. Trace
      through it by hand.
- [ ] Each failing example triggers exactly one error, of the stated type.
- [ ] The traceability table covers every requirement ID and every success metric.
- [ ] Every milestone has a runnable gate and lists the docs it updates.
- [ ] Every "filled in at M#" note in the docs names a milestone that lists that doc.
- [ ] `docs/how-it-works/` agrees with `docs/PRD.md` on the grammar, the rules and the
      error codes.
- [ ] The plan contains nothing that the PRD and the Step 0 answers do not need.
- [ ] `CLAUDE.md` includes the commit-and-push rules and the no-co-author rule.
- [ ] `git log` shows no `Co-Authored-By` or Claude attribution in any of your commits.

Fix anything that fails, then commit and push the fixes. Finish with a short summary:
the main PRD changes, the milestone list with rough effort, the docs created, the
commits pushed (or any push failure), and any assumptions the user should double-check.
