# 05. Intermediate representation: three-address code, basic blocks and the CFG

## 1. What this phase does

| | |
| --- | --- |
| Input | The type-annotated AST, after semantic analysis has passed. |
| Output | Per task: a linear three-address-code listing (`IRFunction`), and the same code split into basic blocks connected by a control flow graph (`CFG`). Two artifacts: `ir` (the listing) for the IR tab and `cfg` (blocks and edges, plus a Mermaid graph) for the CFG tab. |
| Place in the pipeline | Stage 4 of 10, the fourth classic phase and the start of the middle end. The CFG is what the taint analysis (stage 5) and the approval analysis (stage 6) run on, **unoptimized**; the optimizer (stage 7) then works on a copy of it. |
| Errors | None of its own. It assumes a semantically valid AST. |

The AST is good for checking what a program means, but bad for asking "where can this value
flow?" or "which paths reach this call?". This phase flattens the tree into simple instructions
(one operation each) and makes every jump explicit, so the analyses that follow can be ordinary
data-flow and control-flow algorithms.

## 2. Key data structures

All of them are in `agentscript/ir.py`.

**Operands.** `Const(value)` holds an `int`, `str` or `bool`; `Var(name)` names a user variable,
a parameter, a loop counter or a temporary (`t1`, `t2`, ...).

**Instructions.** Each has `line` and `col`: the source position of the construct it came from,
so that later phases can report errors in source terms.

| Instruction | Text form | Meaning |
| --- | --- | --- |
| `Assign` | `x = y` | copy an operand |
| `BinOp` | `x = a + b` | one binary operator (`+ - * == != < <= > >=`) |
| `Index` | `x = xs[i]` | list indexing (may fail at runtime with E603) |
| `Call` | `x = call tool(a, b)` | one tool call; its result always goes into a variable |
| `Jump` | `goto L1` | unconditional jump (terminator) |
| `Branch` | `if c goto L1 else L2` | two-way branch on a `bool` operand (terminator) |
| `Return` | `return x` | end the task (terminator) |
| `Label` | `L1:` | a jump target; only in the linear listing, never inside a block |
| `ParallelCalls` | `round { x = call ...; y = call ... }` | M7 only: a group of independent calls run as one round ([11](11-parallel-scheduling.md)) |

Every operand of every instruction is a `Const` or a `Var`: no instruction contains a nested
expression. That is what makes it "three-address": at most two operands and one destination.

**IRFunction.** One per task: `name`, `params` (name and type), `return_type`, and `instrs`, the
linear listing including `Label`s.

**BasicBlock.** `label`, `instrs` (no `Label`s; the last instruction is the block's only
terminator), `succs` and `preds` (labels of successor and predecessor blocks). For a `Branch`,
`succs` is `[if_true, if_false]` in that order, which the approval analysis relies on: the guard
block is the **true** successor.

**CFG.** `name`, `params`, `return_type`, `blocks` (a dictionary from label to block, in layout
order), and `entry` (always `"entry"`, the first block).

**Helpers** used by every later phase: `defined_var(instr)` (the variable an instruction writes,
if any) and `defined_vars(instr)` (the same as a list, which also covers `ParallelCalls`),
`used_vars(instr)` and `operands(instr)` (what it reads), `format_instr` and `format_function`
(the text forms), `count_instructions(cfg)` and `count_calls(cfg)` (for the optimizer's
before/after numbers). `TERMINATORS` is the tuple `(Jump, Branch, Return)`.

## 3. Algorithm

### 3.1 Lowering the AST to three-address code

In plain words: walk each task's statements in order and emit instructions into one list.
Every expression is lowered bottom-up and returns the operand that holds its value: a literal
becomes a `Const`, a name becomes a `Var`, and every operator, index or call writes its result
into a new temporary. Control flow (`if`, `repeat`) becomes labels, branches and jumps.

```
lower_expr(e) -> Operand:
    IntLit / StrLit / BoolLit:  return Const(e.value)
    Name:                       return Var(ir_name(e.name))        # after renaming, see 3.2
    Binary:                     l = lower_expr(e.left); r = lower_expr(e.right)
                                t = new_temp(); emit BinOp(t, e.op, l, r); return t
    Index:                      b = lower_expr(e.base); i = lower_expr(e.index)
                                t = new_temp(); emit Index(t, b, i); return t
    Call:                       args = [lower_expr(a) for a in e.args]
                                t = new_temp(); emit Call(t, e.tool, args); return t
```

The statement rules:

| Statement | Emitted code |
| --- | --- |
| `let x = <call, binary or index>` | the instruction writes **directly into `x`** (no extra temporary) |
| `let x = <name or literal>` | `x = <operand>` (`Assign`) |
| `return e` | the code for `e`, then `return <operand>` |
| `e;` (expression statement) | the code for `e`; a call's result goes into a fresh temporary that nothing reads |

`if (c) { A } else { B }` (schematic; the labels `Lthen`, `Lelse` (only with an else block)
and `Lend` are numbered in that order, before the code for `c` is emitted):

```
        <code for c, giving operand c>
        if c goto Lthen else Lelse        ; without an else block: if c goto Lthen else Lend
Lthen:
        <code for A>
        goto Lend                         ; left out when A ends with a return
Lelse:                                    ; only when there is an else block
        <code for B>
        goto Lend                         ; left out when B ends with a return
Lend:                                     ; only when some edge jumps to it
```

So an `if`/`else` whose branches both return has no `Lend` label at all, and an `if` without
`else` always has one (its false edge goes there).

`repeat N { A }` (schematic; `tK`, `tN`, `tC` stand for fresh temporaries):

```
        tK = 0                            ; the loop counter
        tN = N                            ; the count, evaluated once on entry
        goto Lhead
Lhead:
        tC = tK < tN
        if tC goto Lbody else Lexit
Lbody:
        <code for A>
        tK = tK + 1
        goto Lhead
Lexit:
```

A count of 0 or less fails the first test, so the body runs zero times, as the language
requires. The loop counter is the only kind of IR variable written by two instructions.

**Numbering.** Temporaries are `t1, t2, ...` and labels `L1, L2, ...`, both numbered per task
in the order they are created, so every task starts again at `t1` and `L1`. The numbering is
deterministic, which keeps the golden test files stable. A user variable or parameter may be
named like a temporary (`let t2 = ...`); such names are reserved for the task and the temporary
counter skips them, so a temporary never overwrites a user variable.

**The `then` block always gets its own label**, even though it directly follows the `Branch`.
A `Branch` needs a named target for its true edge, and the approval analysis defines a guard
block as "the true successor of a branch on a confirm value". With its own label, the `then`
code is guaranteed to start a basic block of its own, so that block is exactly the code the
human approved.

### 3.2 Renaming reused variable names

The source language forbids shadowing, but sibling blocks may reuse a name:

```
if (a) { let ok = confirm("first?");  ... }
else   { let ok = confirm("second?"); ... }
```

The IR has one flat namespace per task (the VM also keeps one set of variables per task), so
the IR generator does its own scoping while lowering: the first declaration of a name in a task
keeps the name, and each later declaration of the same name in the same task gets `name.2`,
`name.3`, and so on. Uses are resolved through the generator's scope chain to the right IR name.
In the example above, the second `ok` and its uses become `ok.2`. The `.` cannot appear in a
source identifier, so a renamed variable can never clash with a user's name.

Result: every IR variable except the loop counters has exactly one static definition. The
analyses rely on this: the taint state maps a variable name to one label, the approval
analysis recognises a "confirm value" as a variable defined only by `confirm(...)` or by a copy
of one, and dead-assignment elimination asks whether a destination is used anywhere in the task.

### 3.3 Building basic blocks and the CFG

In plain words: a basic block is a maximal run of instructions that is always entered at the
top and left at the bottom. Cut the listing before every label and after every jump, branch or
return; then connect each block to the blocks its terminator can jump to.

```
build_cfg(fn):
    blocks = []; current = new block "entry"
    for instr in fn.instrs:
        if instr is Label:
            if current has no terminator: append Jump(instr.name) to current       # fall-through
            close current
            current = new block instr.name
        else:
            if current already ends in a terminator:          # code after goto/branch/return
                close current; current = new block "U<k>"     # generated label, unreachable
            append instr to current
    if current has no terminator: append Jump(current.label)   # falls off the end: self-loop
    close current
    for each block b:
        b.succs = [target] for Jump; [if_true, if_false] for Branch; [] for Return
        for s in b.succs: blocks[s].preds.append(b.label)
```

The resulting invariants, which every later phase relies on:

| Invariant | Why it matters |
| --- | --- |
| The first block is `entry`. | Data-flow and dominator analyses start there. |
| Every block ends with exactly one terminator; no `Label` appears inside a block. | Successors can be read directly from the last instruction. |
| A block that would fall through gets an explicit `Jump`. | Block order no longer matters for meaning, so the optimizer may delete blocks and codegen may lay them out freely. |
| Code after a terminator with no label gets a generated label `U1, U2, ...`. | Statements after a `return` are legal; they form blocks with no predecessors, which the optimizer's unreachable-block elimination removes. |
| A last block that would fall off the end of the listing gets `goto <itself>`. | Only possible in unreachable code of a valid program (a task always returns), but it keeps "exactly one terminator" true for every block. |
| `preds` list each predecessor once, in layout order. | A `Branch` with two identical targets still gives one edge in `preds`; dominators and printing stay deterministic. |
| `blocks` keeps layout order. | Code generation lays out blocks in this order and can drop a `Jump` to the next block. |

`cfg.py` also provides the graph algorithms the later stages share: `successors(block)` and
`link_blocks(cfg)` (recompute `succs` and `preds` after the optimizer changes blocks),
`reachable(cfg)` (labels reachable from `entry`), `dominators(cfg)` (the simple iterative
algorithm over the reachable blocks, used by the approval analysis, see
[07](07-approval-analysis.md)) and `immediate_dominators(cfg)`, and the printers `format_cfg`,
`cfg_to_dict` and `cfg_to_mermaid` (the CFG tab draws the Mermaid graph; `format_cfg` and
Mermaid mark blocks that are not reachable as `(unreachable)`).

## 4. Worked example

The input is `examples/valid_report.as` (task `report`, see
[04](04-semantic-analysis.md#4-worked-example)).

**The linear IR.** `.venv/bin/python -m agentscript compile examples/valid_report.as --phase ir`:

```
task report(topic: string) -> bool
      raw = call web_search(topic)             ; line 6
      t1 = raw[0]                              ; line 7
      clean = call sanitize(t1)                ; line 7
      t2 = "Summarize: " + clean               ; line 8
      summary = call llm(t2)                   ; line 8
      t3 = call confirm("Send report?")        ; line 9
      if t3 goto L1 else L2                    ; line 9
  L1:
      t4 = call send_email("me@example.com", summary) ; line 10
      return t4                                ; line 10
  L2:
      return false                             ; line 12
```

What to look at:

- `let raw = web_search(topic);` and `let clean = sanitize(raw[0]);` are `let`s of calls, so the
  `Call` writes **directly into `raw` and `clean`**: there is no `t = call ...; clean = t` pair.
  Only the nested expressions get temporaries: `t1 = raw[0]` (the index inside the argument) and
  `t2 = "Summarize: " + clean`.
- The `if` condition `confirm("Send report?")` is not a `let`, so its result goes into the
  temporary `t3`, and the `Branch` tests it: `if t3 goto L1 else L2`.
- The labels were created in the order `then` (`L1`), `end` (`L2`); there is no `else` block, so
  the false edge goes straight to `L2`. The `then` block ends with `return t4`, so no `goto L2`
  follows it.
- Every instruction keeps its source line (`; line 7` and so on).

**The CFG.** `.venv/bin/python -m agentscript compile examples/valid_report.as --phase cfg`:

```
task report(topic: string) -> bool
  entry:
      preds: -
      succs: L1, L2
      raw = call web_search(topic)             ; line 6
      t1 = raw[0]                              ; line 7
      clean = call sanitize(t1)                ; line 7
      t2 = "Summarize: " + clean               ; line 8
      summary = call llm(t2)                   ; line 8
      t3 = call confirm("Send report?")        ; line 9
      if t3 goto L1 else L2                    ; line 9
  L1:
      preds: entry
      succs: -
      t4 = call send_email("me@example.com", summary) ; line 10
      return t4                                ; line 10
  L2:
      preds: entry
      succs: -
      return false                             ; line 12
```

Three blocks: the listing is cut before `L1:` and before `L2:`. `entry` ends with the `Branch`
on the `confirm` result `t3`, so its `succs` are `L1, L2` in the order `[if_true, if_false]`.
**`L1` is the guard block**: it is the true successor of a branch on a confirm value, and it
contains exactly the code under `if (confirm(...)) { ... }`, the `send_email` call. That is why
`then` blocks always get their own label (3.1). `L1` and `L2` end in `return`, so they have no
successors.

The CFG artifact (`--json`, `phases.cfg.data.tasks[0]`) also carries the Mermaid graph the CFG
tab draws, with `T` and `F` on the branch edges, and the dominator sets:

```
flowchart TD
  B0["entry<br/>raw = call web_search(topic)<br/>t1 = raw[0]<br/>clean = call sanitize(t1)<br/>t2 = #quot;Summarize: #quot; + clean<br/>summary = call llm(t2)<br/>t3 = call confirm(#quot;Send report?#quot;)<br/>if t3 goto L1 else L2"]
  B1["L1<br/>t4 = call send_email(#quot;me@example.com#quot;, summary)<br/>return t4"]
  B2["L2<br/>return false"]
  B0 -->|T| B1
  B0 -->|F| B2
```

```
{'entry': ['entry'], 'L1': ['L1', 'entry'], 'L2': ['L2', 'entry']}
```

A loop for comparison: `runtime_budget.as` (`repeat times { let r = web_search(topic); }`),
from `.venv/bin/python -m agentscript compile examples/runtime_budget.as --phase ir`, shows the
`repeat` schematic of 3.1 with `t1` the counter, `t2` the count and `t3` the test:

```
task poll(topic: string, times: int) -> int
      t1 = 0                                   ; line 6
      t2 = times                               ; line 6
      goto L1                                  ; line 6
  L1:
      t3 = t1 < t2                             ; line 6
      if t3 goto L2 else L3                    ; line 6
  L2:
      r = call web_search(topic)               ; line 7
      t1 = t1 + 1                              ; line 6
      goto L1                                  ; line 6
  L3:
      return times                             ; line 9
```

In its CFG (`--phase cfg`) the back edge shows up as `L2` in the `preds` of the loop head:

```
  L1:
      preds: entry, L2
      succs: L2, L3
```

## 5. Errors this phase catches

None. IR generation and CFG construction report no user error codes: E101 to E306 are all
caught by stages 1 to 3, and `lower()` assumes a semantically valid AST (the pipeline only
calls it after `analyze()` has succeeded).

Internal checks that can fire only on an AST that skipped semantic analysis, or on a compiler
bug:

| Where | Raises | Covered by |
| --- | --- | --- |
| `irgen._TaskLowerer.resolve` | `KeyError("irgen: undeclared name ... (AST not semantically valid)")` | `tests/test_irgen.py::test_every_parseable_example_lowers` lowers the parsed (not checked) `sem_undeclared.as` and expects `KeyError`; `tests/test_cfg.py::_lowerable_examples` skips files that raise it. |
| `irgen._TaskLowerer.lower_stmt` / `lower_expr` | `TypeError("irgen: unknown statement/expression ...")` for an AST node type it does not know | no test (cannot happen with the parser's node types) |
| `ir.format_instr` | `TypeError("unknown instruction ...")` | no test |

`agentscript/cfg.py` raises nothing of its own. If any of these did happen inside the pipeline,
`pipeline.py` turns the exception into an internal `E000` diagnostic
(`internal compiler error: <type>: <message>`) instead of crashing the API.

## 6. Design decisions and limitations

| Decision | Why |
| --- | --- |
| Three-address code as the IR. | Each instruction does one thing and names its inputs and output, so a data-flow analysis has one simple transfer rule per instruction kind. Every tool call becomes exactly one `Call` instruction, which the budget, taint, approval, optimizer and scheduler stages can each find directly. |
| Analyses run on the IR, not the AST. | Taint must follow data through temporaries and across branches; approval must reason about paths and dominators. Both are standard on a CFG and awkward on a tree. |
| Every instruction keeps a source position. | Diagnostics from the taint and approval analyses (E401, E501, E502) and from the VM (E601, E603) must point at source lines, and the `path` in E401 is a chain of IR steps shown as source positions. |
| `let x = call ...` writes straight into `x`. | Fewer temporaries and copies, so the IR listing reads like the source and taint paths are shorter. |
| Per-task numbering of temporaries and labels. | Deterministic output for golden tests, and each task's listing stands on its own. |
| Renaming instead of full SSA. | Variables are immutable and cannot be shadowed, so renaming sibling reuses already gives one definition per variable (except loop counters). There are no reassignments that would need phi nodes at join points, because a variable declared inside a branch is not visible after it. |
| Explicit `Jump` on fall-through; one terminator per block. | Every edge is visible in the instructions, so no analysis has to remember "and the next block in layout order". |
| Unreachable code is kept in the CFG. | The IR shows exactly what the source says; removing dead code is the optimizer's job, and the safety analyses work on the unoptimized program on purpose. |
| The `then` block always starts with its own label. | The approval rule's guard block is then precisely the approved code. |

Limitations:

- No SSA form and no phi nodes; the loop counter is redefined on every iteration. This is fine
  for the analyses here (the counter is computed only from constants and the count, and no tool
  returns an `int`, so it is always trusted), but a more advanced optimizer would want SSA.
- Temporaries are never reused, so a long task produces many of them. The stack VM does not care.
- One CFG per task and no interprocedural edges, because tasks cannot call each other.
- The IR is untyped: types were checked on the AST and are not repeated on each instruction
  (the `IRFunction` keeps only the parameter and return types).

## 7. Where it lives in the code

| File | Main names |
| --- | --- |
| `agentscript/ir.py` | Operands `Const`, `Var` (`Operand = Const \| Var`); instructions `Instr`, `Assign`, `BinOp`, `Index`, `Call`, `Jump`, `Branch`, `Return`, `Label`, `ParallelCalls` (M7); `TERMINATORS`; containers `IRFunction`, `BasicBlock` (with the `terminator` property), `CFG`; helpers `defined_var`, `defined_vars`, `operands`, `used_vars`, `format_operand`, `format_instr`, `format_function`, `count_instructions`, `count_calls`. |
| `agentscript/irgen.py` | `lower(agent) -> list[IRFunction]` (one per task); `ir_artifact(fns)` (the IR tab `{text, data}`) and `instr_to_dict`; `_declared_names` (finds user names like `t3` to reserve); `_TaskLowerer`, one per task, with `lower`, `emit`, `new_temp`, `new_label`, the renaming helpers `declare` (gives `name`, `name.2`, ...) and `resolve` (scope chain lookup), `ends_with_return`, the statement lowering `lower_block`, `lower_stmt`, `lower_let`, `lower_if`, `lower_repeat`, and the expression lowering `lower_expr(expr, dst)`. |
| `agentscript/cfg.py` | `build_cfg(fn) -> CFG`; `successors`, `link_blocks`; `reachable`, `dominators`, `immediate_dominators`; printers `format_cfg`, `cfg_to_dict`, `cfg_to_mermaid` (with `_mermaid_escape`) and `cfg_artifact(cfgs)` (the CFG tab `{text, data}`, including Mermaid and dominator sets per task). |
| `agentscript/pipeline.py` | Calls `lower(res.agent)` for phase `ir` and `build_cfg` per function for phase `cfg`, right after `analyze()`. |

Tests:

- `tests/test_irgen.py`: exact listings of the examples (`test_valid_report_exact_listing`,
  `test_valid_report_columns`, `test_valid_report_operands`,
  `test_runtime_budget_repeat_variable`, `test_valid_cleanup_branches_on_let_variable`,
  `test_optimize_demo_listing`); the `if` shapes (`test_if_else_both_return_has_no_end_label`,
  `test_if_else_falls_through_to_end`, `test_if_without_else_and_then_returning`,
  `test_nested_ifs_label_numbering`, `test_nested_if_both_return_suppresses_outer_goto`, ...);
  loops (`test_repeat_literal`, `test_repeat_variable_count_and_nesting`); renaming and
  numbering (`test_sibling_scope_names_are_renamed`, `test_numbering_restarts_per_task`,
  `test_user_variable_named_like_a_temp_is_not_clobbered`); expressions and statements
  (`test_let_of_name_and_literal_emits_assign`, `test_precedence_and_left_associativity`,
  `test_code_after_return_is_kept`, ...); `test_ir_artifact_shape`,
  `test_lowering_is_deterministic` and `test_every_parseable_example_lowers`.
- `tests/test_cfg.py`: block splitting (`test_valid_report_blocks`, `test_repeat_loop_blocks`,
  `test_fallthrough_into_label_gets_explicit_jump`,
  `test_code_after_return_becomes_unreachable_u_block`, `test_trailing_open_block_gets_self_jump`,
  `test_branch_with_identical_targets_lists_pred_once`, `test_build_cfg_does_not_mutate_listing`,
  ...); dominators (`test_dominators_diamond`, `test_dominators_loop`,
  `test_dominators_nested_if`, `test_dominators_guard_block_of_valid_cleanup`,
  `test_dominators_skip_unreachable_blocks`, ...); printers (`test_format_cfg_valid_report`,
  `test_cfg_to_dict`, `test_mermaid_contains_every_block_and_branch_labels`,
  `test_mermaid_escapes_quotes_and_brackets`, `test_cfg_artifact_shape`, ...); and
  `test_every_example_builds_a_well_formed_cfg` over every lowerable example.
