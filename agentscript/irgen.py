"""IR generation: lower a (semantically valid) AST to linear three-address code per task.

Lowering rules (design brief section 5):

- temps `t1, t2, ...` and labels `L1, L2, ...` are numbered per task in creation order;
- a user variable whose name was already used earlier in the same task (a sibling scope;
  shadowing is illegal) is renamed `name.2`, `name.3`, ... so it has one static definition;
- `let x = <call|binop|index>` writes straight into `x`; `let x = <name|literal>` emits Assign;
- literals and names are operands, not instructions;
- `if`:     if c goto Lthen else Lelse|Lend; Lthen: ...; goto Lend; [Lelse: ...; goto Lend;] Lend:
  (no `goto Lend` after a block ending in Return; `Lend:` only when something jumps to it);
- `repeat`: k = 0; n = N; goto Lhead; Lhead: c = k < n; if c goto Lbody else Lexit;
            Lbody: ...; k = k + 1; goto Lhead; Lexit:

irgen does its own scoping and does not depend on semantic.py.
"""

from __future__ import annotations

import re

from . import ast_nodes as ast
from . import ir
from .ir import Const, IRFunction, Operand, Var

_TEMP_RE = re.compile(r"t[0-9]+")


def lower(agent: ast.Agent) -> list[IRFunction]:
    """One IRFunction per task, in task order."""
    return [_TaskLowerer(task).lower() for task in agent.tasks]


def ir_artifact(fns: list[IRFunction]) -> dict:
    """Phase artifact: the printable listing plus a JSON form of every instruction."""
    return {
        "text": "\n\n".join(ir.format_function(fn) for fn in fns),
        "data": [
            {
                "name": fn.name,
                "params": [{"name": n, "type": str(t)} for n, t in fn.params],
                "return_type": str(fn.return_type),
                "instrs": [instr_to_dict(i) for i in fn.instrs],
            }
            for fn in fns
        ],
    }


def instr_to_dict(instr: ir.Instr) -> dict:
    return {
        "text": ir.format_instr(instr),
        "op": type(instr).__name__,
        "line": instr.line,
        "col": instr.col,
    }


def _declared_names(block: ast.Block) -> set[str]:
    """Every `let` name in a block, recursively (used to keep temps from colliding)."""
    names: set[str] = set()
    for stmt in block.statements:
        if isinstance(stmt, ast.Let):
            names.add(stmt.name)
        elif isinstance(stmt, ast.If):
            names |= _declared_names(stmt.then_block)
            if stmt.else_block is not None:
                names |= _declared_names(stmt.else_block)
        elif isinstance(stmt, ast.Repeat):
            names |= _declared_names(stmt.body)
    return names


class _TaskLowerer:
    def __init__(self, task: ast.Task):
        self.task = task
        self.instrs: list[ir.Instr] = []
        self.temp_count = 0
        self.label_count = 0
        # A user may name a variable `t3`; such names are never handed out as temps.
        user_names = {p.name for p in task.params} | _declared_names(task.body)
        self.reserved = {n for n in user_names if _TEMP_RE.fullmatch(n)}
        self.uses: dict[str, int] = {}  # source name -> how many times declared so far
        self.scopes: list[dict[str, str]] = []  # source name -> IR name

    # ------------------------------------------------------------ helpers

    def lower(self) -> IRFunction:
        params = {}
        for p in self.task.params:
            params[p.name] = self.declare(p.name)
        self.scopes.append(params)
        self.lower_block(self.task.body)
        self.scopes.pop()
        return IRFunction(
            self.task.name,
            [(p.name, p.declared_type) for p in self.task.params],
            self.task.return_type,
            self.instrs,
        )

    def emit(self, instr: ir.Instr) -> None:
        self.instrs.append(instr)

    def new_temp(self) -> Var:
        while True:
            self.temp_count += 1
            name = f"t{self.temp_count}"
            if name not in self.reserved:
                return Var(name)

    def new_label(self) -> str:
        self.label_count += 1
        return f"L{self.label_count}"

    def declare(self, name: str) -> str:
        n = self.uses.get(name, 0) + 1
        self.uses[name] = n
        return name if n == 1 else f"{name}.{n}"

    def resolve(self, name: str) -> str:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise KeyError(f"irgen: undeclared name {name!r} (AST not semantically valid)")

    def ends_with_return(self) -> bool:
        return bool(self.instrs) and isinstance(self.instrs[-1], ir.Return)

    # --------------------------------------------------------- statements

    def lower_block(self, block: ast.Block) -> None:
        self.scopes.append({})
        for stmt in block.statements:
            self.lower_stmt(stmt)
        self.scopes.pop()

    def lower_stmt(self, stmt: ast.Stmt) -> None:
        if isinstance(stmt, ast.Let):
            self.lower_let(stmt)
        elif isinstance(stmt, ast.If):
            self.lower_if(stmt)
        elif isinstance(stmt, ast.Repeat):
            self.lower_repeat(stmt)
        elif isinstance(stmt, ast.Return):
            value = self.lower_expr(stmt.value)
            self.emit(ir.Return(value, line=stmt.line, col=stmt.col))
        elif isinstance(stmt, ast.ExprStmt):
            self.lower_expr(stmt.expr)
        else:
            raise TypeError(f"irgen: unknown statement {stmt!r}")

    def lower_let(self, stmt: ast.Let) -> None:
        if isinstance(stmt.value, (ast.Call, ast.Binary, ast.Index)):
            # The initializer cannot mention the new name (no shadowing), so declaring it
            # first is safe and lets the instruction write straight into the variable.
            dst = Var(self.declare(stmt.name))
            self.lower_expr(stmt.value, dst)
        else:
            src = self.lower_expr(stmt.value)
            dst = Var(self.declare(stmt.name))
            self.emit(ir.Assign(dst, src, line=stmt.line, col=stmt.col))
        self.scopes[-1][stmt.name] = dst.name

    def lower_if(self, stmt: ast.If) -> None:
        pos = {"line": stmt.line, "col": stmt.col}
        then_label = self.new_label()
        else_label = self.new_label() if stmt.else_block is not None else None
        end_label = self.new_label()
        end_used = else_label is None  # the false edge jumps straight to Lend

        cond = self.lower_expr(stmt.cond)
        self.emit(ir.Branch(cond, then_label, else_label or end_label, **pos))

        self.emit(ir.Label(then_label, **pos))
        self.lower_block(stmt.then_block)
        if not self.ends_with_return():
            self.emit(ir.Jump(end_label, **pos))
            end_used = True

        if stmt.else_block is not None:
            self.emit(ir.Label(else_label, **pos))
            self.lower_block(stmt.else_block)
            if not self.ends_with_return():
                self.emit(ir.Jump(end_label, **pos))
                end_used = True

        if end_used:
            self.emit(ir.Label(end_label, **pos))

    def lower_repeat(self, stmt: ast.Repeat) -> None:
        pos = {"line": stmt.line, "col": stmt.col}
        counter = self.new_temp()
        limit = self.new_temp()
        head, body, exit_ = self.new_label(), self.new_label(), self.new_label()

        self.emit(ir.Assign(counter, Const(0), **pos))
        self.emit(ir.Assign(limit, self.lower_expr(stmt.count), **pos))
        self.emit(ir.Jump(head, **pos))

        self.emit(ir.Label(head, **pos))
        cond = self.new_temp()
        self.emit(ir.BinOp(cond, "<", counter, limit, **pos))
        self.emit(ir.Branch(cond, body, exit_, **pos))

        self.emit(ir.Label(body, **pos))
        self.lower_block(stmt.body)
        self.emit(ir.BinOp(counter, "+", counter, Const(1), **pos))
        self.emit(ir.Jump(head, **pos))

        self.emit(ir.Label(exit_, **pos))

    # -------------------------------------------------------- expressions

    def lower_expr(self, expr: ast.Expr, dst: Var | None = None) -> Operand:
        """Emit code for `expr` and return the operand holding its value.

        `dst` (only for Call/Binary/Index) is the variable to write instead of a fresh temp.
        """
        if isinstance(expr, (ast.IntLit, ast.StrLit, ast.BoolLit)):
            return Const(expr.value)
        if isinstance(expr, ast.Name):
            return Var(self.resolve(expr.name))
        pos = {"line": expr.line, "col": expr.col}
        if isinstance(expr, ast.Call):
            args = [self.lower_expr(a) for a in expr.args]
            dst = dst or self.new_temp()
            self.emit(ir.Call(dst, expr.tool, args, **pos))
            return dst
        if isinstance(expr, ast.Binary):
            left = self.lower_expr(expr.left)
            right = self.lower_expr(expr.right)
            dst = dst or self.new_temp()
            self.emit(ir.BinOp(dst, expr.op, left, right, **pos))
            return dst
        if isinstance(expr, ast.Index):
            base = self.lower_expr(expr.base)
            index = self.lower_expr(expr.index)
            dst = dst or self.new_temp()
            self.emit(ir.Index(dst, base, index, **pos))
            return dst
        raise TypeError(f"irgen: unknown expression {expr!r}")
