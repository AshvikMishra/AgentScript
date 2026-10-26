"""Semantic analysis (F2-F6): scopes, symbols, types, permissions and the static budget.

`analyze(agent)` makes one walk over the AST in source order (scopes, types, permissions;
the first error raises), then checks the static call budget of every task. It sets `.type`
on every expression node and returns a SemanticResult (symbol table, budget per task,
warnings). Scope chain: builtins (the 7 tools) -> agent (tasks) -> task (params) -> blocks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import islice
from typing import Iterator, Union

from . import ast_nodes as ast
from .diagnostics import Diagnostic, PathStep, make_diagnostic, make_error
from .tools import TOOLS
from .typesys import BOOL, INT, STRING, Type

# The E306 path and BudgetInfo.call_sites list at most this many calls, so a huge
# `repeat 1000000` is checked by arithmetic instead of being materialized.
MAX_LISTED_CALLS = 100


# ------------------------------------------------------------------ symbols


@dataclass
class Symbol:
    name: str
    kind: str  # "tool" | "task" | "param" | "variable"
    type: Type  # variable/param type; return type for tools and tasks
    line: int  # declaration position (0:0 for built-in tools)
    col: int
    scope: str  # name of the declaring scope
    params: tuple[Type, ...] | None = None  # parameter types for tools and tasks

    def type_text(self) -> str:
        if self.params is None:
            return str(self.type)
        args = ", ".join(str(p) for p in self.params)
        return f"({args}) -> {self.type}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "type": self.type_text(),
            "line": self.line,
            "col": self.col,
        }


@dataclass
class Scope:
    kind: str  # "builtins" | "agent" | "task" | "block"
    name: str
    parent: Scope | None = field(default=None, repr=False, compare=False)
    symbols: dict[str, Symbol] = field(default_factory=dict)
    children: list[Scope] = field(default_factory=list, repr=False)
    line: int = 0  # the `{` of a block scope; the declaration of a task/agent scope
    col: int = 0

    def child(self, kind: str, name: str, line: int = 0, col: int = 0) -> Scope:
        scope = Scope(kind, name, self, line=line, col=col)
        self.children.append(scope)
        return scope

    def lookup(self, name: str) -> Symbol | None:
        """Walk outward from this scope; None when the name is not visible."""
        scope: Scope | None = self
        while scope is not None:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
        return None

    def declare(self, symbol: Symbol) -> Symbol:
        """Add `symbol`; E302 when its name is already visible (no shadowing)."""
        existing = self.lookup(symbol.name)
        if existing is not None:
            raise make_error(
                "E302",
                f"'{symbol.name}' is already declared ({_describe(existing)}); "
                "names cannot be redeclared or shadowed",
                symbol.line,
                symbol.col,
            )
        symbol.scope = self.name
        self.symbols[symbol.name] = symbol
        return symbol

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "line": self.line,
            "col": self.col,
            "symbols": [s.to_dict() for s in self.symbols.values()],
            "children": [c.to_dict() for c in self.children],
        }


def _task_symbol(task: ast.Task) -> Symbol:
    params = tuple(p.declared_type for p in task.params)
    return Symbol(task.name, "task", task.return_type, task.line, task.col, "", params)


def _describe(sym: Symbol) -> str:
    if sym.kind == "tool":
        return "a built-in tool"
    return f"{sym.kind} at {sym.line}:{sym.col}"


# ------------------------------------------------------------------- result


@dataclass
class BudgetInfo:
    task: str
    worst_path_calls: int
    budget: int
    call_sites: list[tuple[str, int, int]]  # (tool, line, col) along the worst path
    dynamic_loops: bool  # some `repeat x` is counted once (enforced at runtime)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "worst_path_calls": self.worst_path_calls,
            "budget": self.budget,
            "call_sites": [{"tool": t, "line": ln, "col": c} for t, ln, c in self.call_sites],
            "dynamic_loops": self.dynamic_loops,
        }


@dataclass
class SemanticResult:
    root_scope: Scope
    budget: dict[str, BudgetInfo]
    warnings: list[Diagnostic]
    permits: list[str]

    def artifact(self) -> dict:
        data = {
            "scopes": self.root_scope.to_dict(),
            "permits": list(self.permits),
            "budget": [info.to_dict() for info in self.budget.values()],
            "warnings": [w.to_dict() for w in self.warnings],
        }
        return {"text": self._text(), "data": json.loads(json.dumps(data))}

    def _text(self) -> str:
        lines = ["Scopes"]
        _format_scope(self.root_scope, 1, lines)
        lines.append("")
        lines.append("Permitted tools: " + (", ".join(self.permits) or "(none)"))
        lines.append("")
        lines.append("Budget (static worst path per task run)")
        width = max([len("task")] + [len(n) for n in self.budget])
        lines.append(f"  {'task':<{width}}  worst path  budget  check")
        for info in self.budget.values():
            check = "runtime" if info.dynamic_loops else "static"
            lines.append(
                f"  {info.task:<{width}}  {info.worst_path_calls:<10}  {info.budget:<6}  {check}"
            )
            sites = " -> ".join(f"{t}@{ln}:{c}" for t, ln, c in info.call_sites) or "(no calls)"
            if info.worst_path_calls > len(info.call_sites):
                sites += f" -> ... ({info.worst_path_calls - len(info.call_sites)} more)"
            lines.append(f"  {'':<{width}}  path: {sites}")
        for w in self.warnings:
            lines.append(w.format())
        return "\n".join(lines)


def _format_scope(scope: Scope, depth: int, out: list[str]) -> None:
    pad = "  " * depth
    head = f"{pad}{scope.kind} {scope.name}" if scope.kind != "builtins" else f"{pad}builtins"
    if scope.line:
        head += f" @{scope.line}:{scope.col}"
    out.append(head)
    for sym in scope.symbols.values():
        where = f"{sym.line}:{sym.col}" if sym.line else "-"
        out.append(f"{pad}  {sym.name:<12} {sym.kind:<8} {sym.type_text():<28} {where}")
    for child in scope.children:
        _format_scope(child, depth + 1, out)


# --------------------------------------------------------------- the checker


_ARITH_OPS = {"-", "*"}
_REL_OPS = {"<", "<=", ">", ">="}
_EQ_OPS = {"==", "!="}
_EQ_TYPES = {INT, BOOL, STRING}


class _Checker:
    """The source-order walk: scopes, types and permissions. First error raises."""

    def __init__(self, agent: ast.Agent):
        self.agent = agent
        self.builtins = Scope("builtins", "builtins")
        for spec in TOOLS.values():
            self.builtins.declare(Symbol(spec.name, "tool", spec.returns, 0, 0, "", spec.params))
        self.agent_scope = self.builtins.child("agent", agent.name, agent.line, agent.col)
        self.permits: list[str] = []
        self.task: ast.Task | None = None
        self.block_counter = 0

    # ---------------------------------------------------------- declarations

    def check_agent(self) -> None:
        self.check_permits()
        # Task names are hoisted (visible in every task body, also earlier ones), but this
        # pre-pass raises nothing: a bad task name is reported when the walk reaches that
        # task, so errors keep source order (first error wins).
        for task in self.agent.tasks:
            if self.builtins.lookup(task.name) is None and task.name not in self.agent_scope.symbols:
                symbol = _task_symbol(task)
                symbol.scope = self.agent_scope.name
                self.agent_scope.symbols[task.name] = symbol
        for task in self.agent.tasks:
            self.check_task_name(task)
            self.check_task(task)

    def check_task_name(self, task: ast.Task) -> None:
        """E302 when this task is not the hoisted owner of its name (a duplicate or a tool name)."""
        owner = self.agent_scope.symbols.get(task.name)
        if owner is not None and (owner.line, owner.col) == (task.line, task.col):
            return
        self.agent_scope.declare(_task_symbol(task))  # raises E302 against the visible name

    def check_permits(self) -> None:
        seen: dict[str, ast.NameRef] = {}
        for permit in self.agent.permits:
            for ref in permit.tools:
                if ref.name not in TOOLS:
                    raise make_error(
                        "E301",
                        f"unknown tool '{ref.name}' in permit; built-in tools are: "
                        + ", ".join(TOOLS),
                        ref.line,
                        ref.col,
                    )
                if ref.name in seen:
                    first = seen[ref.name]
                    raise make_error(
                        "E302",
                        f"tool '{ref.name}' is already permitted at {first.line}:{first.col}",
                        ref.line,
                        ref.col,
                    )
                seen[ref.name] = ref
                self.permits.append(ref.name)

    def check_task(self, task: ast.Task) -> None:
        self.task = task
        self.block_counter = 0
        task_scope = self.agent_scope.child("task", task.name, task.line, task.col)
        for param in task.params:
            task_scope.declare(
                Symbol(param.name, "param", param.declared_type, param.line, param.col, "")
            )
        if not self.check_block(task.body, task_scope):
            raise make_error(
                "E304",
                f"task '{task.name}' does not return a {task.return_type} on every path",
                task.body.end_line,
                task.body.end_col,
            )

    # ------------------------------------------------------------ statements

    def check_block(self, block: ast.Block, parent: Scope) -> bool:
        """Check a block in a new scope; True when the block always returns."""
        assert self.task is not None
        self.block_counter += 1
        scope = parent.child("block", f"{self.task.name}.{self.block_counter}", block.line, block.col)
        returns = False
        for stmt in block.statements:
            if self.check_stmt(stmt, scope):
                returns = True
        return returns

    def check_stmt(self, stmt: ast.Stmt, scope: Scope) -> bool:
        """Check one statement; True when it always returns."""
        if isinstance(stmt, ast.Let):
            value_type = self.check_expr(stmt.value, scope)  # before declaring: `let x = x;` is E301
            scope.declare(Symbol(stmt.name, "variable", value_type, stmt.name_line, stmt.name_col, ""))
            return False
        if isinstance(stmt, ast.If):
            cond_type = self.check_expr(stmt.cond, scope)
            if cond_type != BOOL:
                raise _mismatch(f"if condition must be bool, found {cond_type}", stmt.cond)
            then_returns = self.check_block(stmt.then_block, scope)
            if stmt.else_block is None:
                return False
            else_returns = self.check_block(stmt.else_block, scope)
            return then_returns and else_returns
        if isinstance(stmt, ast.Repeat):
            self.check_repeat_count(stmt.count, scope)
            self.check_block(stmt.body, scope)
            return False  # the body may run zero times
        if isinstance(stmt, ast.Return):
            assert self.task is not None
            value_type = self.check_expr(stmt.value, scope)
            if value_type != self.task.return_type:
                raise _mismatch(
                    f"task '{self.task.name}' returns {self.task.return_type}, "
                    f"but this value is {value_type}",
                    stmt.value,
                )
            return True
        if isinstance(stmt, ast.ExprStmt):
            self.check_expr(stmt.expr, scope)
            return False
        raise TypeError(f"unknown statement {type(stmt).__name__}")

    def check_repeat_count(self, count: ast.IntLit | ast.Name, scope: Scope) -> None:
        count_type = self.check_expr(count, scope)
        if count_type != INT:
            raise _mismatch(f"repeat count must be int, found {count_type}", count)

    # ----------------------------------------------------------- expressions

    def check_expr(self, expr: ast.Expr, scope: Scope) -> Type:
        """Type `expr` (and its children), store it in `expr.type` and return it."""
        result = self._type_of(expr, scope)
        expr.type = result
        return result

    def _type_of(self, expr: ast.Expr, scope: Scope) -> Type:
        if isinstance(expr, ast.IntLit):
            return INT
        if isinstance(expr, ast.StrLit):
            return STRING
        if isinstance(expr, ast.BoolLit):
            return BOOL
        if isinstance(expr, ast.Name):
            return self.check_name(expr, scope)
        if isinstance(expr, ast.Call):
            return self.check_call(expr, scope)
        if isinstance(expr, ast.Index):
            return self.check_index(expr, scope)
        if isinstance(expr, ast.Binary):
            return self.check_binary(expr, scope)
        raise TypeError(f"unknown expression {type(expr).__name__}")

    def check_name(self, expr: ast.Name, scope: Scope) -> Type:
        sym = scope.lookup(expr.name)
        if sym is None:
            raise make_error("E301", f"undeclared variable '{expr.name}'", expr.line, expr.col)
        if sym.kind == "tool":
            raise make_error(
                "E301",
                f"'{expr.name}' is a built-in tool, not a variable; call it as {expr.name}(...)",
                expr.line,
                expr.col,
            )
        if sym.kind == "task":
            raise make_error(
                "E301", f"'{expr.name}' is a task, not a variable", expr.line, expr.col
            )
        return sym.type

    def check_call(self, call: ast.Call, scope: Scope) -> Type:
        sym = scope.lookup(call.tool)
        if sym is None or sym.kind != "tool":
            hint = ""
            if sym is not None and sym.kind == "task":
                hint = " ('" + call.tool + "' is a task; tasks cannot call tasks)"
            elif sym is not None:
                hint = f" ('{call.tool}' is a {sym.kind})"
            raise make_error(
                "E301", f"unknown tool '{call.tool}'{hint}", call.line, call.col
            )
        if call.tool not in self.permits:
            raise make_error(
                "E305",
                f"tool '{call.tool}' is not permitted; add it to a permit declaration",
                call.line,
                call.col,
            )
        spec = TOOLS[call.tool]
        arg_types = [self.check_expr(arg, scope) for arg in call.args]
        if len(arg_types) != len(spec.params):
            raise make_error(
                "E303",
                f"{call.tool} expects {len(spec.params)} argument"
                f"{'' if len(spec.params) == 1 else 's'} {spec.signature()}, "
                f"found {len(arg_types)}",
                call.line,
                call.col,
            )
        for n, (arg, found, expected) in enumerate(zip(call.args, arg_types, spec.params), 1):
            if found != expected:
                raise _mismatch(
                    f"argument {n} of {call.tool} must be {expected}, found {found}", arg
                )
        return spec.returns

    def check_index(self, expr: ast.Index, scope: Scope) -> Type:
        base_type = self.check_expr(expr.base, scope)
        index_type = self.check_expr(expr.index, scope)
        if not base_type.is_list:
            raise _mismatch(f"only lists can be indexed, found {base_type}", expr)
        if index_type != INT:
            raise _mismatch(f"list index must be int, found {index_type}", expr.index)
        assert base_type.elem is not None
        return base_type.elem

    def check_binary(self, expr: ast.Binary, scope: Scope) -> Type:
        left = self.check_expr(expr.left, scope)
        right = self.check_expr(expr.right, scope)
        op = expr.op
        if op == "+":
            if left == right and left in (INT, STRING):
                return left
            expected = "int + int or string + string"
        elif op in _ARITH_OPS:
            if left == INT and right == INT:
                return INT
            expected = f"int {op} int"
        elif op in _REL_OPS:
            if left == INT and right == INT:
                return BOOL
            expected = f"int {op} int"
        elif op in _EQ_OPS:
            if left == right and left in _EQ_TYPES:
                return BOOL
            expected = "two operands of the same type (int, bool or string)"
        else:
            raise TypeError(f"unknown operator {op}")
        raise _mismatch(f"operator '{op}' expects {expected}, found {left} {op} {right}", expr)


def _mismatch(message: str, node: ast.Expr) -> Exception:
    return make_error("E303", message, node.line, node.col)  # type: ignore[attr-defined]


# ------------------------------------------------------------------- budget

# A worst path is a tree so `repeat n` never copies its body n times:
# a Call is one call, a _Seq is its parts in order, a _Rep is its body `times` times.


@dataclass(frozen=True)
class _Seq:
    parts: tuple[_PathNode, ...]
    count: int


@dataclass(frozen=True)
class _Rep:
    times: int
    body: _PathNode
    count: int


_PathNode = Union[ast.Call, _Seq, _Rep]

_EMPTY = _Seq((), 0)


def _count(node: _PathNode) -> int:
    return 1 if isinstance(node, ast.Call) else node.count


def _seq(*parts: _PathNode) -> _Seq:
    kept = tuple(p for p in parts if _count(p) > 0)
    return _Seq(kept, sum(_count(p) for p in kept))


def _iter_calls(node: _PathNode) -> Iterator[ast.Call]:
    if isinstance(node, ast.Call):
        yield node
    elif isinstance(node, _Seq):
        for part in node.parts:
            yield from _iter_calls(part)
    else:
        for _ in range(node.times):
            yield from _iter_calls(node.body)


def _nth_call(node: _PathNode, i: int) -> ast.Call:
    """The call at 0-based position `i` of the path (requires i < _count(node))."""
    while not isinstance(node, ast.Call):
        if isinstance(node, _Rep):
            i %= _count(node.body)
            node = node.body
            continue
        for part in node.parts:
            if i < _count(part):
                node = part
                break
            i -= _count(part)
    return node


class _BudgetWalker:
    """Builds the structural worst path of one task (brief section 3, Budget)."""

    def __init__(self) -> None:
        self.warnings: list[Diagnostic] = []

    def block(self, block: ast.Block) -> _Seq:
        return _seq(*(self.stmt(s) for s in block.statements))

    def stmt(self, stmt: ast.Stmt) -> _PathNode:
        if isinstance(stmt, ast.Let):
            return self.expr(stmt.value)
        if isinstance(stmt, ast.Return):
            return self.expr(stmt.value)
        if isinstance(stmt, ast.ExprStmt):
            return self.expr(stmt.expr)
        if isinstance(stmt, ast.If):
            cond = self.expr(stmt.cond)
            then = self.block(stmt.then_block)
            other = self.block(stmt.else_block) if stmt.else_block is not None else _EMPTY
            longer = then if _count(then) >= _count(other) else other  # ties pick `then`
            return _seq(cond, longer)
        if isinstance(stmt, ast.Repeat):
            body = self.block(stmt.body)
            if isinstance(stmt.count, ast.IntLit):
                times = max(stmt.count.value, 0)
                if times == 0 or body.count == 0:
                    return _EMPTY
                return _Rep(times, body, times * body.count)
            self.warnings.append(
                make_diagnostic(
                    "W306",
                    f"repeat count '{stmt.count.name}' is not a literal; "
                    "the budget for this loop is enforced at runtime",
                    stmt.count.line,
                    stmt.count.col,
                )
            )
            return body
        raise TypeError(f"unknown statement {type(stmt).__name__}")

    def expr(self, expr: ast.Expr) -> _PathNode:
        if isinstance(expr, ast.Call):
            return _seq(*(self.expr(a) for a in expr.args), expr)  # arguments run first
        if isinstance(expr, ast.Binary):
            return _seq(self.expr(expr.left), self.expr(expr.right))
        if isinstance(expr, ast.Index):
            return _seq(self.expr(expr.base), self.expr(expr.index))
        return _EMPTY


def _has_dynamic_repeat(block: ast.Block) -> bool:
    for stmt in block.statements:
        if isinstance(stmt, ast.Repeat):
            if isinstance(stmt.count, ast.Name) or _has_dynamic_repeat(stmt.body):
                return True
        elif isinstance(stmt, ast.If):
            if _has_dynamic_repeat(stmt.then_block):
                return True
            if stmt.else_block is not None and _has_dynamic_repeat(stmt.else_block):
                return True
    return False


def check_budget(task: ast.Task, budget: int) -> tuple[BudgetInfo, list[Diagnostic]]:
    """Worst-path call count of `task`; E306 at the (budget+1)-th call when it is over."""
    walker = _BudgetWalker()
    path = walker.block(task.body)
    listed = list(islice(_iter_calls(path), MAX_LISTED_CALLS))
    if path.count > budget:
        culprit = _nth_call(path, budget)
        steps = [
            PathStep(c.line, c.col, f"call {n}: {c.tool}" + (" (over budget)" if n == budget + 1 else ""))
            for n, c in enumerate(listed, 1)
        ]
        if budget >= len(listed):  # the culprit lies beyond the listed prefix
            steps.append(PathStep(culprit.line, culprit.col, f"call {budget + 1}: {culprit.tool} (over budget)"))
        if path.count > len(listed):
            steps.append(
                PathStep(culprit.line, culprit.col, f"... {path.count - len(listed)} more calls on this path")
            )
        raise make_error(
            "E306",
            f"task '{task.name}' may make {path.count} tool call"
            f"{'' if path.count == 1 else 's'} on its worst path, but the budget is {budget}",
            culprit.line,
            culprit.col,
            steps,
        )
    info = BudgetInfo(
        task.name,
        path.count,
        budget,
        [(c.tool, c.line, c.col) for c in listed],
        _has_dynamic_repeat(task.body),
    )
    return info, walker.warnings


# --------------------------------------------------------------------- entry


def analyze(agent: ast.Agent) -> SemanticResult:
    """Check `agent` (sets `.type` on every Expr); raises CompileError E301-E306."""
    checker = _Checker(agent)
    checker.check_agent()
    budgets: dict[str, BudgetInfo] = {}
    warnings: list[Diagnostic] = []
    for task in agent.tasks:
        info, task_warnings = check_budget(task, agent.budget.calls)
        budgets[task.name] = info
        warnings.extend(task_warnings)
    return SemanticResult(checker.builtins, budgets, warnings, checker.permits)
