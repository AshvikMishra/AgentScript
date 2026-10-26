# AgentScript documentation

AgentScript is a tiny language and compiler for AI agent programs, built for a compiler lab
course. Unsafe agent programs fail to compile: the compiler proves that untrusted data never
reaches a privileged tool without `sanitize`, and that no irreversible tool runs without a
human `confirm`.

**Source of truth:** `PRD.md` is the corrected specification. When the code or any other
document disagrees with it, the PRD wins. `PRD-Original.md` is kept unchanged, only for
reference; every difference is listed in the final "Changes from the original"
section of `PRD.md`.

## Documents

| Document | What it is |
| --- | --- |
| [PRD-Original.md](PRD-Original.md) | The original PRD, unchanged; kept for reference only |
| [PRD.md](PRD.md) | The corrected PRD: requirements, grammar, semantics, error taxonomy, and a table of every change from the original |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | The build plan: data structures, milestones M1 to M7 with steps, tests, gates and the docs each milestone fills in |
| [how-it-works/00-overview.md](how-it-works/00-overview.md) | The problem, the two safety guarantees, and the whole pipeline in one diagram |
| [how-it-works/01-language.md](how-it-works/01-language.md) | Syntax, types, the built-in tools and their annotations, the example program line by line |
| [how-it-works/02-lexer.md](how-it-works/02-lexer.md) | Lexical analysis: tokens, positions, E101 and E102 |
| [how-it-works/03-parser.md](how-it-works/03-parser.md) | Grammar, recursive descent, precedence, the AST, E201 |
| [how-it-works/04-semantic-analysis.md](how-it-works/04-semantic-analysis.md) | Symbol table and scopes, type checking, permission and budget checks (E301 to E306, W306) |
| [how-it-works/05-ir-and-cfg.md](how-it-works/05-ir-and-cfg.md) | Three-address code, basic blocks, the control flow graph |
| [how-it-works/06-taint-analysis.md](how-it-works/06-taint-analysis.md) | Headline feature 1: forward data-flow taint analysis (E401) |
| [how-it-works/07-approval-analysis.md](how-it-works/07-approval-analysis.md) | Headline feature 2: dominators and the approval rule (E501, E502) |
| [how-it-works/08-optimizer.md](how-it-works/08-optimizer.md) | Constant folding, dead code elimination, duplicate tool-call elimination |
| [how-it-works/09-codegen-and-vm.md](how-it-works/09-codegen-and-vm.md) | Bytecode, the stack VM, the tool registry, runtime guards (E601 to E604) |
| [how-it-works/10-editor-and-api.md](how-it-works/10-editor-and-api.md) | The web editor, the API, and how a Compile click flows through the system |
| [how-it-works/11-parallel-scheduling.md](how-it-works/11-parallel-scheduling.md) | Optional milestone M7: dependency graph and parallel rounds of tool calls |
| [presentation/demo-script.md](presentation/demo-script.md) | The live demo, step by step: what to open, click, show and say, plus a CLI fallback |
| [presentation/viva-notes.md](presentation/viva-notes.md) | Likely viva questions with prepared answers, and related work |
| [prompts/](prompts/) | Prompts used to drive the agent sessions that produced these docs; do not edit |

Outside `docs/`: `CLAUDE.md` (instructions for coding agents), `examples/` (demo programs)
and `examples/manifest.json` (the expected error code, line and column of every example,
used by the tests, the editor's example picker and these docs).

## Reading order

For someone new to the project (an examiner or a classmate):

1. `how-it-works/00-overview.md`: what the project is and why.
2. `how-it-works/01-language.md`: the language, with the example program.
3. `how-it-works/06-taint-analysis.md` and `07-approval-analysis.md`: the two headline
   features.
4. `how-it-works/02` to `05`, then `08` to `11`, in number order, for the rest of the
   pipeline.
5. `presentation/demo-script.md`, to see it run.

For someone implementing or changing the code:

1. `../CLAUDE.md`, then this file.
2. `PRD.md` in full, especially the Grammar and Semantics sections.
3. `IMPLEMENTATION_PLAN.md`, then the `how-it-works/` files for the milestone at hand.

## Status of the docs

Sections that need real compiler output are marked with a note of the form
`> Filled in at M<n>: <what to paste, from which command>.` Each note is replaced with
output pasted from a real run once milestone M<n> passes its gate, and the note is removed.
Compiler output in these docs is never written by hand.
