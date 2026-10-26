# 08. Optimizer

## 1. What this phase does

| | |
| --- | --- |
| Input | One task's CFG of the unoptimized IR, **after** the semantic, taint and approval checks have passed. |
| Output | A new, smaller CFG and an `OptReport`: instruction count (non-label) and tool-call count before and after, plus a list of the changes made. `optimize(cfg) -> tuple[CFG, OptReport]` works on a deep copy and never mutates its input. |
| Place in the pipeline | Stage 7 of 10, one of the six classic phases. Its output goes to the scheduler (stage 8, M7) and then to code generation (stage 9). The Optimized IR tab shows the result and the before/after counts. |
| Requirements | F8 (constant folding, dead code elimination, duplicate tool-call elimination); success metric "duplicate tool call removed, call count shown before and after". |

The optimizer makes the program cheaper without changing what it does: fewer instructions, and,
for an agent, the thing that actually costs money and time, fewer tool calls.

## 2. Key data structures

| Structure | Type | Purpose |
| --- | --- | --- |
| `CFG`, `BasicBlock`, IR instructions | from `agentscript/ir.py` | Rewritten in place on the copy. `Const` and `Var` operands make "is this a constant?" a type test. |
| Local environment | `dict[str, Operand]` per block, reset at each block entry | What a variable is known to equal at this point of the block: a `Const` (constant propagation) or another `Var` (copy propagation). |
| Use set | `set[str]` over the whole task | Every variable read by any instruction (`used_vars()`); drives dead-assignment elimination. |
| Last call | the most recent `Call` seen in the current block | Drives duplicate tool-call elimination. |
| `OptReport` | `before {instructions, calls}`, `after {instructions, calls}`, `changes`, `iterations` | Counted with `count_instructions()` and `count_calls()` from `ir.py`. Each change is one line of text naming the source line and what was rewritten. `iterations` counts the rounds of the four passes, including the last one that changed nothing. `to_dict()` feeds the `stats` field of the `/compile` response. |
| `TOOLS[tool].mergeable` | from `agentscript/tools.py` | Set for `web_search`, `read_file`, `llm`, `sanitize`; never for `send_email`, `delete_file`, `confirm`. |

## 3. Algorithm

**In plain words.** Four small passes run in a loop until a whole round changes nothing:

1. **Constant folding, local propagation and branch folding.** Inside each block, replace a
   variable by the constant or variable it is known to equal; compute `BinOp`s whose operands are
   both constants; turn a `Branch` on a constant into a `Jump`.
2. **Unreachable-block elimination.** Delete blocks that can no longer be reached from `entry`.
3. **Dead-assignment elimination.** Delete `Assign` and `BinOp` instructions whose destination is
   never read anywhere in the task. Never delete a `Call` or an `Index`.
4. **Duplicate tool-call elimination.** In one block, a `Call` to a mergeable tool with the same
   arguments as the immediately preceding `Call` of the same tool (no other `Call` between them,
   and neither the earlier result nor any argument variable redefined in between) becomes
   `Assign dst = <earlier dst>`.

Each pass enables the others: folding `if (debug)` to a `Jump` makes the debug block unreachable
(pass 2), which removes the last read of `debug` (pass 3); merging a call produces a copy that pass
1 can propagate in the next round.

**Pass 1: fold and propagate (per block).**

```
fold_block(block):
    env = {}                                        # var -> Const or Var, this block only
    for instr in block.instrs:
        replace every Var operand x of instr by env[x] if x in env
        if instr is BinOp and both operands are Const:
            instr = Assign(instr.dst, Const(evaluate(op, left, right)))   # + - * on ints, + on strings,
                                                                          # comparisons -> bool
        if instr defines d:
            drop env[d] and every env entry whose value is Var(d)         # d is overwritten
            if instr is Assign: env[d] = instr.src
        if instr is Branch and instr.cond is Const:
            target = if_true if cond.value else if_false
            instr = Jump(target); update succs and preds
```

Folding is exact because the VM uses the same Python `int`, `str` and `bool` operations, and the
type checker has already guaranteed the operand types. There is no division, so folding can never
raise.

**Pass 2: unreachable blocks.** `R = reachable(cfg)`; delete every block not in `R` and remove it
from the `preds` of its successors. This removes branches folded away in pass 1 and the `U` blocks
that `build_cfg` creates for code after a `return`.

**Pass 3: dead assignments.**

```
used = { v for every instr in every block for v in used_vars(instr) }
delete every Assign or BinOp whose dst is not in used
```

**Pass 4: duplicate calls (per block).**

```
last, redefined = None, {}
for instr in block.instrs:
    if instr is Call:
        if last is not None and TOOLS[instr.tool].mergeable and instr.tool == last.tool
                and instr.args == last.args            # same Const values (and types) / same Var names
                and last.dst not in last.args
                and not ({last.dst} | vars(last.args)) & redefined:
            replace instr by Assign(instr.dst, last.dst); redefined.add(instr.dst)
        else:
            last, redefined = instr, {}                # any other call resets the window
    else:
        redefined |= defined_vars(instr)
```

Comparing operands by name is sound because the `redefined` set rejects a merge when an argument
variable or the earlier result is written between the two calls, so two reads of the same name
read the same value. (Only the loop counters have more than one definition, so in practice the
check matters for hand-built IR and loop bodies.) Constants are compared by type as well as value,
so `true` and `1` are never treated as the same argument.

**Fixpoint loop and report.**

```
optimize(cfg):
    new = deepcopy(cfg)
    before = (count_instructions(new), count_calls(new))
    repeat
        changed = fold(new) | drop_unreachable(new) | drop_dead(new) | merge_calls(new)
    until not changed
    after = (count_instructions(new), count_calls(new))
    return new, OptReport(before, after, changes)
```

Every pass only deletes instructions or blocks, or replaces an instruction by a simpler one
(`BinOp` to `Assign`, `Branch` to `Jump`, `Call` to `Assign`), so the loop terminates.

**The demo, by hand (illustrative; the real output is pasted in section 4).** In
`examples/optimize_demo.as`:

| Source | What happens |
| --- | --- |
| `let pages = 2 * 3;` (line 6) | folded to `pages = 6`; `pages` is never read, so it is deleted |
| `let first = web_search(topic);` (line 7) | kept |
| `let again = web_search(topic);` (line 8) | same tool, same argument, no call in between: becomes `again = first` |
| `let debug = false;` (line 9) and `if (debug)` (line 10) | `debug` propagates into the branch, the branch becomes a jump to the code after the `if`; `debug` is then unused and deleted |
| `return llm("debug");` (line 11) | its block is unreachable and is deleted, with its call |
| `return llm("Compare: " + ...);` (line 13) | kept |

Tool calls go from **4 to 2**: one `web_search` is merged and the debug `llm` is removed.

## 4. Worked example

**`examples/optimize_demo.as`, before.** The unoptimized IR from
`.venv/bin/python -m agentscript compile examples/optimize_demo.as --phase ir`:

```
task research(topic: string) -> string
      pages = 2 * 3                            ; line 6
      first = call web_search(topic)           ; line 7
      again = call web_search(topic)           ; line 8
      debug = false                            ; line 9
      if debug goto L1 else L2                 ; line 10
  L1:
      t1 = call llm("debug")                   ; line 11
      return t1                                ; line 11
  L2:
      t2 = first[1]                            ; line 13
      t3 = "Compare: " + t2                    ; line 13
      t4 = t3 + " / "                          ; line 13
      t5 = again[2]                            ; line 13
      t6 = t4 + t5                             ; line 13
      t7 = call llm(t6)                        ; line 13
      return t7                                ; line 13
```

**After.** `.venv/bin/python -m agentscript compile examples/optimize_demo.as --phase optimized_ir`
prints the optimized CFG, the counts and every change, in the order the passes made them:

```
task research(topic: string) -> string
  entry:
      preds: -
      succs: L2
      first = call web_search(topic)           ; line 7
      again = first                            ; line 8
      goto L2                                  ; line 10
  L2:
      preds: entry
      succs: -
      t2 = first[1]                            ; line 13
      t3 = "Compare: " + t2                    ; line 13
      t4 = t3 + " / "                          ; line 13
      t5 = again[2]                            ; line 13
      t6 = t4 + t5                             ; line 13
      t7 = call llm(t6)                        ; line 13
      return t7                                ; line 13
instructions 14 -> 10, tool calls 4 -> 2
changes:
  line 6: folded pages = 2 * 3 -> 6
  line 10: replaced debug with false
  line 10: branch on false -> goto L2
  removed unreachable block L1 (line 11)
  line 6: removed dead assignment pages = 6
  line 9: removed dead assignment debug = false
  line 8: duplicate call web_search(topic) replaced by copy of first (line 7)
```

Tool calls go **4 -> 2** and instructions 14 -> 10, exactly as predicted in section 3. Note that
`again = first` is kept: `again` is still read by `t5 = again[2]`, and the copy is not propagated
into `L2` because propagation is block-local. The same numbers reach the `stats` field of
`.venv/bin/python -m agentscript compile examples/optimize_demo.as --json`:

```
{
  "before": {
    "instructions": 14,
    "calls": 4
  },
  "after": {
    "instructions": 10,
    "calls": 2
  },
  "rounds_before": 2,
  "rounds_after": 2
}
```

**`examples/valid_report.as` (the PRD example).** Nothing to do: every value is used, no branch
condition is a constant and no two calls repeat. The output of
`.venv/bin/python -m agentscript compile examples/valid_report.as --phase optimized_ir`:

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
instructions 10 -> 10, tool calls 5 -> 5
changes: none
```

## 5. Errors this phase catches

None. The optimizer emits no diagnostics of its own: `agentscript/optimizer.py` never creates a
`Diagnostic` (the only error code it mentions is E603, in the comment explaining why an `Index` is
never removed). `agentscript/pipeline.py` calls `optimize()` only after the semantic, taint and
approval phases have finished without errors, so every program it sees is already valid; the
tests in `tests/test_optimizer.py` build their input the same way (`cfgs_of()` runs `analyze()`
first, "the optimizer only ever sees semantically valid programs"). `compile
examples/optimize_demo.as --json` reports `"diagnostics": []`.

What the optimizer must do instead is *not hide* errors that happen later. Two tests pin that
down: `test_index_never_removed` (an unused `xs[5]` stays, so a run can still fail with E603) and
`test_unused_call_never_removed` (an unused `llm(...)` result still counts against the budget, so
E601 at runtime is unchanged).

## 6. Design decisions and limitations

**Why it works this way**

| Decision | Why |
| --- | --- |
| Runs only after the safety checks pass, on a deep copy | A guarantee never depends on what the optimizer removes. The editor can show the original IR next to the optimized one because the input is never mutated. |
| Never remove a `Call`, even if its result is unused | A tool call is the agent's observable behaviour. `send_email(to, body);` as a statement puts its result in a temp that nobody reads; deleting it as a "dead assignment" would silently drop the email. The same holds for a `confirm` the human must see, and every call is part of the run's call log and budget. |
| Never remove an `Index`, even if unused | `xs[9]` on a three-element list fails with E603 at runtime. Removing it would turn a failing run into a succeeding one, which changes behaviour. |
| Duplicate-call merging only for `mergeable` tools | `web_search`, `read_file`, `llm` and `sanitize` are treated as read-only: asking twice gives the same answer. `send_email` twice is two emails, `delete_file` twice is two deletions, and `confirm` twice is two questions a human may answer differently; merging any of them would change what the agent does or which answer guards a call. |
| Only the immediately preceding call, in the same block | An intervening call may change the world (`delete_file` changes what `read_file` returns; a `confirm` may stop the run). Requiring no call in between makes the rule obviously safe without modelling effects. Within one block both calls run whenever either does; across blocks it would need an available-expressions analysis. |
| Local (per-block) propagation | Inside a block instructions run in order, so it is always safe. Global propagation would need a reaching-definitions analysis (loop counters have two definitions). In the demos the constants that matter are in the same block as their use. |
| Fixpoint loop | Passes enable each other; looping until nothing changes is simpler than ordering them cleverly. |

**Why the safety results still hold after optimization.** The checks are not re-run, so every
rewrite must preserve them:

| Guarantee | Why the rewrites preserve it |
| --- | --- |
| Budget (F6) | Calls are only removed or merged, never added. The static worst-path count was an upper bound for the unoptimized program, so it still bounds the optimized one. |
| Taint (T1–T4) | No new data flow is created. A folded constant is trusted; a merged call `again = first` carries the label of an identical call with identical arguments; deleted instructions were unread. |
| Approval (A1–A3) | No call moves to another block, and only unreachable blocks and impossible edges are deleted. Removing paths can only make a guard dominate more, never less. A `confirm` result is never a constant, so a guard branch is never folded. |

**Limitations**

| Limitation | Consequence |
| --- | --- |
| Propagation stops at block boundaries | `let n = 3;` used inside a later `if` block is not replaced by `3`. |
| No block merging or jump threading | A folded branch may leave a `Jump` to the next block; codegen drops such jumps anyway (see `09-codegen-and-vm.md`). |
| Merging assumes mergeable tools are deterministic within a run | True for the mocks; a live `web_search` could return different results a second later. The rule is "same question, same answer", stated as an assumption. |
| Only adjacent duplicate calls | `web_search(a); llm(x); web_search(a);` keeps both searches. |
| No loop optimizations | `repeat` bodies are not unrolled or hoisted. |

## 7. Where it lives in the code

| File | What is there |
| --- | --- |
| `agentscript/optimizer.py` | `optimize(cfg) -> tuple[CFG, OptReport]`: deep copy, then the fixpoint loop over the four passes. `OptReport` (`before`, `after`, `changes`, `iterations`, `to_dict()`). |
| | Pass 1: `_fold_and_propagate` / `_fold_block`, with `_substitute` (operand replacement), `_kill` (forget a redefined variable and its copies) and `fold_binop(op, left, right)` (the VM's result for well-typed constants, or `None`). |
| | Pass 2: `_remove_unreachable` (uses `reachable` and `link_blocks` from `cfg.py`). Pass 3: `_remove_dead`. Pass 4: `_merge_calls` / `_merge_block`, with `_same_call` and `_same_operand` (keeps `true` and `1` apart). |
| | `optimized_artifact(results)`: the `optimized_ir` phase artifact (text above, plus per-task CFG, Mermaid graph and report, and totals). |
| `agentscript/pipeline.py` | `_Driver.compile` runs `optimize(c)` for each task's CFG right after taint and approval, stores `res.optimized`, builds the `optimized_ir` phase, and fills `res.stats` with `before` / `after` (and `rounds_before` / `rounds_after`, which the scheduler overwrites when M7 is on). The optimized CFGs go to the scheduler, or straight to codegen with `--no-parallel`. |
| `agentscript/ir.py` | `count_instructions`, `count_calls`, `used_vars`, `defined_vars`, `format_instr`, `format_operand`. |
| `agentscript/tools.py` | `TOOLS[...].mergeable`. |
| `tests/test_optimizer.py` | The demo (`test_optimize_demo_calls_4_to_2`, `test_optimize_demo_changes_list`), `test_valid_report_keeps_all_five_calls`, `test_input_cfg_not_mutated`, idempotence over every valid example, merging rules (non-mergeable tools, different arguments, different blocks, redefined arguments or destination), `fold_binop` against the VM, branch folding, block-local propagation, loops, and the artifact. |
