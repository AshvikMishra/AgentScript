"""Parser: tokens -> AST (ast_nodes.Agent), by hand-written recursive descent.

There is one method per grammar rule of the design brief, section 2:

    program      = "agent" IDENT "{" { permit_decl } budget_decl task { task } "}" EOF ;
    permit_decl  = "permit" IDENT { "," IDENT } ";" ;
    budget_decl  = "budget" "calls" "=" INT ";" ;
    task         = "task" IDENT "(" [ param { "," param } ] ")" "->" type block ;
    param        = IDENT ":" type ;
    type         = "string" | "int" | "bool" | "list" "<" type ">" ;
    block        = "{" { statement } "}" ;
    statement    = let_stmt | if_stmt | repeat_stmt | return_stmt | expr_stmt ;
    let_stmt     = "let" IDENT "=" expr ";" ;
    if_stmt      = "if" "(" expr ")" block [ "else" block ] ;
    repeat_stmt  = "repeat" ( INT | IDENT ) block ;
    return_stmt  = "return" expr ";" ;
    expr_stmt    = expr ";" ;
    expr         = equality ;
    equality     = relational { ( "==" | "!=" ) relational } ;
    relational   = additive { ( "<" | "<=" | ">" | ">=" ) additive } ;
    additive     = term { ( "+" | "-" ) term } ;
    term         = postfix { "*" postfix } ;
    postfix      = primary { "[" expr "]" } ;
    primary      = INT | STRING | "true" | "false"
                 | IDENT [ "(" [ expr { "," expr } ] ")" ] | "(" expr ")" ;

The first syntax error raises E201 "expected X, found Y"; there is no recovery.
"""

from __future__ import annotations

from collections.abc import Callable

from . import ast_nodes as ast
from .diagnostics import CompileError, make_error
from .lexer import Token, TokenKind
from .typesys import BOOL, INT, STRING, Type, list_of

K = TokenKind

_VARIABLE_KIND_NAMES = {
    K.IDENT: "identifier",
    K.INT: "integer",
    K.STRING: "string",
    K.EOF: "end of file",
}

_EQUALITY_OPS = {K.EQ, K.NE}
_RELATIONAL_OPS = {K.LT, K.LE, K.GT, K.GE}
_ADDITIVE_OPS = {K.PLUS, K.MINUS}
_TERM_OPS = {K.STAR}
_SIMPLE_TYPES = {K.STRING_T: STRING, K.INT_T: INT, K.BOOL_T: BOOL}


def describe_kind(kind: TokenKind) -> str:
    """How an expected token kind reads in a message: `';'`, `identifier`, ..."""
    return _VARIABLE_KIND_NAMES.get(kind, f"'{kind.value}'")


def describe_token(tok: Token) -> str:
    """How a found token reads in a message: `'return'`, `identifier 'x'`, `integer 42`, ..."""
    if tok.kind is K.IDENT:
        return f"identifier '{tok.text}'"
    if tok.kind is K.INT:
        return f"integer {tok.text}"
    if tok.kind is K.STRING:
        return f"string {tok.text}"
    if tok.kind is K.EOF:
        return "end of file"
    return f"'{tok.text}'"


class Parser:
    def __init__(self, tokens: list[Token]):
        if not tokens or tokens[-1].kind is not K.EOF:
            raise ValueError("token list must end with EOF")
        self.tokens = tokens
        self.pos = 0

    # ------------------------------------------------------------ token helpers

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def check(self, *kinds: TokenKind) -> bool:
        return self.peek().kind in kinds

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind is not K.EOF:  # never step past EOF
            self.pos += 1
        return tok

    def expect(self, kind: TokenKind, what: str | None = None) -> Token:
        if self.check(kind):
            return self.advance()
        raise self.error(what or describe_kind(kind))

    def error(self, expected: str) -> CompileError:
        """E201 at the found token, or just after the previous token when the found token
        is on a later line (a missing `;` is reported at the end of its own line)."""
        found = self.peek()
        line, col = found.line, found.col
        if self.pos > 0:
            prev = self.tokens[self.pos - 1]
            if found.line > prev.line:
                line, col = prev.line, prev.col + len(prev.text)
        return make_error("E201", f"expected {expected}, found {describe_token(found)}", line, col)

    # ------------------------------------------------------------- declarations

    def parse_program(self) -> ast.Agent:
        start = self.expect(K.AGENT)
        name = self.expect(K.IDENT, "agent name").text
        self.expect(K.LBRACE)
        permits: list[ast.Permit] = []
        while self.check(K.PERMIT):
            permits.append(self.parse_permit())
        if not self.check(K.BUDGET):
            raise self.error("'permit' or 'budget'")
        budget = self.parse_budget()
        if not self.check(K.TASK):
            raise self.error("'task'")
        tasks = [self.parse_task()]
        while self.check(K.TASK):
            tasks.append(self.parse_task())
        self.expect(K.RBRACE, "'task' or '}'")
        self.expect(K.EOF)
        return ast.Agent(name, permits, budget, tasks, start.line, start.col)

    def parse_permit(self) -> ast.Permit:
        start = self.expect(K.PERMIT)
        tools = [self._name_ref()]
        while self.check(K.COMMA):
            self.advance()
            tools.append(self._name_ref())
        self.expect(K.SEMI, "',' or ';'")
        return ast.Permit(tools, start.line, start.col)

    def _name_ref(self) -> ast.NameRef:
        tok = self.expect(K.IDENT, "tool name")
        return ast.NameRef(tok.text, tok.line, tok.col)

    def parse_budget(self) -> ast.Budget:
        start = self.expect(K.BUDGET)
        self.expect(K.CALLS)
        self.expect(K.ASSIGN)
        calls = self.expect(K.INT)
        self.expect(K.SEMI)
        return ast.Budget(calls.value, start.line, start.col)

    def parse_task(self) -> ast.Task:
        start = self.expect(K.TASK)
        name = self.expect(K.IDENT, "task name").text
        self.expect(K.LPAREN)
        params: list[ast.Param] = []
        if not self.check(K.RPAREN):
            params.append(self.parse_param())
            while self.check(K.COMMA):
                self.advance()
                params.append(self.parse_param())
            self.expect(K.RPAREN, "',' or ')'")
        else:
            self.advance()
        self.expect(K.ARROW)
        return_type = self.parse_type()
        body = self.parse_block()
        return ast.Task(name, params, return_type, body, start.line, start.col)

    def parse_param(self) -> ast.Param:
        tok = self.expect(K.IDENT, "parameter name")
        self.expect(K.COLON)
        return ast.Param(tok.text, self.parse_type(), tok.line, tok.col)

    def parse_type(self) -> Type:
        tok = self.peek()
        if tok.kind in _SIMPLE_TYPES:
            self.advance()
            return _SIMPLE_TYPES[tok.kind]
        if tok.kind is K.LIST_T:
            self.advance()
            self.expect(K.LT)
            elem = self.parse_type()
            self.expect(K.GT)
            return list_of(elem)
        raise self.error("type")

    # --------------------------------------------------------------- statements

    def parse_block(self) -> ast.Block:
        start = self.expect(K.LBRACE)
        statements: list[ast.Stmt] = []
        while not self.check(K.RBRACE, K.EOF):
            statements.append(self.parse_statement())
        end = self.expect(K.RBRACE)
        return ast.Block(statements, start.line, start.col, end.line, end.col)

    def parse_statement(self) -> ast.Stmt:
        handler: Callable[[], ast.Stmt] | None = {
            K.LET: self.parse_let,
            K.IF: self.parse_if,
            K.REPEAT: self.parse_repeat,
            K.RETURN: self.parse_return,
        }.get(self.peek().kind)
        if handler is not None:
            return handler()
        expr = self.parse_expr()
        self.expect(K.SEMI)
        return ast.ExprStmt(expr, expr.line, expr.col)

    def parse_let(self) -> ast.Let:
        start = self.expect(K.LET)
        name = self.expect(K.IDENT)
        self.expect(K.ASSIGN)
        value = self.parse_expr()
        self.expect(K.SEMI)
        return ast.Let(name.text, value, start.line, start.col, name.line, name.col)

    def parse_if(self) -> ast.If:
        start = self.expect(K.IF)
        self.expect(K.LPAREN)
        cond = self.parse_expr()
        self.expect(K.RPAREN)
        then_block = self.parse_block()
        else_block = None
        if self.check(K.ELSE):
            self.advance()
            else_block = self.parse_block()
        return ast.If(cond, then_block, else_block, start.line, start.col)

    def parse_repeat(self) -> ast.Repeat:
        start = self.expect(K.REPEAT)
        tok = self.peek()
        count: ast.IntLit | ast.Name
        if tok.kind is K.INT:
            count = ast.IntLit(tok.value, tok.line, tok.col)
        elif tok.kind is K.IDENT:
            count = ast.Name(tok.text, tok.line, tok.col)
        else:
            raise self.error("integer or identifier")
        self.advance()
        body = self.parse_block()
        return ast.Repeat(count, body, start.line, start.col)

    def parse_return(self) -> ast.Return:
        start = self.expect(K.RETURN)
        value = self.parse_expr()
        self.expect(K.SEMI)
        return ast.Return(value, start.line, start.col)

    # -------------------------------------------------------------- expressions

    def parse_expr(self) -> ast.Expr:
        return self.parse_equality()

    def _binary_level(self, ops: set[TokenKind], operand: Callable[[], ast.Expr]) -> ast.Expr:
        """Left-associative chain `operand { op operand }`; the node sits at the operator."""
        left = operand()
        while self.check(*ops):
            op = self.advance()
            right = operand()
            left = ast.Binary(op.text, left, right, op.line, op.col)
        return left

    def parse_equality(self) -> ast.Expr:
        return self._binary_level(_EQUALITY_OPS, self.parse_relational)

    def parse_relational(self) -> ast.Expr:
        return self._binary_level(_RELATIONAL_OPS, self.parse_additive)

    def parse_additive(self) -> ast.Expr:
        return self._binary_level(_ADDITIVE_OPS, self.parse_term)

    def parse_term(self) -> ast.Expr:
        return self._binary_level(_TERM_OPS, self.parse_postfix)

    def parse_postfix(self) -> ast.Expr:
        expr = self.parse_primary()
        while self.check(K.LBRACKET):
            bracket = self.advance()
            index = self.parse_expr()
            self.expect(K.RBRACKET)
            expr = ast.Index(expr, index, bracket.line, bracket.col)
        return expr

    def parse_primary(self) -> ast.Expr:
        tok = self.peek()
        if tok.kind is K.INT:
            self.advance()
            return ast.IntLit(tok.value, tok.line, tok.col)
        if tok.kind is K.STRING:
            self.advance()
            return ast.StrLit(tok.value, tok.line, tok.col)
        if tok.kind in (K.TRUE, K.FALSE):
            self.advance()
            return ast.BoolLit(tok.kind is K.TRUE, tok.line, tok.col)
        if tok.kind is K.IDENT:
            self.advance()
            if self.check(K.LPAREN):
                return self._call_args(tok)
            return ast.Name(tok.text, tok.line, tok.col)
        if tok.kind is K.LPAREN:
            self.advance()
            expr = self.parse_expr()
            self.expect(K.RPAREN)
            return expr
        raise self.error("expression")

    def _call_args(self, name: Token) -> ast.Call:
        self.expect(K.LPAREN)
        args: list[ast.Expr] = []
        if self.check(K.RPAREN):
            self.advance()
        else:
            args.append(self.parse_expr())
            while self.check(K.COMMA):
                self.advance()
                args.append(self.parse_expr())
            self.expect(K.RPAREN, "',' or ')'")
        return ast.Call(name.text, args, name.line, name.col)


def parse(tokens: list[Token]) -> ast.Agent:
    """Parse a token list (from lexer.tokenize); raises CompileError E201 on the first error."""
    return Parser(tokens).parse_program()
