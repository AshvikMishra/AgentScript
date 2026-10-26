"""Bytecode for the AgentScript stack VM.

Stack effects (stack grows to the right):

    PUSH_CONST v          [] -> [v]
    LOAD name             [] -> [value of name]
    STORE name            [v] -> []
    ADD SUB MUL           [a, b] -> [a op b]        (ADD also concatenates strings)
    EQ NE LT LE GT GE     [a, b] -> [bool]
    INDEX                 [list, i] -> [list[i]]    (E603 when i is out of range)
    CALL tool argc        [a1 .. an] -> [result]    (budget guard E601, permission guard E602)
    CALL_PARALLEL calls   [args of call 1 .. args of call k] -> [r1 .. rk]   (M7; arg = [(tool, argc), ...])
    JUMP addr             [] -> []
    JUMP_IF_FALSE addr    [cond] -> []
    RETURN                [v] -> []                 (ends the task with value v)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Op(Enum):
    PUSH_CONST = "PUSH_CONST"
    LOAD = "LOAD"
    STORE = "STORE"
    ADD = "ADD"
    SUB = "SUB"
    MUL = "MUL"
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LE = "LE"
    GT = "GT"
    GE = "GE"
    INDEX = "INDEX"
    CALL = "CALL"
    CALL_PARALLEL = "CALL_PARALLEL"
    JUMP = "JUMP"
    JUMP_IF_FALSE = "JUMP_IF_FALSE"
    RETURN = "RETURN"


# IR binary operator -> opcode
BINARY_OPS: dict[str, Op] = {
    "+": Op.ADD,
    "-": Op.SUB,
    "*": Op.MUL,
    "==": Op.EQ,
    "!=": Op.NE,
    "<": Op.LT,
    "<=": Op.LE,
    ">": Op.GT,
    ">=": Op.GE,
}


@dataclass
class BInstr:
    op: Op
    arg: Any = None  # PUSH_CONST value, LOAD/STORE name, CALL tool, JUMP* address, CALL_PARALLEL [(tool, argc), ...]
    arg2: Any = None  # CALL argc
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)

    def format(self) -> str:
        op = self.op.value
        if self.op is Op.PUSH_CONST:
            v = self.arg
            text = ("true" if v else "false") if isinstance(v, bool) else json.dumps(v)
            return f"{op} {text}"
        if self.op is Op.CALL:
            return f"{op} {self.arg} {self.arg2}"
        if self.op is Op.CALL_PARALLEL:
            return f"{op} " + ", ".join(f"{t}/{n}" for t, n in self.arg)
        if self.arg is None:
            return op
        return f"{op} {self.arg}"

    def to_dict(self) -> dict:
        arg = [list(c) for c in self.arg] if self.op is Op.CALL_PARALLEL else self.arg
        return {"op": self.op.value, "arg": arg, "arg2": self.arg2, "line": self.line, "col": self.col}


@dataclass
class BytecodeTask:
    name: str
    params: list[tuple[str, str]]  # (name, type as text, e.g. "list<string>")
    return_type: str
    code: list[BInstr]


@dataclass
class BytecodeProgram:
    agent: str
    permits: list[str]
    budget: int
    tasks: dict[str, BytecodeTask]

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "permits": self.permits,
            "budget": self.budget,
            "tasks": {
                name: {
                    "params": [{"name": n, "type": t} for n, t in task.params],
                    "return_type": task.return_type,
                    "code": [i.to_dict() for i in task.code],
                }
                for name, task in self.tasks.items()
            },
        }


def format_program(program: BytecodeProgram) -> str:
    """e.g.

    agent Assistant  permit [web_search, ...]  budget 5
    task report(topic: string) -> bool
       0  LOAD topic                     ; line 6
       1  CALL web_search 1              ; line 6
    """
    out = [f"agent {program.agent}  permit [{', '.join(program.permits)}]  budget {program.budget}"]
    for task in program.tasks.values():
        params = ", ".join(f"{n}: {t}" for n, t in task.params)
        out.append(f"task {task.name}({params}) -> {task.return_type}")
        for addr, instr in enumerate(task.code):
            out.append(f"  {addr:>3}  {instr.format():<30} ; line {instr.line}")
    return "\n".join(out)
