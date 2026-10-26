"""Taint analysis (T1-T4): untrusted tool output must not reach a privileged tool.

A forward data-flow analysis over the CFG of the UNOPTIMIZED IR (design brief section 3):

- labels: trusted < untrusted; one label per value (a list carries one label);
- state at each block entry: var -> TaintInfo for the untrusted vars (absent = trusted);
  the entry state is empty (parameters and literals are trusted);
- Assign / BinOp / Index: untrusted if any operand var is; provenance from the first
  untrusted operand in operand order, plus one PathStep for this instruction;
- Call: `untrusted_result` starts a new chain, `propagates_taint` joins its arguments,
  every other tool (sanitizer, bools) returns a trusted value;
- meet at joins = union, provenance from the first predecessor (preds order) that has it;
- round-robin over the reachable blocks in layout order until the set of untrusted names
  at every block entry stops changing.

Only explicit flows are tracked: taint does not flow through `if` conditions or loop
counts. Afterwards every argument of every privileged call is checked; the first
untrusted one raises E401 at the call, with the source-to-sink chain as its path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ir
from .cfg import reachable
from .diagnostics import CompileError, Diagnostic, PathStep, make_error
from .ir import CFG, Call, Var
from .tools import TOOLS

State = dict[str, "TaintInfo"]


@dataclass(frozen=True)
class TaintInfo:
    """Why a variable is untrusted: the source call and the chain of IR steps since."""

    source_tool: str
    source_line: int
    source_col: int
    steps: tuple[PathStep, ...]

    def extend(self, instr: ir.Instr) -> TaintInfo:
        step = PathStep(instr.line, instr.col, ir.format_instr(instr))
        return TaintInfo(self.source_tool, self.source_line, self.source_col, self.steps + (step,))


# ------------------------------------------------------------------- report


@dataclass
class UntrustedVar:
    var: str
    line: int  # where it is defined
    info: TaintInfo

    def to_dict(self) -> dict:
        return {
            "var": self.var,
            "line": self.line,
            "source_tool": self.info.source_tool,
            "source_line": self.info.source_line,
            "path": [s.to_dict() for s in self.info.steps],
        }


@dataclass
class SanitizedResult:
    var: str
    line: int
    col: int
    text: str  # the IR instruction
    input_untrusted: bool

    def to_dict(self) -> dict:
        return {
            "var": self.var,
            "line": self.line,
            "col": self.col,
            "instr": self.text,
            "input": "untrusted" if self.input_untrusted else "trusted",
            "result": "trusted",
        }


@dataclass
class SinkArg:
    label: str  # the operand as printed in the IR
    info: TaintInfo | None  # None = trusted

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "taint": "trusted" if self.info is None else "untrusted",
            "source_tool": None if self.info is None else self.info.source_tool,
            "source_line": None if self.info is None else self.info.source_line,
        }


@dataclass
class SinkCheck:
    tool: str
    line: int
    col: int
    text: str  # the IR instruction
    args: list[SinkArg]

    @property
    def ok(self) -> bool:
        return all(a.info is None for a in self.args)

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "line": self.line,
            "col": self.col,
            "instr": self.text,
            "args": [a.to_dict() for a in self.args],
            "status": "OK" if self.ok else "VIOLATION",
        }


@dataclass
class TaskTaint:
    name: str
    iterations: int
    block_entry: dict[str, list[str]]  # reachable block -> sorted untrusted names at entry
    untrusted: list[UntrustedVar] = field(default_factory=list)
    sanitized: list[SanitizedResult] = field(default_factory=list)
    sinks: list[SinkCheck] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "block_entry": {k: list(v) for k, v in self.block_entry.items()},
            "untrusted": [u.to_dict() for u in self.untrusted],
            "sanitized": [s.to_dict() for s in self.sanitized],
            "sinks": [s.to_dict() for s in self.sinks],
        }


@dataclass
class TaintReport:
    tasks: list[TaskTaint]
    violation: Diagnostic | None = None

    def tainted_lines(self) -> list[int]:
        """Source lines of instructions that define an untrusted var (editor highlighting)."""
        return sorted({u.line for t in self.tasks for u in t.untrusted})

    def artifact(self) -> dict:
        data = {
            "tasks": [t.to_dict() for t in self.tasks],
            "tainted_lines": self.tainted_lines(),
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


def _task_text(task: TaskTaint) -> list[str]:
    out = [f"task {task.name}  (fixed point after {task.iterations} iteration(s))"]
    out.append("  untrusted variables:")
    if not task.untrusted:
        out.append("    (none)")
    for u in task.untrusted:
        out.append(
            f"    {u.var:<12} line {u.line:<4} from {u.info.source_tool} (line {u.info.source_line})"
        )
    out.append("  sanitized (trusted) results:")
    if not task.sanitized:
        out.append("    (none)")
    for s in task.sanitized:
        given = "untrusted" if s.input_untrusted else "trusted"
        out.append(f"    {s.var:<12} line {s.line:<4} {s.text}  (input {given})")
    out.append("  privileged sinks:")
    if not task.sinks:
        out.append("    (none)")
    for sink in task.sinks:
        args = ", ".join(
            f"{a.label}: " + ("trusted" if a.info is None else f"untrusted from {a.info.source_tool}")
            for a in sink.args
        )
        status = "OK" if sink.ok else "VIOLATION"
        out.append(f"    {sink.tool} line {sink.line}  [{args}]  {status}")
    return out


# ----------------------------------------------------------------- analysis


def _operand_info(op: ir.Operand, state: State) -> TaintInfo | None:
    return state.get(op.name) if isinstance(op, Var) else None


def _first_untrusted(ops: list[ir.Operand], state: State) -> TaintInfo | None:
    for op in ops:
        info = _operand_info(op, state)
        if info is not None:
            return info
    return None


def _set(state: State, dst: str, info: TaintInfo | None) -> None:
    if info is None:
        state.pop(dst, None)
    else:
        state[dst] = info


def _call_result(call: Call, state: State) -> TaintInfo | None:
    spec = TOOLS[call.tool]
    if spec.untrusted_result:
        note = f"{ir.format_instr(call)}  <- {call.tool} returns untrusted data"
        return TaintInfo(call.tool, call.line, call.col, (PathStep(call.line, call.col, note),))
    if spec.propagates_taint:
        joined = _first_untrusted(call.args, state)
        return None if joined is None else joined.extend(call)
    return None  # sanitizer, or a tool returning a fresh trusted value


def _calls_of(instr: ir.Instr) -> list[Call]:
    if isinstance(instr, Call):
        return [instr]
    if isinstance(instr, ir.ParallelCalls):  # defensive: taint runs before scheduling
        return list(instr.calls)
    return []


def transfer(instr: ir.Instr, state: State) -> None:
    """Apply one instruction to `state` in place."""
    if isinstance(instr, (ir.Assign, ir.BinOp, ir.Index)):
        info = _first_untrusted(ir.operands(instr), state)
        _set(state, instr.dst.name, None if info is None else info.extend(instr))
        return
    # Results of a round are computed from the state before the round.
    results = [(c.dst.name, _call_result(c, state)) for c in _calls_of(instr)]
    for dst, info in results:
        _set(state, dst, info)


def _meet(cfg: CFG, label: str, exits: dict[str, State], live: set[str]) -> State:
    """Union of the predecessors' exit states; provenance from the first pred that has it."""
    state: State = {}
    for pred in cfg.blocks[label].preds:
        if pred not in live:
            continue
        for var, info in exits.get(pred, {}).items():
            state.setdefault(var, info)
    return state


def solve(cfg: CFG) -> tuple[dict[str, State], int]:
    """Block-entry states of the reachable blocks and the number of round-robin passes."""
    live = reachable(cfg)
    order = [label for label in cfg.blocks if label in live]
    entries: dict[str, State] = {label: {} for label in order}
    exits: dict[str, State] = {}
    iterations = 0
    changed = True
    while changed:
        changed = False
        iterations += 1
        for label in order:
            new_entry = _meet(cfg, label, exits, live)
            if set(new_entry) != set(entries[label]):
                changed = True
            entries[label] = new_entry
            state = dict(new_entry)
            for instr in cfg.blocks[label].instrs:
                transfer(instr, state)
            exits[label] = state
    return entries, iterations


def _check_task(cfg: CFG) -> TaskTaint:
    entries, iterations = solve(cfg)
    task = TaskTaint(
        cfg.name, iterations, {label: sorted(state) for label, state in entries.items()}
    )
    for label, entry in entries.items():
        state = dict(entry)
        for instr in cfg.blocks[label].instrs:
            for call in _calls_of(instr):
                _record_call(task, call, state)
            transfer(instr, state)
            for dst in ir.defined_vars(instr):
                if dst in state:
                    task.untrusted.append(UntrustedVar(dst, instr.line, state[dst]))
    return task


def _record_call(task: TaskTaint, call: Call, state: State) -> None:
    spec = TOOLS[call.tool]
    text = ir.format_instr(call)
    if spec.sanitizer:
        untrusted_in = _first_untrusted(call.args, state) is not None
        task.sanitized.append(SanitizedResult(call.dst.name, call.line, call.col, text, untrusted_in))
    if spec.privileged:
        args = [SinkArg(ir.format_operand(a), _operand_info(a, state)) for a in call.args]
        task.sinks.append(SinkCheck(call.tool, call.line, call.col, text, args))


def _violation(task: TaskTaint) -> CompileError | None:
    for sink in task.sinks:
        for k, arg in enumerate(sink.args, start=1):
            if arg.info is None:
                continue
            info = arg.info
            message = (
                f"untrusted data from {info.source_tool} (line {info.source_line}) reaches "
                f"privileged tool '{sink.tool}' (line {sink.line}), argument {k}; "
                "pass it through sanitize first"
            )
            final = PathStep(sink.line, sink.col, f"{sink.text}  <- privileged sink")
            return make_error("E401", message, sink.line, sink.col, list(info.steps) + [final])
    return None


def analyze_taint(cfgs: list[CFG]) -> TaintReport:
    """Analyze every task; raise E401 (with `.artifact` = the full report) on a violation."""
    report = TaintReport([_check_task(cfg) for cfg in cfgs])
    for task in report.tasks:
        err = _violation(task)
        if err is not None:
            report.violation = err.diagnostic
            err.artifact = report.artifact()
            raise err
    return report
