"""Parallel tool-call scheduling (M7, L1-L3): group independent calls into rounds.

schedule(cfg) works on a deep copy of the CFG, one basic block at a time:

- a dependency graph over the block's non-terminator instructions, through variable names:
  true (read-after-write), anti (write-after-read) and output (write-after-write)
  dependencies; a barrier call (ToolSpec.barrier: privileged, irreversible or approval)
  depends on every earlier Call in the block and every later Call depends on it (L3);
  an Index (which may fail with E603) is ordered against every Call the same way, so a
  failing index stops the run after exactly the calls the unscheduled program makes;
- list scheduling: repeatedly emit every ready non-call instruction in original order until
  none is ready, then take every ready Call as one round (k >= 2 -> one ParallelCalls with
  the line/col of the first call, k == 1 -> the plain Call); the terminator stays last.

Rounds before = number of calls; rounds after = number of rounds emitted (a ParallelCalls
counts 1). A ParallelCalls already in the input is flattened back into its calls first, so
scheduling twice gives the same result.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from . import ir
from .ir import CFG, BasicBlock, Call, Instr, ParallelCalls
from .tools import TOOLS


# ------------------------------------------------------------------- report


@dataclass
class BlockRounds:
    label: str
    rounds: list[list[str]]  # per round, the text of each call in it


@dataclass
class TaskSchedule:
    name: str
    rounds_before: int
    rounds_after: int
    blocks: list[BlockRounds] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "rounds_before": self.rounds_before,
            "rounds_after": self.rounds_after,
            "blocks": [{"label": b.label, "rounds": [list(r) for r in b.rounds]} for b in self.blocks],
        }


@dataclass
class ScheduleReport:
    tasks: list[TaskSchedule]
    rounds_before: int
    rounds_after: int

    def to_dict(self) -> dict:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "rounds_before": self.rounds_before,
            "rounds_after": self.rounds_after,
        }


# ------------------------------------------------------------ dependencies


def _is_barrier(instr: Instr) -> bool:
    return isinstance(instr, Call) and instr.tool in TOOLS and TOOLS[instr.tool].barrier


def _call_and_index(a: Instr, b: Instr) -> bool:
    return (isinstance(a, Call) and isinstance(b, ir.Index)) or (
        isinstance(a, ir.Index) and isinstance(b, Call)
    )


def build_dependencies(instrs: list[Instr]) -> list[set[int]]:
    """deps[j] = indexes of the earlier instructions that j must follow."""
    deps: list[set[int]] = [set() for _ in instrs]
    for j, later in enumerate(instrs):
        writes_j = set(ir.defined_vars(later))
        reads_j = set(ir.used_vars(later))
        for i in range(j):
            earlier = instrs[i]
            writes_i = set(ir.defined_vars(earlier))
            reads_i = set(ir.used_vars(earlier))
            if (
                writes_i & reads_j  # true dependency
                or reads_i & writes_j  # anti dependency
                or writes_i & writes_j  # output dependency
            ):
                deps[j].add(i)
            elif isinstance(earlier, Call) and isinstance(later, Call):
                if _is_barrier(earlier) or _is_barrier(later):
                    deps[j].add(i)
            elif _call_and_index(earlier, later):
                deps[j].add(i)
    return deps


# ---------------------------------------------------------------- scheduling


def _flatten(instrs: list[Instr]) -> list[Instr]:
    out: list[Instr] = []
    for instr in instrs:
        if isinstance(instr, ParallelCalls):
            out.extend(instr.calls)
        else:
            out.append(instr)
    return out


def schedule_block(block: BasicBlock) -> list[list[Call]]:
    """Reorder block.instrs in place into rounds; returns the call rounds in order."""
    body = _flatten(block.instrs[:-1])
    terminator = block.instrs[-1]
    deps = build_dependencies(body)
    done: set[int] = set()
    out: list[Instr] = []
    rounds: list[list[Call]] = []

    def ready(k: int) -> bool:
        return k not in done and deps[k] <= done

    while len(done) < len(body):
        progress = True
        while progress:
            progress = False
            for k, instr in enumerate(body):
                if not isinstance(instr, Call) and ready(k):
                    done.add(k)
                    out.append(instr)
                    progress = True
        calls = [k for k, instr in enumerate(body) if isinstance(instr, Call) and ready(k)]
        if not calls:
            continue  # only reached when the non-call loop already finished the body
        group = [body[k] for k in calls]
        done.update(calls)
        rounds.append(group)
        if len(group) == 1:
            out.append(group[0])
        else:
            first = group[0]
            out.append(ParallelCalls(group, line=first.line, col=first.col))

    block.instrs = out + [terminator]
    return rounds


def schedule(cfg: CFG) -> tuple[CFG, ScheduleReport]:
    """Schedule every block of a deep copy of cfg; the input is never mutated."""
    result = copy.deepcopy(cfg)
    task = TaskSchedule(cfg.name, 0, 0)
    for block in result.blocks.values():
        rounds = schedule_block(block)
        if not rounds:
            continue
        task.rounds_before += sum(len(r) for r in rounds)
        task.rounds_after += len(rounds)
        task.blocks.append(BlockRounds(block.label, [[ir.format_instr(c) for c in r] for r in rounds]))
    return result, ScheduleReport([task], task.rounds_before, task.rounds_after)


# ------------------------------------------------------------------ artifact


def format_schedule(reports: list[ScheduleReport]) -> str:
    out: list[str] = []
    for report in reports:
        for task in report.tasks:
            out.append(f"task {task.name}: rounds {task.rounds_before} -> {task.rounds_after}")
            for block in task.blocks:
                out.append(f"  {block.label}:")
                for n, calls in enumerate(block.rounds, start=1):
                    out.append(f"    round {n}: " + " | ".join(calls))
    before = sum(r.rounds_before for r in reports)
    after = sum(r.rounds_after for r in reports)
    out.append(f"total: rounds {before} -> {after}")
    return "\n".join(out)


def schedule_artifact(results: list[tuple[CFG, ScheduleReport]]) -> dict:
    """Phase artifact for the results of schedule() over every task."""
    reports = [report for _, report in results]
    return {
        "text": format_schedule(reports),
        "data": {
            "tasks": [t.to_dict() for r in reports for t in r.tasks],
            "rounds_before": sum(r.rounds_before for r in reports),
            "rounds_after": sum(r.rounds_after for r in reports),
        },
    }
