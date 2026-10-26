"""Lexer tests: token kinds, positions, values, comments, escapes and E101/E102."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscript.diagnostics import CompileError
from agentscript.lexer import KEYWORDS, Token, TokenKind, tokenize, tokens_artifact

K = TokenKind
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text())


def kinds(source: str) -> list[TokenKind]:
    return [t.kind for t in tokenize(source)]


def lex_error(source: str) -> tuple[str, int, int, str]:
    with pytest.raises(CompileError) as info:
        tokenize(source)
    d = info.value.diagnostic
    assert d.phase == "lexer"
    return d.code, d.line, d.col, d.message


# ------------------------------------------------------------------ basics


def test_empty_source_is_only_eof():
    toks = tokenize("")
    assert toks == [Token(K.EOF, "", None, 1, 1)]


def test_whitespace_only_eof_position():
    toks = tokenize("  \n\t x")
    assert [t.kind for t in toks] == [K.IDENT, K.EOF]
    assert (toks[0].line, toks[0].col) == (2, 3)  # tab counts as one column
    assert (toks[1].line, toks[1].col) == (2, 4)


def test_eof_after_trailing_newline():
    toks = tokenize("x\n")
    assert (toks[-1].line, toks[-1].col) == (2, 1)


def test_every_keyword():
    words = "agent permit budget calls task let if else repeat return true false string int bool list"
    expected = [
        K.AGENT, K.PERMIT, K.BUDGET, K.CALLS, K.TASK, K.LET, K.IF, K.ELSE, K.REPEAT,
        K.RETURN, K.TRUE, K.FALSE, K.STRING_T, K.INT_T, K.BOOL_T, K.LIST_T, K.EOF,
    ]
    assert kinds(words) == expected
    assert set(KEYWORDS) == set(words.split())


def test_keyword_values_are_none():
    toks = tokenize("true false let")
    assert all(t.value is None for t in toks)


def test_identifiers():
    toks = tokenize("x _y abc123 letter iffy Agent __")
    assert all(t.kind is K.IDENT for t in toks[:-1])
    assert [t.text for t in toks[:-1]] == ["x", "_y", "abc123", "letter", "iffy", "Agent", "__"]
    assert all(t.value is None for t in toks[:-1])


def test_integers_have_int_values():
    toks = tokenize("0 42 007 12345678901234567890")
    assert [t.kind for t in toks[:-1]] == [K.INT] * 4
    assert [t.value for t in toks[:-1]] == [0, 42, 7, 12345678901234567890]
    assert [t.text for t in toks[:-1]] == ["0", "42", "007", "12345678901234567890"]


def test_int_followed_by_ident_splits():
    toks = tokenize("12ab")
    assert [(t.kind, t.text) for t in toks[:-1]] == [(K.INT, "12"), (K.IDENT, "ab")]


def test_all_punctuation_and_operators():
    src = "{ } ( ) [ ] , ; : = -> + - * == != < <= > >="
    assert kinds(src) == [
        K.LBRACE, K.RBRACE, K.LPAREN, K.RPAREN, K.LBRACKET, K.RBRACKET, K.COMMA, K.SEMI,
        K.COLON, K.ASSIGN, K.ARROW, K.PLUS, K.MINUS, K.STAR, K.EQ, K.NE, K.LT, K.LE, K.GT,
        K.GE, K.EOF,
    ]


def test_longest_match_without_spaces():
    assert kinds("a<=b>=c==d!=e->f") == [
        K.IDENT, K.LE, K.IDENT, K.GE, K.IDENT, K.EQ, K.IDENT, K.NE, K.IDENT, K.ARROW, K.IDENT, K.EOF,
    ]
    assert kinds("===") == [K.EQ, K.ASSIGN, K.EOF]
    assert kinds("a--b") == [K.IDENT, K.MINUS, K.MINUS, K.IDENT, K.EOF]


def test_double_greater_is_two_tokens():
    toks = tokenize("list<list<string>>")
    assert [t.kind for t in toks] == [K.LIST_T, K.LT, K.LIST_T, K.LT, K.STRING_T, K.GT, K.GT, K.EOF]
    assert [t.col for t in toks[-3:-1]] == [17, 18]


def test_positions_are_one_based():
    toks = tokenize("agent A {\n  permit llm;\n}")
    pos = [(t.kind, t.line, t.col) for t in toks]
    assert pos == [
        (K.AGENT, 1, 1), (K.IDENT, 1, 7), (K.LBRACE, 1, 9),
        (K.PERMIT, 2, 3), (K.IDENT, 2, 10), (K.SEMI, 2, 13),
        (K.RBRACE, 3, 1), (K.EOF, 3, 2),
    ]


def test_carriage_return_is_whitespace():
    toks = tokenize("a\r\nb")
    assert [(t.text, t.line, t.col) for t in toks[:-1]] == [("a", 1, 1), ("b", 2, 1)]


# ---------------------------------------------------------------- comments


def test_line_comments_are_skipped():
    toks = tokenize("let x = 1; // a comment with \"quotes\" and # @ !\nreturn x;")
    assert [t.text for t in toks[:-1]] == ["let", "x", "=", "1", ";", "return", "x", ";"]
    assert (toks[5].line, toks[5].col) == (2, 1)


def test_comment_at_end_of_file():
    assert kinds("x // trailing") == [K.IDENT, K.EOF]


def test_comment_only_file():
    toks = tokenize("// nothing here")
    assert [t.kind for t in toks] == [K.EOF]


def test_comment_directly_after_token():
    assert kinds("a//b") == [K.IDENT, K.EOF]


# ----------------------------------------------------------------- strings


def test_simple_string():
    (tok, eof) = tokenize('"hello world"')
    assert tok.kind is K.STRING
    assert tok.text == '"hello world"'
    assert tok.value == "hello world"
    assert (eof.line, eof.col) == (1, 14)


def test_empty_string():
    tok = tokenize('""')[0]
    assert tok.text == '""' and tok.value == ""


@pytest.mark.parametrize(
    "raw, value",
    [
        (r'"a\nb"', "a\nb"),
        (r'"a\tb"', "a\tb"),
        (r'"say \"hi\""', 'say "hi"'),
        (r'"back\\slash"', "back\\slash"),
        (r'"\q"', "q"),
        (r'"\\n"', "\\n"),
        (r'"\/"', "/"),
    ],
)
def test_string_escapes(raw: str, value: str):
    tok = tokenize(raw)[0]
    assert tok.kind is K.STRING
    assert tok.text == raw  # text keeps the raw lexeme
    assert tok.value == value


def test_string_may_contain_comment_and_illegal_chars():
    tok = tokenize('"// not a comment # @ !"')[0]
    assert tok.value == "// not a comment # @ !"


def test_position_after_string_with_escapes():
    toks = tokenize(r'"a\"b" x')
    assert (toks[1].line, toks[1].col) == (1, 8)


def test_unterminated_string_at_end_of_line():
    code, line, col, msg = lex_error('let s = "abc;\nreturn s;')
    assert (code, line, col) == ("E101", 1, 9)
    assert "unterminated string" in msg


def test_unterminated_string_at_eof():
    assert lex_error('  "abc')[:3] == ("E101", 1, 3)


def test_escaped_quote_does_not_close():
    assert lex_error(r'x = "abc\"')[:3] == ("E101", 1, 5)


def test_backslash_before_newline_is_unterminated():
    assert lex_error('"abc\\\n"')[:3] == ("E101", 1, 1)


def test_backslash_at_eof_is_unterminated():
    assert lex_error('"abc\\')[:3] == ("E101", 1, 1)


# ---------------------------------------------------------- illegal chars


@pytest.mark.parametrize("ch", ["#", "@", "!", "&", "/", "%", "$", "|", "'", "?", ".", "é"])
def test_illegal_characters(ch: str):
    code, line, col, msg = lex_error(f"let x\n  = 1 {ch} 2;")
    assert (code, line, col) == ("E102", 2, 7)
    assert repr(ch) in msg


def test_bang_alone_is_illegal_but_ne_is_fine():
    assert kinds("a != b") == [K.IDENT, K.NE, K.IDENT, K.EOF]
    assert lex_error("a ! b")[:3] == ("E102", 1, 3)


def test_single_slash_is_illegal():
    assert lex_error("a / b")[:3] == ("E102", 1, 3)


def test_unicode_letters_are_not_identifiers():
    assert lex_error("café")[:3] == ("E102", 1, 4)


def test_first_lexical_error_wins():
    assert lex_error('# "abc')[:3] == ("E102", 1, 1)
    assert lex_error('"abc\n#')[:3] == ("E101", 1, 1)


# ---------------------------------------------------------------- artifact


def test_tokens_artifact_text_and_data():
    art = tokens_artifact(tokenize('let x = "a\\n";\n'))
    lines = art["text"].split("\n")
    assert lines[0] == "  1:1   LET        let"
    assert lines[1] == "  1:5   IDENT      x"
    assert lines[3] == '  1:9   STRING     "a\\n"'
    assert lines[-1] == "  2:1   EOF"
    assert art["data"][3] == {"kind": "STRING", "text": '"a\\n"', "value": "a\n", "line": 1, "col": 9}
    assert art["data"][-1] == {"kind": "EOF", "text": "", "value": None, "line": 2, "col": 1}
    json.dumps(art)  # JSON-ready


def test_tokens_artifact_matches_brief_format():
    src = (EXAMPLES / "valid_report.as").read_text()
    text = tokens_artifact(tokenize(src))["text"]
    assert "  6:5   LET        let" in text.split("\n")


def test_tokenize_is_deterministic():
    src = (EXAMPLES / "valid_report.as").read_text()
    assert tokenize(src) == tokenize(src)


# ---------------------------------------------------------------- examples


@pytest.mark.parametrize("entry", MANIFEST, ids=[e["file"] for e in MANIFEST])
def test_examples_lex_per_manifest(entry: dict):
    source = (EXAMPLES / entry["file"]).read_text()
    expect = entry["expect"]
    if expect and expect["code"] in ("E101", "E102"):
        code, line, col, _ = lex_error(source)
        assert (code, line, col) == (expect["code"], expect["line"], expect["col"])
    else:
        toks = tokenize(source)
        assert toks[-1].kind is K.EOF
        assert toks[0].kind is K.AGENT


# ------------------------------------------------------------------ robustness


@pytest.mark.parametrize("text", ['"a\ud800b"', '"\\\udfff"'])
def test_lone_surrogate_in_string_is_e102(text):
    code, line, col, message = lex_error("let s = " + text + ";")
    assert (code, line) == ("E102", 1)
    assert col == 9 + text.index("\\u"[0] if False else next(c for c in text if 0xD800 <= ord(c) <= 0xDFFF))
    assert message.startswith("illegal character")


def test_surrogate_pair_characters_outside_bmp_are_fine():
    toks = tokenize('"\U0001F600"')
    assert toks[0].kind is K.STRING and toks[0].value == "\U0001F600"


def test_int_literal_longer_than_4300_digits():
    toks = tokenize("9" * 5000)
    assert toks[0].kind is K.INT and toks[0].value == int("9" * 5000)
