"""Three-address intermediate representation, basic blocks and the CFG container.

The IR generator (irgen.py) produces a linear listing per task (with Label pseudo
instructions); cfg.py splits it into BasicBlocks. Every instruction carries the source
`line`/`col` of the construct it came from, so later phases can report locations.

Text form of each instruction (format_instr):

    x = y                      Assign
    x = a + b                  BinOp
    x = xs[i]                  Index
    x = call tool(a, b)        Call
    goto L1                    Jump
    if c goto L1 else L2       Branch
    return x                   Return
    L1:                        Label
    round { x = call ...; y = call ... }   ParallelCalls (M7)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .typesys import Type


# ------------------------------------------------------------------- operands


@dataclass(frozen=True)
class Const:
    value: int | str | bool


@dataclass(frozen=True)
class Var:
    name: str  # user variable ("raw", "ok.2"), parameter, loop counter or temp ("t3")


Operand = Const | Var


# --------------------------------------------------------------- instructions


@dataclass
class Instr:
    pass


@dataclass
class Assign(Instr):
    dst: Var
    src: Operand
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


@dataclass
class BinOp(Instr):
    dst: Var
    op: str  # "+" "-" "*" "==" "!=" "<" "<=" ">" ">="
    left: Operand
    right: Operand
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


@dataclass
class Index(Instr):
    dst: Var
    base: Operand
    index: Operand
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


@dataclass
class Call(Instr):
    dst: Var
    tool: str
    args: list[Operand]
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


@dataclass
class Jump(Instr):
    target: str
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


@dataclass
class Branch(Instr):
    cond: Operand
    if_true: str
    if_false: str
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


@dataclass
class Return(Instr):
    value: Operand
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


@dataclass
class Label(Instr):
    name: str
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


@dataclass
class ParallelCalls(Instr):
    """M7 only: independent calls executed concurrently as one round."""

    calls: list[Call]
    line: int = field(default=0, kw_only=True)
    col: int = field(default=0, kw_only=True)


TERMINATORS = (Jump, Branch, Return)


# ------------------------------------------------------------------ containers


@dataclass
class IRFunction:
    """Linear IR for one task, as produced by irgen.lower()."""

    name: str
    params: list[tuple[str, Type]]
    return_type: Type
    instrs: list[Instr]


@dataclass
class BasicBlock:
    label: str
    instrs: list[Instr]  # no Label instructions; the last one is the only terminator
    succs: list[str] = field(default_factory=list)  # Branch: [if_true, if_false]
    preds: list[str] = field(default_factory=list)

    @property
    def terminator(self) -> Instr:
        return self.instrs[-1]


@dataclass
class CFG:
    name: str  # task name
    params: list[tuple[str, Type]]
    return_type: Type
    blocks: dict[str, BasicBlock]  # insertion order = layout order; first is the entry
    entry: str = "entry"


# --------------------------------------------------------------------- helpers


def defined_var(instr: Instr) -> str | None:
    """Name of the variable an instruction writes, if any (ParallelCalls: use defined_vars)."""
    if isinstance(instr, (Assign, BinOp, Index, Call)):
        return instr.dst.name
    return None


def defined_vars(instr: Instr) -> list[str]:
    if isinstance(instr, ParallelCalls):
        return [c.dst.name for c in instr.calls]
    name = defined_var(instr)
    return [] if name is None else [name]


def operands(instr: Instr) -> list[Operand]:
    """Operands an instruction reads, in order."""
    if isinstance(instr, Assign):
        return [instr.src]
    if isinstance(instr, BinOp):
        return [instr.left, instr.right]
    if isinstance(instr, Index):
        return [instr.base, instr.index]
    if isinstance(instr, Call):
        return list(instr.args)
    if isinstance(instr, Branch):
        return [instr.cond]
    if isinstance(instr, Return):
        return [instr.value]
    if isinstance(instr, ParallelCalls):
        return [a for c in instr.calls for a in c.args]
    return []


def used_vars(instr: Instr) -> list[str]:
    """Names of the variables an instruction reads, in operand order."""
    return [op.name for op in operands(instr) if isinstance(op, Var)]


def format_operand(op: Operand) -> str:
    if isinstance(op, Var):
        return op.name
    if isinstance(op.value, bool):
        return "true" if op.value else "false"
    if isinstance(op.value, str):
        return json.dumps(op.value)
    return str(op.value)


def format_instr(instr: Instr) -> str:
    f = format_operand
    if isinstance(instr, Assign):
        return f"{instr.dst.name} = {f(instr.src)}"
    if isinstance(instr, BinOp):
        return f"{instr.dst.name} = {f(instr.left)} {instr.op} {f(instr.right)}"
    if isinstance(instr, Index):
        return f"{instr.dst.name} = {f(instr.base)}[{f(instr.index)}]"
    if isinstance(instr, Call):
        args = ", ".join(f(a) for a in instr.args)
        return f"{instr.dst.name} = call {instr.tool}({args})"
    if isinstance(instr, Jump):
        return f"goto {instr.target}"
    if isinstance(instr, Branch):
        return f"if {f(instr.cond)} goto {instr.if_true} else {instr.if_false}"
    if isinstance(instr, Return):
        return f"return {f(instr.value)}"
    if isinstance(instr, Label):
        return f"{instr.name}:"
    if isinstance(instr, ParallelCalls):
        return "round { " + "; ".join(format_instr(c) for c in instr.calls) + " }"
    raise TypeError(f"unknown instruction {instr!r}")


def format_function(fn: IRFunction) -> str:
    """Linear listing with line numbers of the source, e.g.

    task report(topic: string) -> bool
          raw = call web_search(topic)        ; line 6
    """
    params = ", ".join(f"{n}: {t}" for n, t in fn.params)
    out = [f"task {fn.name}({params}) -> {fn.return_type}"]
    for instr in fn.instrs:
        if isinstance(instr, Label):
            out.append(f"  {instr.name}:")
        else:
            out.append(f"      {format_instr(instr):<40} ; line {instr.line}")
    return "\n".join(out)


def count_instructions(cfg: CFG) -> int:
    """Non-label instructions in a CFG (ParallelCalls counts each call)."""
    total = 0
    for block in cfg.blocks.values():
        for instr in block.instrs:
            total += len(instr.calls) if isinstance(instr, ParallelCalls) else 1
    return total


def count_calls(cfg: CFG) -> int:
    total = 0
    for block in cfg.blocks.values():
        for instr in block.instrs:
            if isinstance(instr, Call):
                total += 1
            elif isinstance(instr, ParallelCalls):
                total += len(instr.calls)
    return total
