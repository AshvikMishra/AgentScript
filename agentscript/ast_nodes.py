"""AST node types. The parser builds them; semantic analysis fills in `Expr.type`.

Positions (`line`, `col`, 1-based) point at the node's main token:
literals and names -> the token itself; Call -> the tool name; Index -> the `[`;
Binary -> the operator; statements -> their keyword (`let`, `if`, `repeat`, `return`);
ExprStmt -> its expression; Task -> the `task` keyword; Block -> the `{`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass

from .typesys import Type


# ---------------------------------------------------------------- expressions


@dataclass
class Expr:
    pass


@dataclass
class IntLit(Expr):
    value: int
    line: int
    col: int
    type: Type | None = field(default=None, kw_only=True)


@dataclass
class StrLit(Expr):
    value: str  # unescaped value
    line: int
    col: int
    type: Type | None = field(default=None, kw_only=True)


@dataclass
class BoolLit(Expr):
    value: bool
    line: int
    col: int
    type: Type | None = field(default=None, kw_only=True)


@dataclass
class Name(Expr):
    name: str
    line: int
    col: int
    type: Type | None = field(default=None, kw_only=True)


@dataclass
class Call(Expr):
    tool: str
    args: list[Expr]
    line: int
    col: int
    type: Type | None = field(default=None, kw_only=True)


@dataclass
class Index(Expr):
    base: Expr
    index: Expr
    line: int
    col: int
    type: Type | None = field(default=None, kw_only=True)


@dataclass
class Binary(Expr):
    op: str  # "+" "-" "*" "==" "!=" "<" "<=" ">" ">="
    left: Expr
    right: Expr
    line: int
    col: int
    type: Type | None = field(default=None, kw_only=True)


# ----------------------------------------------------------------- statements


@dataclass
class Stmt:
    pass


@dataclass
class Block:
    statements: list[Stmt]
    line: int  # the `{`
    col: int
    end_line: int  # the `}`
    end_col: int


@dataclass
class Let(Stmt):
    name: str
    value: Expr
    line: int  # the `let` keyword
    col: int
    name_line: int  # the identifier (E302 points here)
    name_col: int


@dataclass
class If(Stmt):
    cond: Expr
    then_block: Block
    else_block: Block | None
    line: int
    col: int


@dataclass
class Repeat(Stmt):
    count: IntLit | Name  # an INT literal or a variable of type int
    body: Block
    line: int
    col: int


@dataclass
class Return(Stmt):
    value: Expr
    line: int
    col: int


@dataclass
class ExprStmt(Stmt):
    expr: Expr
    line: int
    col: int


# ---------------------------------------------------------------- declarations


@dataclass
class NameRef:
    """A tool name inside a `permit` declaration."""

    name: str
    line: int
    col: int


@dataclass
class Permit:
    tools: list[NameRef]
    line: int
    col: int


@dataclass
class Budget:
    calls: int
    line: int
    col: int


@dataclass
class Param:
    name: str
    declared_type: Type
    line: int
    col: int


@dataclass
class Task:
    name: str
    params: list[Param]
    return_type: Type
    body: Block
    line: int
    col: int


@dataclass
class Agent:
    """The root of the AST (one agent per file)."""

    name: str
    permits: list[Permit]
    budget: Budget
    tasks: list[Task]
    line: int
    col: int

    def permitted_tools(self) -> list[str]:
        return [ref.name for p in self.permits for ref in p.tools]


# ------------------------------------------------------------------- printing


def ast_to_dict(node: object) -> object:
    """JSON-ready form: {"node": ClassName, field: value, ...}; Type values become strings."""
    if isinstance(node, Type):
        return str(node)
    if isinstance(node, list):
        return [ast_to_dict(n) for n in node]
    if is_dataclass(node):
        out: dict[str, object] = {"node": type(node).__name__}
        for f in fields(node):
            value = getattr(node, f.name)
            if f.name == "type" and value is None:
                continue
            out[f.name] = ast_to_dict(value)
        return out
    return node


_POSITION_FIELDS = {"line", "col", "end_line", "end_col", "name_line", "name_col"}


def format_ast(node: object, indent: int = 0) -> str:
    """Indented tree, one node per line, e.g.

    Agent Assistant @1:1
      Permit @2:3 [web_search, llm]
      ...
          Let raw @6:5
            Call web_search : list<string> @6:15
              Name topic : string @6:26
    """
    pad = "  " * indent
    if isinstance(node, list):
        return "\n".join(format_ast(n, indent) for n in node)
    if not is_dataclass(node):
        return f"{pad}{node!r}"

    kind = type(node).__name__
    scalars: list[str] = []
    children: list[tuple[str, object]] = []
    for f in fields(node):
        if f.name in _POSITION_FIELDS or f.name == "type":
            continue
        value = getattr(node, f.name)
        if isinstance(value, Type):
            scalars.append(f"{f.name}={value}")
        elif isinstance(value, list) and value and all(isinstance(v, NameRef) for v in value):
            scalars.append("[" + ", ".join(v.name for v in value) + "]")
        elif is_dataclass(value) or isinstance(value, list):
            children.append((f.name, value))
        elif value is not None:
            scalars.append(repr(value) if isinstance(value, str) and kind == "StrLit" else str(value))
    head = f"{pad}{kind}"
    if scalars:
        head += " " + " ".join(scalars)
    node_type = getattr(node, "type", None)
    if isinstance(node_type, Type):
        head += f" : {node_type}"
    if hasattr(node, "line"):
        head += f" @{node.line}:{node.col}"

    lines = [head]
    for name, value in children:
        if isinstance(value, list):
            if not value:
                continue
            if name not in ("statements", "args", "tasks", "permits", "params"):
                lines.append(f"{pad}  {name}:")
            lines.append(format_ast(value, indent + 1))
        else:
            if name in ("then_block", "else_block", "body", "budget"):
                lines.append(f"{pad}  {name}:")
                lines.append(format_ast(value, indent + 2))
            else:
                lines.append(format_ast(value, indent + 1))
    return "\n".join(lines)
