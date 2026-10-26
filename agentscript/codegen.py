"""Code generation: lower each task's CFG to stack-VM bytecode (design brief section 5).

Blocks are laid out in CFG order (`cfg.blocks` insertion order). Generation takes two passes:

1. emit every block's instructions with symbolic jump targets (block labels) and record the
   address at which each block starts;
2. resolve every JUMP / JUMP_IF_FALSE label to that address.

Per IR instruction:

    Assign  dst = src          push src; STORE dst
    BinOp   dst = a op b       push a; push b; ADD|SUB|...; STORE dst
    Index   dst = xs[i]        push xs; push i; INDEX; STORE dst
    Call    dst = tool(args)   push args in order; CALL tool argc; STORE dst
    ParallelCalls              push the args of each call in order; CALL_PARALLEL [(tool, argc) ...]
                               with arg2 = [[line, col] ...] of each member call;
                               STORE the dsts in reverse order (the last result is on top)
    Return  value              push value; RETURN
    Branch  c ? T : F          push c; JUMP_IF_FALSE F; JUMP T  (JUMP omitted when T is the next block)
    Jump    L                  JUMP L                           (omitted when L is the next block)

"push" is PUSH_CONST for a Const and LOAD for a Var. Every BInstr carries the line/col of
the IR instruction it came from (inside a ParallelCalls: the member Call's, except for the
CALL_PARALLEL itself, which carries the group's and lists each member's in arg2, so the VM
logs and reports every call at its own location).
"""

from __future__ import annotations

from . import ast_nodes as ast
from . import ir
from .bytecode import BINARY_OPS, BInstr, BytecodeProgram, BytecodeTask, Op, format_program
from .ir import CFG, Const, Operand, Var

_JUMPS = (Op.JUMP, Op.JUMP_IF_FALSE)


def generate(agent: ast.Agent, cfgs: list[CFG]) -> BytecodeProgram:
    """One BytecodeTask per CFG (in the given order), plus the agent's permits and budget."""
    tasks = {cfg.name: generate_task(cfg) for cfg in cfgs}
    return BytecodeProgram(agent.name, agent.permitted_tools(), agent.budget.calls, tasks)


def generate_task(cfg: CFG) -> BytecodeTask:
    params = [(name, str(t)) for name, t in cfg.params]
    return BytecodeTask(cfg.name, params, str(cfg.return_type), _TaskEmitter(cfg).emit())


def bytecode_artifact(program: BytecodeProgram) -> dict:
    """Phase artifact: the printable listing plus the JSON form of the program."""
    return {"text": format_program(program), "data": program.to_dict()}


class _TaskEmitter:
    def __init__(self, cfg: CFG):
        self.cfg = cfg
        self.code: list[BInstr] = []
        self.addresses: dict[str, int] = {}

    def emit(self) -> list[BInstr]:
        layout = list(self.cfg.blocks)
        for pos, label in enumerate(layout):
            self.addresses[label] = len(self.code)
            next_label = layout[pos + 1] if pos + 1 < len(layout) else None
            for instr in self.cfg.blocks[label].instrs:
                self.emit_instr(instr, next_label)
        self.resolve()
        return self.code

    def resolve(self) -> None:
        """Second pass: replace each symbolic jump target with its block's start address."""
        for instr in self.code:
            if instr.op in _JUMPS:
                instr.arg = self.addresses[instr.arg]

    # ------------------------------------------------------------ first pass

    def put(self, op: Op, src: ir.Instr, arg=None, arg2=None) -> None:
        self.code.append(BInstr(op, arg, arg2, line=src.line, col=src.col))

    def push(self, operand: Operand, src: ir.Instr) -> None:
        if isinstance(operand, Const):
            self.put(Op.PUSH_CONST, src, operand.value)
        elif isinstance(operand, Var):
            self.put(Op.LOAD, src, operand.name)
        else:
            raise TypeError(f"unknown operand {operand!r}")

    def emit_instr(self, instr: ir.Instr, next_label: str | None) -> None:
        if isinstance(instr, ir.Assign):
            self.push(instr.src, instr)
            self.put(Op.STORE, instr, instr.dst.name)
        elif isinstance(instr, ir.BinOp):
            self.push(instr.left, instr)
            self.push(instr.right, instr)
            self.put(BINARY_OPS[instr.op], instr)
            self.put(Op.STORE, instr, instr.dst.name)
        elif isinstance(instr, ir.Index):
            self.push(instr.base, instr)
            self.push(instr.index, instr)
            self.put(Op.INDEX, instr)
            self.put(Op.STORE, instr, instr.dst.name)
        elif isinstance(instr, ir.Call):
            for arg in instr.args:
                self.push(arg, instr)
            self.put(Op.CALL, instr, instr.tool, len(instr.args))
            self.put(Op.STORE, instr, instr.dst.name)
        elif isinstance(instr, ir.ParallelCalls):
            self.emit_parallel(instr)
        elif isinstance(instr, ir.Return):
            self.push(instr.value, instr)
            self.put(Op.RETURN, instr)
        elif isinstance(instr, ir.Branch):
            self.push(instr.cond, instr)
            self.put(Op.JUMP_IF_FALSE, instr, instr.if_false)
            if instr.if_true != next_label:
                self.put(Op.JUMP, instr, instr.if_true)
        elif isinstance(instr, ir.Jump):
            if instr.target != next_label:
                self.put(Op.JUMP, instr, instr.target)
        elif isinstance(instr, ir.Label):
            pass  # labels exist only in the linear listing, never inside a basic block
        else:
            raise TypeError(f"unknown instruction {instr!r}")

    def emit_parallel(self, instr: ir.ParallelCalls) -> None:
        # argument pushes and stores keep each call's own location; the round uses the group's
        for call in instr.calls:
            for arg in call.args:
                self.push(arg, call)
        specs = [(call.tool, len(call.args)) for call in instr.calls]
        locations = [[call.line, call.col] for call in instr.calls]
        self.put(Op.CALL_PARALLEL, instr, specs, locations)
        # results are pushed in call order, so the last call's result is popped first
        for call in reversed(instr.calls):
            self.put(Op.STORE, call, call.dst.name)
