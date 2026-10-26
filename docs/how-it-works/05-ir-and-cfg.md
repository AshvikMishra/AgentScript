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
if any), `used_vars(instr)` and `operands(instr)` (what it reads), `count_instructions(cfg)` and
`count_calls(cfg)` (for the optimizer's before/after numbers).

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

`if (c) { A } else { B }` (schematic; label numbers are assigned in creation order):

```
        <code for c, giving operand c>
        if c goto Lthen else Lelse        ; without an else block: if c goto Lthen else Lend
Lthen:
        <code for A>
        goto Lend
Lelse:                                    ; only when there is an else block
        <code for B>
        goto Lend
Lend:
```

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
deterministic, which keeps the golden test files stable.

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
| `blocks` keeps layout order. | Code generation lays out blocks in this order and can drop a `Jump` to the next block. |

`cfg.py` also provides the graph algorithms the later stages share: `reachable(cfg)` (labels
reachable from `entry`), `dominators(cfg)` (the simple iterative algorithm, used by the approval
analysis, see [07](07-approval-analysis.md)), and the printers `format_cfg`, `cfg_to_dict` and
`cfg_to_mermaid` (the CFG tab draws the Mermaid graph).

## 4. Worked example

> Filled in at M2: paste the real IR listing printed by `.venv/bin/python -m agentscript compile examples/valid_report.as --phase ir` and the CFG printed by `.venv/bin/python -m agentscript compile examples/valid_report.as --phase cfg`, and point out where `clean = call sanitize(...)` writes directly into `clean`, the `Branch` on the `confirm` result, and the guard block that is its true successor.

## 5. Errors this phase catches

> Filled in at M2: state that IR generation and CFG construction report no user error codes (E101 to E306 are all caught by stages 1 to 3, and `lower()` assumes a valid AST); list any internal assertion that `agentscript/irgen.py` or `agentscript/cfg.py` raises and the test in `tests/test_irgen.py` or `tests/test_cfg.py` that covers it.

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

> Filled in at M2: list `agentscript/irgen.py` (`lower(agent)` and its expression, statement and renaming helpers), `agentscript/cfg.py` (`build_cfg`, `reachable`, `dominators`, `format_cfg`, `cfg_to_dict`, `cfg_to_mermaid`), the data structures in `agentscript/ir.py`, and the tests in `tests/test_irgen.py` and `tests/test_cfg.py`.
