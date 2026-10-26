"""Lexer: source text -> list of tokens (always ending in EOF).

Rules (design brief, section 1): whitespace is space, tab, CR and LF; `//` starts a line
comment; lines and columns are 1-based and a tab counts as one column. Operators use the
longest match, except that `>>` is two `>` tokens so `list<list<string>>` closes cleanly.
The first lexical error (E101 unterminated string, E102 illegal character) stops the lexer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .diagnostics import make_error


def _is_surrogate(ch: str) -> bool:
    return len(ch) == 1 and 0xD800 <= ord(ch) <= 0xDFFF


class TokenKind(Enum):
    # Keywords: the value is the lexeme.
    AGENT = "agent"
    PERMIT = "permit"
    BUDGET = "budget"
    CALLS = "calls"
    TASK = "task"
    LET = "let"
    IF = "if"
    ELSE = "else"
    REPEAT = "repeat"
    RETURN = "return"
    TRUE = "true"
    FALSE = "false"
    STRING_T = "string"
    INT_T = "int"
    BOOL_T = "bool"
    LIST_T = "list"
    # Punctuation and operators: the value is the lexeme.
    LBRACE = "{"
    RBRACE = "}"
    LPAREN = "("
    RPAREN = ")"
    LBRACKET = "["
    RBRACKET = "]"
    COMMA = ","
    SEMI = ";"
    COLON = ":"
    ASSIGN = "="
    ARROW = "->"
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    EQ = "=="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    # Tokens with a variable lexeme: placeholder values (they must not collide with keywords).
    IDENT = "<ident>"
    INT = "<int>"
    STRING = "<string>"
    EOF = "<eof>"


_VARIABLE_KINDS = {TokenKind.IDENT, TokenKind.INT, TokenKind.STRING, TokenKind.EOF}

KEYWORDS: dict[str, TokenKind] = {
    k.value: k for k in TokenKind if k not in _VARIABLE_KINDS and k.value.isalpha()
}

# Two-character operators are tried before single characters (longest match).
_TWO_CHAR: dict[str, TokenKind] = {
    k.value: k for k in TokenKind if k not in _VARIABLE_KINDS and len(k.value) == 2 and not k.value.isalpha()
}
_ONE_CHAR: dict[str, TokenKind] = {
    k.value: k for k in TokenKind if k not in _VARIABLE_KINDS and len(k.value) == 1
}

_WHITESPACE = " \t\r\n"
_DIGITS = "0123456789"
_IDENT_START = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_"
_IDENT_CHARS = _IDENT_START + _DIGITS
_ESCAPES = {"n": "\n", "t": "\t"}  # any other escaped char stands for itself


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str  # raw lexeme; strings keep their quotes and escapes; "" for EOF
    value: int | str | None  # int for INT, unescaped str for STRING, else None
    line: int
    col: int

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.name,
            "text": self.text,
            "value": self.value,
            "line": self.line,
            "col": self.col,
        }


class _Lexer:
    def __init__(self, source: str):
        self.src = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list[Token] = []

    def peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.src[i] if i < len(self.src) else ""

    def advance(self) -> str:
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def emit(self, kind: TokenKind, start: int, line: int, col: int, value: int | str | None = None) -> None:
        self.tokens.append(Token(kind, self.src[start : self.pos], value, line, col))

    def run(self) -> list[Token]:
        while self.pos < len(self.src):
            ch = self.peek()
            if ch in _WHITESPACE:
                self.advance()
            elif ch == "/" and self.peek(1) == "/":
                self.skip_comment()
            elif ch in _IDENT_START:
                self.lex_word()
            elif ch in _DIGITS:
                self.lex_int()
            elif ch == '"':
                self.lex_string()
            else:
                self.lex_operator()
        self.tokens.append(Token(TokenKind.EOF, "", None, self.line, self.col))
        return self.tokens

    def skip_comment(self) -> None:
        while self.pos < len(self.src) and self.peek() != "\n":
            self.advance()

    def lex_word(self) -> None:
        start, line, col = self.pos, self.line, self.col
        while self.peek() and self.peek() in _IDENT_CHARS:
            self.advance()
        word = self.src[start : self.pos]
        self.emit(KEYWORDS.get(word, TokenKind.IDENT), start, line, col)

    def lex_int(self) -> None:
        start, line, col = self.pos, self.line, self.col
        while self.peek() and self.peek() in _DIGITS:
            self.advance()
        self.emit(TokenKind.INT, start, line, col, int(self.src[start : self.pos]))

    def lex_string(self) -> None:
        start, line, col = self.pos, self.line, self.col
        self.advance()  # opening quote
        chars: list[str] = []
        while True:
            ch = self.peek()
            if ch in ("", "\n"):
                raise make_error(
                    "E101", "unterminated string: missing closing '\"' before end of line", line, col
                )
            if _is_surrogate(ch):  # cannot be encoded as UTF-8 in any artifact or response
                raise make_error("E102", f"illegal character {ch!r}", self.line, self.col)
            self.advance()
            if ch == '"':
                break
            if ch == "\\":
                nxt = self.peek()
                if _is_surrogate(nxt):
                    raise make_error("E102", f"illegal character {nxt!r}", self.line, self.col)
                if nxt in ("", "\n"):
                    continue  # the loop head reports E101 at the opening quote
                self.advance()
                chars.append(_ESCAPES.get(nxt, nxt))
            else:
                chars.append(ch)
        self.emit(TokenKind.STRING, start, line, col, "".join(chars))

    def lex_operator(self) -> None:
        start, line, col = self.pos, self.line, self.col
        two = self.src[self.pos : self.pos + 2]
        if two in _TWO_CHAR:
            self.advance()
            self.advance()
            self.emit(_TWO_CHAR[two], start, line, col)
            return
        ch = self.peek()
        if ch in _ONE_CHAR:
            self.advance()
            self.emit(_ONE_CHAR[ch], start, line, col)
            return
        raise make_error("E102", f"illegal character {ch!r}", line, col)


def tokenize(source: str) -> list[Token]:
    """Tokenize the whole source; raises CompileError (E101/E102) on the first lexical error."""
    return _Lexer(source).run()


def format_token(tok: Token) -> str:
    """One listing line, e.g. `  6:5   LET        let`."""
    return f"{tok.line:>3}:{tok.col:<4}{tok.kind.name:<11}{tok.text}".rstrip()


def tokens_artifact(tokens: list[Token]) -> dict:
    """The `tokens` phase artifact: a printable listing plus one JSON record per token."""
    return {
        "text": "\n".join(format_token(t) for t in tokens),
        "data": [t.to_dict() for t in tokens],
    }
