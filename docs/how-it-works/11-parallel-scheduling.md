# 11. Parallel scheduling (M7, optional stretch)

## 1. What this phase does

| | |
| --- | --- |
| Input | One task's **optimized** CFG (output of `08-optimizer.md`). |
| Output | A scheduled CFG in which independent tool calls of a block are grouped into `ParallelCalls` instructions, plus a `ScheduleReport` with the rounds before (= number of calls) and after. `schedule(cfg) -> tuple[CFG, ScheduleReport]`. Shown in the Rounds tab. |
| Place in the pipeline | Stage 8 of 10, between the optimizer (stage 7) and codegen (stage 9). It runs when `compile_source(source, parallel=True)` (the default); codegen turns each `ParallelCalls` into one `CALL_PARALLEL`, which the VM executes concurrently. |
| Requirements | L1 (dependency graph, independent calls grouped into rounds), L2 (concurrent execution, rounds shown before and after), L3 (never reorder dependent calls or irreversible tools); success metric "3 independent calls run in 1 round". |

Tool calls are slow (network, model latency). Three searches that do not depend on each other
can run at the same time; this phase finds such calls and the VM runs them together.

## 2. Key data structures

| Structure | Type | Purpose |
| --- | --- | --- |
| Dependency graph | per block: nodes = the block's instructions except the terminator; edges `i -> j` (i before j in the block) when j must stay after i | The constraints a schedule must respect. |
| Data edges | `j` reads a variable `i` writes; `j` writes a variable `i` reads; both write the same variable | Def-use through variables (`defined_vars()`, `used_vars()` in `ir.py`). The last two kinds matter only for the loop counter `tK`, the one variable with two definitions. |
| Barrier edges | `i` and `j` are both calls and either tool is a barrier | A barrier tool (`ToolSpec.barrier`: `privileged`, `irreversible` or `approval`, i.e. `send_email`, `delete_file`, `confirm`) keeps its order relative to every other call in the block. |
| `ParallelCalls(calls)` | from `ir.py` | One round of k ≥ 2 independent calls; printed as `round { ... }`. |
| `CALL_PARALLEL [(tool, argc), ...]` | from `bytecode.py` | Pops all arguments of all calls in order, runs them concurrently, pushes the results in order. Stack effect Σ(1 − argc_i). |
| `ScheduleReport` | `rounds_before`, `rounds_after`, the rounds per block | `rounds_before` = number of calls; `rounds_after` = number of `Call` plus `ParallelCalls` instructions. Feeds `stats.rounds_before` / `stats.rounds_after` in `/compile`. |

## 3. Algorithm

**In plain words.** Work on one basic block at a time. Build the dependency graph. Then, as long
as instructions remain: first emit every non-call instruction that is ready (all its predecessors
in the graph already emitted), in original order, repeating until none is ready; then take every
call that is ready *now* and emit them together as one round. One ready call stays a plain `Call`;
two or more become a `ParallelCalls`. The terminator goes last. This is *list scheduling* (also
called topological layering): each round is one layer of the dependency graph, restricted to calls.

```
schedule_block(block):
    body, term = block.instrs[:-1], block.instrs[-1]
    deps = dependency_graph(body)                  # data edges + barrier edges
    done, out = set(), []
    while len(done) < len(body):
        progress = True
        while progress:                            # all ready non-calls, original order
            progress = False
            for ins in body:
                if ins not in done and ins is not Call and deps[ins] <= done:
                    out.append(ins); done.add(ins); progress = True
        ready = [c for c in body if c not in done and c is Call and deps[c] <= done]
        if len(ready) == 1: out.append(ready[0])
        if len(ready) >= 2: out.append(ParallelCalls(ready))     # original order
        done |= set(ready)
    out.append(term)
    block.instrs = out

dependency_graph(body):
    for j, b in enumerate(body):
        deps[b] = { a for a in body[:j]
                    if writes(a) & reads(b) or reads(a) & writes(b) or writes(a) & writes(b)
                    or (a is Call and b is Call and (TOOLS[a.tool].barrier or TOOLS[b.tool].barrier)) }
```

The `ready` list is computed once per round, before any of its calls is marked done, so two calls
in the same round never depend on each other. Every iteration emits at least one instruction (the
graph is acyclic because edges only point forward), so the loop terminates.

**Concurrent execution in the VM.** For `CALL_PARALLEL [(tool_1, n_1), ..., (tool_k, n_k)]`:

```
argv_k .. argv_1 = pop n_k, ..., n_1 values      # restore each call's argument order
for each call: if tool not in permits: raise E602 at that call
if calls_used + k > budget: raise E601 at the first call of the round that would exceed it
results = run registry.call(tool_i, argv_i) for all i concurrently (thread pool), wait for all
push results in order; log each call with the same round number, in program order
```

The permission and budget guards check the whole round before any call starts, so a round either
runs completely or not at all and the budget is never exceeded. (IMPLEMENTATION_PLAN.md M7 step 5:
check `calls_used + k <= budget`, E601 at the first call that would exceed.) A thread pool from the
standard library (`concurrent.futures`) is enough: the calls are I/O-bound. The log is written in
program order, not completion order, so runs stay deterministic.

**The demos, by hand (illustrative; the real schedule is pasted in section 4).**

| Program | Calls in order | Dependencies | Rounds before → after |
| --- | --- | --- | --- |
| `examples/parallel_demo.as` | `web_search(a)`, `web_search(b)`, `web_search(c)`, `llm(...)` | the three searches are independent; `llm` reads `ra[1]`, `rb[1]`, `rc[1]` | **4 → 2**: round 1 = the three searches, then the index and concatenation instructions, round 2 = `llm` |
| `examples/valid_report.as` | `web_search`, `sanitize`, `llm`, `confirm`, `send_email` | each call uses the previous result; `confirm` and `send_email` are barriers and sit in different blocks | **5 → 5**: nothing can run in parallel |

## 4. Worked example

> Filled in at M7: paste the schedule printed by `.venv/bin/python -m agentscript compile examples/parallel_demo.as --phase schedule` (rounds 4 -> 2) and by `.venv/bin/python -m agentscript compile examples/valid_report.as --phase schedule` (5 -> 5), and the call log of `.venv/bin/python -m agentscript run examples/parallel_demo.as --task scout --args '{"a": "rust", "b": "go", "c": "zig"}'` showing three calls in round 1.

## 5. Errors this phase catches

> Filled in at M7: state that the scheduler emits no diagnostics of its own and paste, from `tests/test_scheduler.py`, the test showing how a `CALL_PARALLEL` round meets the E601/E602 guards.

## 6. Design decisions and limitations

**Why it works this way: the L3 guarantee**

| Decision | Why |
| --- | --- |
| Only within one basic block | Every instruction of a block runs exactly when the block runs, so regrouping changes the *order* of calls, never *which* calls happen. Moving calls across blocks would be speculation: a call could run on a path where the program would not have made it, or leave a confirm guard block, breaking the approval guarantee. |
| Data edges | A call that uses another call's result (directly or through index and concatenation instructions) always comes in a later round. This is the first half of L3. |
| Barrier tools are ordered with every call | `send_email` and `delete_file` act on the world and `confirm` asks a human; running a search "at the same time" as a delete, or before a confirm that might stop the run, would change observable behaviour. A barrier call is therefore always alone in its round, in its original position among the calls. This is the second half of L3 (irreversible tools are barriers), extended to privileged and approval tools for the same reason. |
| After the optimizer, after the safety checks | Merged duplicates are gone before rounds are counted. Safety is unaffected: the set of calls in each block is unchanged (budget), no data flow changes (taint), and no call changes block (approval). |
| Greedy, as-soon-as-possible rounds | Simplest list scheduling; with no limit on concurrency it is also optimal in the number of rounds for one block (each round is the next layer of the graph). |
| Rounds counted statically and at runtime | The Rounds tab shows the static `rounds_before → rounds_after` (L2); the run result's `rounds` and each log entry's `round` show what actually executed. |

**Limitations**

| Limitation | Consequence |
| --- | --- |
| No parallelism across blocks or loop iterations | Each `repeat` iteration's calls run in their own rounds; calls on both sides of an `if` are never combined. |
| Non-barrier tools are assumed independent | `read_file` and `web_search` (and `llm`, `sanitize`) may run in any order relative to each other. True for the mocks; a live tool with hidden side effects would break the assumption. |
| Non-call instructions move earlier | Ready non-calls are emitted before the next round. If an `Index` that will fail with E603 moves ahead of a call, a failing run's call log can show fewer calls than the sequential order would have made. Successful runs are unaffected. |
| No limit on concurrency | A block with many independent calls launches them all at once. |
| Speed-up is invisible with mocks | Mock calls return instantly, so the demo shows the round count, not wall-clock time; the benefit appears only with `--live`. |
| Optional milestone | Built only after M1–M6 pass; with `parallel=False` the pipeline skips it, `schedule` is `null` and every call is its own round. |

## 7. Where it lives in the code

> Filled in at M7: list `agentscript/scheduler.py` (`schedule(cfg)`, `ScheduleReport`, the dependency-graph and list-scheduling helpers), the `ParallelCalls` lowering in `agentscript/codegen.py`, the `CALL_PARALLEL` case in `agentscript/vm.py`, how `agentscript/pipeline.py` calls it, and the tests in `tests/test_scheduler.py`.
