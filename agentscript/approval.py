"""Approval analysis (A1-A3): every irreversible call must be dominated by a confirm guard.

Runs on the CFGs of the **unoptimized** IR, one task at a time:

- *confirm values*: variables all of whose definitions are `Call(confirm)` or an `Assign`
  from a confirm value (least fixed point; variables are immutable, so in practice this is
  `t = call confirm(..)` and `let ok = confirm(..)` plus copies of those);
- *guard block*: the true successor of a `Branch` in a reachable block whose condition is
  a confirm value. `confirm(..) == true` is a BinOp result, so it is not a guard;
- a call to an `irreversible` tool in reachable block B is approved iff some guard block
  dominates B (dominators from cfg.dominators). Otherwise it is E502 when a reachable block
  holding a confirm call can reach B (a confirm exists on some path but does not guard
  them all), else E501. Calls in unreachable blocks are listed but ignored.

The diagnostic's `path` is a shortest entry -> B path that avoids every guard block (or,
when none exists, the first guard block), described edge by edge in source terms.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

from . import ir
from .cfg import dominators, immediate_dominators, reachable
from .diagnostics import CompileError, Diagnostic, PathStep, make_error
from .ir import CFG, Assign, BinOp, Branch, Call, Index, Var
from .tools import TOOLS

_TEMP_RE = re.compile(r"t[0-9]+")

APPROVED = "approved"
UNREACHABLE = "unreachable"


# ---------------------------------------------------------------- report data


@dataclass
class GuardBlock:
    label: str  # the true successor of the guarding Branch
    confirm_line: int  # line of the confirm call whose result is branched on
    condition: str  # source-level condition, e.g. "ok" or "confirm(...)"
    branch_line: int

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "confirm_line": self.confirm_line,
            "condition": self.condition,
            "branch_line": self.branch_line,
        }


@dataclass
class IrreversibleCall:
    tool: str
    line: int
    col: int
    block: str
    guarded_by: str | None  # innermost guard block dominating `block`
    verdict: str  # "approved" | "E501" | "E502" | "unreachable"
    confirm_line: int | None = None  # E502: the confirm that reaches but does not guard

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "line": self.line,
            "col": self.col,
            "block": self.block,
            "guarded_by": self.guarded_by,
            "verdict": self.verdict,
            "confirm_line": self.confirm_line,
        }


@dataclass
class TaskApproval:
    name: str
    dominators: dict[str, list[str]]  # reachable block -> its dominators, in layout order
    idom: dict[str, str | None]
    guards: list[GuardBlock] = field(default_factory=list)
    calls: list[IrreversibleCall] = field(default_factory=list)
    violation: CompileError | None = None  # first rejected call of this task

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "dominators": {k: list(v) for k, v in self.dominators.items()},
            "idom": dict(self.idom),
            "guards": [g.to_dict() for g in self.guards],
            "calls": [c.to_dict() for c in self.calls],
        }


@dataclass
class ApprovalReport:
    tasks: list[TaskApproval]
    violation: Diagnostic | None = None

    def artifact(self) -> dict:
        data = {
            "tasks": [t.to_dict() for t in self.tasks],
            "violation": None if self.violation is None else self.violation.to_dict(),
        }
        return {"text": self._text(), "data": data}

    def _text(self) -> str:
        out: list[str] = []
        for task in self.tasks:
            if out:
                out.append("")
            out.extend(_task_text(task))
        if self.violation is not None:
            out.append("")
            out.append(self.violation.format())
        return "\n".join(out)


def _task_text(task: TaskApproval) -> list[str]:
    out = [f"task {task.name}", "  dominators:"]
    width = max((len(label) for label in task.dominators), default=0)
    for label, doms in task.dominators.items():
        idom = task.idom.get(label) or "-"
        out.append(f"    {label:<{width}}  dom = {{{', '.join(doms)}}}  idom = {idom}")
    out.append("  guard blocks:")
    if not task.guards:
        out.append("    (none)")
    for g in task.guards:
        out.append(
            f"    {g.label}  (if {g.condition} on line {g.branch_line}; "
            f"confirm on line {g.confirm_line})"
        )
    out.append("  irreversible calls:")
    if not task.calls:
        out.append("    (none)")
    for c in task.calls:
        guard = c.guarded_by or "-"
        out.append(
            f"    {c.tool} line {c.line} in {c.block}: guarded by {guard} -> {c.verdict}"
        )
    return out


# ------------------------------------------------------------------- analysis


def _calls_of(instr: ir.Instr) -> list[Call]:
    if isinstance(instr, Call):
        return [instr]
    if isinstance(instr, ir.ParallelCalls):
        return list(instr.calls)
    return []


def _definitions(cfg: CFG) -> dict[str, list[ir.Instr]]:
    """var -> every instruction that writes it, in layout order."""
    defs: dict[str, list[ir.Instr]] = {}
    for block in cfg.blocks.values():
        for instr in block.instrs:
            for call in _calls_of(instr):
                defs.setdefault(call.dst.name, []).append(call)
            if not isinstance(instr, (Call, ir.ParallelCalls)):
                name = ir.defined_var(instr)
                if name is not None:
                    defs.setdefault(name, []).append(instr)
    return defs


def confirm_values(defs: dict[str, list[ir.Instr]]) -> set[str]:
    """Vars all of whose definitions are Call(confirm) or a copy of a confirm value."""
    values: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, writes in defs.items():
            if name in values:
                continue
            if all(_is_confirm_write(w, values) for w in writes):
                values.add(name)
                changed = True
    return values


def _is_confirm_write(instr: ir.Instr, values: set[str]) -> bool:
    if isinstance(instr, Call):
        return instr.tool == "confirm"
    if isinstance(instr, Assign):
        return isinstance(instr.src, Var) and instr.src.name in values
    return False


def _confirm_line(name: str, defs: dict[str, list[ir.Instr]]) -> int:
    """Line of the confirm call a confirm value comes from (first definition, followed)."""
    instr = defs[name][0]
    while isinstance(instr, Assign):
        instr = defs[instr.src.name][0]
    return instr.line


class _Describer:
    """Source-level text for IR operands and branch edges."""

    def __init__(self, cfg: CFG, defs: dict[str, list[ir.Instr]]):
        self.defs = defs
        self.params = {name for name, _ in cfg.params}

    def is_temp(self, name: str) -> bool:
        return name not in self.params and _TEMP_RE.fullmatch(name) is not None

    def operand(self, op: ir.Operand) -> str:
        if isinstance(op, ir.Const):
            return ir.format_operand(op)
        name = op.name
        if not self.is_temp(name):
            return name.split(".")[0]  # irgen renames sibling-scope reuse to name.2
        writes = self.defs.get(name, [])
        if len(writes) != 1:
            return name
        w = writes[0]
        if isinstance(w, Call):
            return f"{w.tool}(...)"
        if isinstance(w, BinOp):
            return f"{self.operand(w.left)} {w.op} {self.operand(w.right)}"
        if isinstance(w, Index):
            return f"{self.operand(w.base)}[{self.operand(w.index)}]"
        if isinstance(w, Assign):
            return self.operand(w.src)
        return name

    def loop_count(self, branch: Branch) -> str | None:
        """For a repeat loop head `c = k < n; if c ...`, the source text of the count N."""
        if not isinstance(branch.cond, Var):
            return None
        writes = self.defs.get(branch.cond.name, [])
        if len(writes) != 1 or not isinstance(writes[0], BinOp) or writes[0].op != "<":
            return None
        test = writes[0]
        if not isinstance(test.left, Var) or not isinstance(test.right, Var):
            return None
        counter = test.left.name
        increments = any(
            isinstance(w, BinOp) and w.op == "+" and w.left == Var(counter)
            and w.right == ir.Const(1)
            for w in self.defs.get(counter, [])
        )
        if not increments:
            return None
        limit = self.defs.get(test.right.name, [])
        if len(limit) == 1 and isinstance(limit[0], Assign):
            return self.operand(limit[0].src)
        return self.operand(test.right)

    def edge(self, term: ir.Instr, target: str) -> str:
        if isinstance(term, Branch):
            count = self.loop_count(term)
            if count is not None:
                side = "body" if target == term.if_true else "exit"
                return f"line {term.line}: repeat {count} -> {side} ({target})"
            side = "true" if target == term.if_true else "false"
            return f"line {term.line}: if {self.operand(term.cond)} -> {side} ({target})"
        return f"line {term.line}: goto {target}"


def _forward_reach(cfg: CFG, start: str) -> set[str]:
    """Blocks reachable from `start` through at least one edge."""
    seen: set[str] = set()
    queue = deque(cfg.blocks[start].succs)
    while queue:
        label = queue.popleft()
        if label in seen:
            continue
        seen.add(label)
        queue.extend(cfg.blocks[label].succs)
    return seen


def _shortest_path(cfg: CFG, target: str, avoid: set[str]) -> list[str] | None:
    """BFS entry -> target never entering a block in `avoid` (succs order: true first)."""
    if cfg.entry in avoid:
        return None
    parent: dict[str, str | None] = {cfg.entry: None}
    queue = deque([cfg.entry])
    while queue:
        label = queue.popleft()
        if label == target:
            path = [label]
            while parent[path[-1]] is not None:
                path.append(parent[path[-1]])
            return path[::-1]
        for succ in cfg.blocks[label].succs:
            if succ not in parent and succ not in avoid:
                parent[succ] = label
                queue.append(succ)
    return None


class _TaskChecker:
    def __init__(self, cfg: CFG):
        self.cfg = cfg
        self.live = reachable(cfg)
        self.order = [label for label in cfg.blocks if label in self.live]
        self.dom = dominators(cfg)
        self.defs = _definitions(cfg)
        self.confirms = confirm_values(self.defs)
        self.describe = _Describer(cfg, self.defs)
        self.guards = self._find_guards()
        self.guard_labels = {g.label for g in self.guards}
        # (block, index in block, call) of every confirm call in a reachable block
        self.confirm_calls = [
            (label, k, call)
            for label in self.order
            for k, instr in enumerate(cfg.blocks[label].instrs)
            for call in _calls_of(instr)
            if call.tool == "confirm"
        ]
        self.reach = {
            label: _forward_reach(cfg, label) for label, _, _ in self.confirm_calls
        }

    def _find_guards(self) -> list[GuardBlock]:
        guards: list[GuardBlock] = []
        seen: set[str] = set()
        for label in self.order:
            term = self.cfg.blocks[label].terminator
            if not isinstance(term, Branch) or not isinstance(term.cond, Var):
                continue
            if term.cond.name not in self.confirms or term.if_true in seen:
                continue
            seen.add(term.if_true)
            guards.append(
                GuardBlock(
                    term.if_true,
                    _confirm_line(term.cond.name, self.defs),
                    self.describe.operand(term.cond),
                    term.line,
                )
            )
        return guards

    def check(self) -> TaskApproval:
        idom = immediate_dominators(self.cfg)
        doms = {
            label: [d for d in self.order if d in self.dom[label]] for label in self.order
        }
        task = TaskApproval(self.cfg.name, doms, idom, list(self.guards))
        for label, block in self.cfg.blocks.items():
            for k, instr in enumerate(block.instrs):
                for call in _calls_of(instr):
                    spec = TOOLS.get(call.tool)
                    if spec is None or not spec.irreversible:
                        continue
                    record, err = self._check_call(label, k, call)
                    task.calls.append(record)
                    if err is not None and task.violation is None:
                        task.violation = err
        return task

    def _check_call(
        self, label: str, index: int, call: Call
    ) -> tuple[IrreversibleCall, CompileError | None]:
        if label not in self.live:
            return IrreversibleCall(call.tool, call.line, call.col, label, None, UNREACHABLE), None
        guard = self._innermost_guard(label)
        if guard is not None:
            return IrreversibleCall(call.tool, call.line, call.col, label, guard, APPROVED), None

        confirm = self._reaching_confirm(label, index)
        steps = self._path_steps(label, index, call)
        if confirm is None:
            message = (
                f"irreversible call to '{call.tool}' (line {call.line}) "
                "is reachable without confirm"
            )
            record = IrreversibleCall(call.tool, call.line, call.col, label, None, "E501")
            return record, make_error("E501", message, call.line, call.col, steps)
        message = (
            f"irreversible call to '{call.tool}' (line {call.line}) is not guarded by "
            f"confirm on every path; the confirm on line {confirm.line} does not guard it"
        )
        record = IrreversibleCall(
            call.tool, call.line, call.col, label, None, "E502", confirm.line
        )
        return record, make_error("E502", message, call.line, call.col, steps)

    def _innermost_guard(self, label: str) -> str | None:
        """The dominating guard block with the largest dominator set (closest to B)."""
        dominating = [g for g in self.guard_labels if g in self.dom[label]]
        if not dominating:
            return None
        return max(dominating, key=lambda g: (len(self.dom[g]), g))

    def _reaching_confirm(self, label: str, index: int) -> Call | None:
        """First confirm call (layout order) from which the call at (label, index) is reachable."""
        for block, k, call in self.confirm_calls:
            if label in self.reach[block] or (block == label and k <= index):
                return call
        return None

    def _path_steps(self, label: str, index: int, call: Call) -> list[PathStep]:
        path = _shortest_path(self.cfg, label, self.guard_labels)
        if path is None:
            first = next(g.label for g in self.guards)
            path = _shortest_path(self.cfg, label, {first}) or [label]

        blocks = self.cfg.blocks
        first_instr = blocks[self.cfg.entry].instrs[0]
        steps = [
            PathStep(
                first_instr.line, first_instr.col, f"task {self.cfg.name} starts (entry)"
            )
        ]
        for pos, here in enumerate(path):
            instrs = blocks[here].instrs
            stop = index if here == label else len(instrs)
            for instr in instrs[:stop]:
                for c in _calls_of(instr):
                    if c.tool == "confirm":
                        steps.append(
                            PathStep(
                                c.line,
                                c.col,
                                f"line {c.line}: confirm(...) is asked here",
                            )
                        )
            if pos + 1 < len(path):
                term = blocks[here].terminator
                steps.append(PathStep(term.line, term.col, self.describe.edge(term, path[pos + 1])))
        steps.append(
            PathStep(
                call.line,
                call.col,
                f"{call.tool}(...) is irreversible and not guarded by confirm",
            )
        )
        return steps


def analyze_approval(cfgs: list[CFG]) -> ApprovalReport:
    """Check every task; raise E501/E502 (with `.artifact` = the full report) on a violation."""
    tasks = [_TaskChecker(cfg).check() for cfg in cfgs]
    report = ApprovalReport(tasks)
    for task in tasks:
        if task.violation is not None:
            err = task.violation
            report.violation = err.diagnostic
            err.artifact = report.artifact()
            raise err
    return report
