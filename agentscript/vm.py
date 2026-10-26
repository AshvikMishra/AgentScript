"""The AgentScript stack VM: validates a run request, then executes one task's bytecode.

Runtime guards (brief section 3, "Running"):
    E601  budget exceeded: checked before every call, also each call of a CALL_PARALLEL round:
          the calls of the round that fit run, then E601 at the first one that does not,
          exactly as the unscheduled program would
    E602  tool not permitted (defensive: compiled programs never trigger it)
    E603  index out of range (i < 0 or i >= len)
    E604  invalid run request (unknown task, missing/extra argument, wrong JSON type)

The call budget does not bound call-free loops, so the VM also stops with E601 after
MAX_STEPS executed instructions (an execution-step budget; the brief sets no such limit).

A runtime error carries the calls made so far as `err.calls` and `err.calls_used`.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .bytecode import BInstr, BytecodeProgram, BytecodeTask, Op
from .diagnostics import AgentRuntimeError, make_diagnostic, make_error
from .registry import ToolRegistry

RESULT_PREVIEW = 60
MAX_STEPS = 1_000_000  # executed instructions per run


@dataclass
class CallRecord:
    n: int  # 1-based position in the run's call log
    tool: str
    args: list
    result: Any
    line: int
    col: int
    round: int  # a CALL is one round; all calls of one CALL_PARALLEL share a round
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
            "line": self.line,
            "round": self.round,
            "note": self.note,
        }


@dataclass
class RunResult:
    value: Any
    calls: list[CallRecord] = field(default_factory=list)
    calls_used: int = 0
    budget: int = 0
    rounds: int = 0

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "calls": [c.to_dict() for c in self.calls],
            "calls_used": self.calls_used,
            "budget": self.budget,
            "rounds": self.rounds,
        }

    def format(self) -> str:
        header = f"calls: {self.calls_used} of budget {self.budget}, rounds: {self.rounds}"
        return "\n".join([header, format_call_log(self.calls), f"value: {to_json(self.value)}"])


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _preview(value: Any) -> str:
    text = to_json(value)
    return text if len(text) <= RESULT_PREVIEW else text[: RESULT_PREVIEW - 3] + "..."


def format_call_log(calls: list[CallRecord]) -> str:
    """Call log table: one row per call, plus an indented line for each note."""
    if not calls:
        return "  (no tool calls)"
    rows = [f"  {'#':>3}  {'round':>5}  {'line':>4}  {'tool':<11}  args -> result"]
    for c in calls:
        args = ", ".join(_preview(a) for a in c.args)
        rows.append(f"  {c.n:>3}  {c.round:>5}  {c.line:>4}  {c.tool:<11}  ({args}) -> {_preview(c.result)}")
        if c.note:
            rows.append(f"  {'':>3}  {'':>5}  {'':>4}  note: {c.note}")
    return "\n".join(rows)


# ---------------------------------------------------------------- run request (E604)


def _split_type(text: str) -> tuple[str, str | None]:
    """'list<list<string>>' -> ('list', 'list<string>'); 'int' -> ('int', None)."""
    text = text.strip()
    if text.startswith("list<") and text.endswith(">"):
        return "list", text[5:-1]
    return text, None


def matches_type(value: Any, type_text: str) -> bool:
    """JSON value vs. AgentScript type: string<->str, int<->int (not bool), bool<->bool, list<T>."""
    name, elem = _split_type(type_text)
    if name == "string":
        return isinstance(value, str)
    if name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "bool":
        return isinstance(value, bool)
    if name == "list" and elem is not None:
        return isinstance(value, list) and all(matches_type(v, elem) for v in value)
    return False


def _invalid(message: str) -> AgentRuntimeError:
    return make_error("E604", f"invalid run request: {message}", 0, 0)


def validate_request(program: BytecodeProgram, task: str, args: Any) -> BytecodeTask:
    if not isinstance(task, str) or task not in program.tasks:
        known = ", ".join(program.tasks) or "none"
        raise _invalid(f"unknown task `{task}` (tasks: {known})")
    spec = program.tasks[task]
    if not isinstance(args, dict):
        raise _invalid("args must be a JSON object of {parameter: value}")
    for name, type_text in spec.params:
        if name not in args:
            raise _invalid(f"missing argument `{name}` ({type_text}) for task `{task}`")
        if not matches_type(args[name], type_text):
            raise _invalid(f"argument `{name}` must be {type_text}, got {to_json(args[name])}")
    declared = {name for name, _ in spec.params}
    for name in args:
        if name not in declared:
            raise _invalid(f"unexpected argument `{name}` for task `{task}`")
    return spec


# ---------------------------------------------------------------- execution


def _internal(message: str, instr: BInstr | None = None) -> AgentRuntimeError:
    line, col = (instr.line, instr.col) if instr else (0, 0)
    return AgentRuntimeError(make_diagnostic("E000", f"internal VM error: {message}", line, col))


_BINARY = {
    Op.ADD: lambda a, b: a + b,
    Op.SUB: lambda a, b: a - b,
    Op.MUL: lambda a, b: a * b,
    Op.EQ: lambda a, b: a == b,
    Op.NE: lambda a, b: a != b,
    Op.LT: lambda a, b: a < b,
    Op.LE: lambda a, b: a <= b,
    Op.GT: lambda a, b: a > b,
    Op.GE: lambda a, b: a >= b,
}


class _Machine:
    def __init__(self, program: BytecodeProgram, task: BytecodeTask, args: dict, registry: ToolRegistry):
        self.program = program
        self.code = task.code
        self.registry = registry
        self.locals: dict[str, Any] = dict(args)
        self.stack: list[Any] = []
        self.calls: list[CallRecord] = []
        self.rounds = 0

    def pop(self, instr: BInstr) -> Any:
        if not self.stack:
            raise _internal(f"stack underflow at {instr.op.value}", instr)
        return self.stack.pop()

    def pop_args(self, argc: int, instr: BInstr) -> list:
        if argc > len(self.stack):
            raise _internal(f"stack underflow at {instr.op.value}", instr)
        args = self.stack[len(self.stack) - argc :] if argc else []
        del self.stack[len(self.stack) - argc :]
        return args

    def execute(self) -> Any:
        pc = 0
        steps = 0
        while 0 <= pc < len(self.code):
            instr = self.code[pc]
            pc += 1
            steps += 1
            if steps > MAX_STEPS:
                raise make_error(
                    "E601",
                    f"budget exceeded: execution step limit of {MAX_STEPS} instructions reached",
                    instr.line,
                    instr.col,
                )
            op = instr.op
            if op is Op.PUSH_CONST:
                self.stack.append(instr.arg)
            elif op is Op.LOAD:
                if instr.arg not in self.locals:
                    raise _internal(f"load of undefined variable `{instr.arg}`", instr)
                self.stack.append(self.locals[instr.arg])
            elif op is Op.STORE:
                self.locals[instr.arg] = self.pop(instr)
            elif op in _BINARY:
                b = self.pop(instr)
                a = self.pop(instr)
                self.stack.append(_BINARY[op](a, b))
            elif op is Op.INDEX:
                self.index(instr)
            elif op is Op.CALL:
                self.call(instr)
            elif op is Op.CALL_PARALLEL:
                self.call_parallel(instr)
            elif op is Op.JUMP:
                pc = instr.arg
            elif op is Op.JUMP_IF_FALSE:
                if not self.pop(instr):
                    pc = instr.arg
            elif op is Op.RETURN:
                return self.pop(instr)
            else:
                raise _internal(f"unknown opcode {op}", instr)
        raise _internal("task ended without RETURN")

    def index(self, instr: BInstr) -> None:
        i = self.pop(instr)
        base = self.pop(instr)
        if i < 0 or i >= len(base):
            raise make_error(
                "E603", f"index {i} out of range for list of length {len(base)}", instr.line, instr.col
            )
        self.stack.append(base[i])

    def guard_error(self, tool: str, n: int, line: int, col: int) -> AgentRuntimeError | None:
        """The E601/E602 error for making call number n (1-based) to `tool`, or None if allowed."""
        budget = self.program.budget
        if n > budget:
            message = f"budget exceeded: call {budget + 1} would exceed the budget of {budget} calls"
            return make_error("E601", message, line, col)
        if tool not in self.program.permits:
            permits = ", ".join(self.program.permits) or "none"
            return make_error("E602", f"tool `{tool}` is not permitted at runtime (permits: {permits})", line, col)
        return None

    def invoke(self, tool: str, args: list) -> tuple[Any, str | None]:
        if hasattr(self.registry, "call_with_note"):
            return self.registry.call_with_note(tool, args)
        before = len(self.registry.notes)
        value = self.registry.call(tool, args)
        notes = self.registry.notes[before:]
        return value, "; ".join(notes) if notes else None

    def record(self, tool: str, args: list, result: Any, note: str | None, line: int, col: int) -> None:
        n = len(self.calls) + 1
        self.calls.append(CallRecord(n, tool, args, result, line, col, self.rounds, note))

    def call(self, instr: BInstr) -> None:
        tool, argc = instr.arg, instr.arg2
        error = self.guard_error(tool, len(self.calls) + 1, instr.line, instr.col)
        if error is not None:
            raise error
        args = self.pop_args(argc, instr)
        self.rounds += 1
        result, note = self.invoke(tool, args)
        self.record(tool, args, result, note, instr.line, instr.col)
        self.stack.append(result)

    def call_parallel(self, instr: BInstr) -> None:
        specs = [(tool, argc) for tool, argc in instr.arg]
        locations = [tuple(loc) for loc in instr.arg2] if instr.arg2 else [(instr.line, instr.col)] * len(specs)
        if len(locations) != len(specs):
            raise _internal("CALL_PARALLEL needs one location per call", instr)
        total = sum(argc for _, argc in specs)
        flat = self.pop_args(total, instr)
        groups, offset = [], 0
        for tool, argc in specs:
            groups.append((tool, flat[offset : offset + argc]))
            offset += argc
        # guard each call in program order: the ones before the first refused call still run
        # (as one round), so a budget or permission stop matches sequential execution
        error = None
        for k, (tool, _) in enumerate(groups):
            error = self.guard_error(tool, len(self.calls) + k + 1, *locations[k])
            if error is not None:
                groups = groups[:k]
                break
        if groups:
            self.rounds += 1
            with ThreadPoolExecutor(max_workers=len(groups)) as pool:
                futures = [pool.submit(self.invoke, tool, args) for tool, args in groups]
                # results are collected in program order, so the log and stack stay deterministic
                outcomes = [f.result() for f in futures]
            for (tool, args), (result, note), (line, col) in zip(groups, outcomes, locations):
                self.record(tool, args, result, note, line, col)
                self.stack.append(result)
        if error is not None:
            raise error


def run(program: BytecodeProgram, task: str, args: dict, registry: ToolRegistry) -> RunResult:
    """Run `task` with JSON `args`; raises AgentRuntimeError (E601-E604) with err.calls attached."""
    machine: _Machine | None = None
    try:
        spec = validate_request(program, task, args)
        machine = _Machine(program, spec, args, registry)
        value = machine.execute()
    except AgentRuntimeError as err:
        calls = machine.calls if machine else []
        err.calls = list(calls)
        err.calls_used = len(calls)
        raise
    return RunResult(value, machine.calls, len(machine.calls), program.budget, machine.rounds)
