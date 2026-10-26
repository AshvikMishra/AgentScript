# 02. Lexer (lexical analysis)

## 1. What this phase does

| | |
| --- | --- |
| Input | The source text of one `.as` file, as a string. |
| Output | A list of tokens, each with its kind, its exact text and its 1-based line and column. The last token is always `EOF`. Also a `{text, data}` artifact for the Tokens tab. |
| Place in the pipeline | Stage 1 of 10, the first of the six classic phases. Its tokens go to the parser (stage 2). |
| Errors | E101 unterminated string, E102 illegal character. The first lexical error stops compilation. |

The lexer turns characters into words. It removes whitespace and comments, recognises
keywords, identifiers, integer and string literals, and operators, and records where each one
starts so that every later error message can point at a line and column.

## 2. Key data structures

**Token.** One record per token:

| Field | Meaning |
| --- | --- |
| `kind` | A `TokenKind` value (see below). |
| `text` | The exact characters from the source, e.g. `web_search`, `<=`, `"Send report?"` (with the quotes and any backslashes). |
| `line`, `col` | Position of the token's first character. 1-based; a tab counts as one column. |

For a string literal the lexer also produces the unescaped value (the characters between the
quotes with escapes resolved), which the parser stores in `StrLit.value`. For an integer
literal the parser converts the text to an `int`.

Why keep the raw `text`: the parser's error-location rule for E201 needs the length of the
previous token as it appears in the source (`prev.col + len(prev.text)`), and the Tokens tab
should show what the user typed.

**TokenKind.** The exact enum members are defined in `agentscript/lexer.py` and listed in the
implementation plan. They fall into these groups:

| Group | Members |
| --- | --- |
| Keywords | `agent permit budget calls task let if else repeat return true false string int bool list` |
| Identifier | `IDENT`: `[A-Za-z_][A-Za-z0-9_]*` that is not a keyword |
| Literals | `INT`: `[0-9]+`; `STRING`: `"..."` on one line |
| Punctuation | `{ } ( ) [ ] , ; : = ->` |
| Operators | `+ - * == != < <= > >=` |
| End | `EOF` |

**Keyword set.** A fixed set of the 16 keyword spellings. An identifier-shaped word is looked
up in it after it has been scanned; if found, it gets the keyword's kind instead of `IDENT`.

## 3. Algorithm

In plain words: walk through the source one character at a time, keeping a position, a line and
a column. At each step skip whitespace and `//` comments; then look at the current character to
decide what kind of token starts here, and consume the longest sequence of characters that
still forms a token of that kind (maximal munch). Record the token with the line and column
where it started. Newlines increase the line and reset the column to 1. At the end, append
`EOF`. The whole file is tokenized before parsing starts.

Recognition rules, in the order they are tried:

| Current character | Action |
| --- | --- |
| space, tab, `\r`, `\n` | skip (a `\n` starts a new line) |
| `/` followed by `/` | skip to the end of the line (comment) |
| letter or `_` | read `[A-Za-z0-9_]*`; keyword if in the keyword set, otherwise `IDENT` |
| digit | read `[0-9]+`: `INT` |
| `"` | read a string literal (below) |
| one of `- = ! < >` that can start a two-character operator | try `->`, `==`, `!=`, `<=`, `>=` first, then the one-character form |
| one of `{ } ( ) [ ] , ; : + - * < > =` | one-character token |
| anything else (including `!` alone and `/` alone) | E102 at this character |

String literals: after the opening quote, read characters until the closing quote. A backslash
takes the next character: `\n` becomes a newline, `\t` a tab, `\"` a quote, `\\` a backslash, and
a backslash before any other character yields that character. A newline or the end of the file
before the closing quote is E101, reported at the **opening** quote.

```
tokenize(src):
    tokens = []; i = 0; line = 1; col = 1
    while i < len(src):
        c = src[i]
        if c is whitespace:            advance(1); continue      # advance() updates line/col
        if src[i:i+2] == "//":         skip to "\n"; continue
        start = (line, col)
        if c is letter or "_":         word = read [A-Za-z0-9_]*
                                       kind = KEYWORDS.get(word, IDENT)
        elif c is digit:               word = read [0-9]+; kind = INT
        elif c == '"':                 word, value = read_string(start)   # E101 at start
                                       kind = STRING
        elif src[i:i+2] in TWO_CHAR:   word = src[i:i+2]; kind = TWO_CHAR[word]
        elif c in ONE_CHAR:            word = c; kind = ONE_CHAR[c]
        else:                          raise E102 "illegal character c" at start
        tokens.append(Token(kind, word, *start))
    tokens.append(Token(EOF, "", line, col))
    return tokens
```

`TWO_CHAR` is `-> == != <= >=`; `ONE_CHAR` is `{ } ( ) [ ] , ; : = + - * < >`. Because `>>` is in
neither table, `list<list<string>>` ends with two separate `>` tokens, which is exactly what the
parser's `type` rule needs.

## 4. Worked example

> Filled in at M1: paste the real token stream printed by `.venv/bin/python -m agentscript compile examples/valid_report.as --phase tokens` (at least lines 5 to 7 of the program), and point out the keyword/identifier split and the line:col of `web_search` on line 6.

## 5. Errors this phase catches

> Filled in at M1: paste the exact diagnostics printed by `.venv/bin/python -m agentscript compile examples/lex_unterminated.as` (E101, expected 6:13) and `.venv/bin/python -m agentscript compile examples/lex_illegal_char.as` (E102, expected 6:15).

## 6. Design decisions and limitations

| Decision | Why |
| --- | --- |
| Hand-written scanner loop rather than a lexer generator. | The token set is tiny, Python has no standard lex, and a loop makes line/column tracking and the E101 position explicit and easy to explain. (A regex alternation would also work.) |
| Tokenize the whole file before parsing. | The parser can then peek at any token, the Tokens tab shows the complete stream, and the lexer and parser can be tested separately. |
| Stop at the first lexical error. | Same policy as every other phase: one error, reported precisely. A wrong character usually makes later tokens meaningless anyway. |
| E101 points at the opening quote. | That is where the user has to look; the end of the line says nothing about which string is unclosed. |
| Strings stay on one line. | An unterminated string is then caught on the line where it starts instead of swallowing the rest of the file. |
| No negative literals, no `/`, no `!`. | The grammar does not have unary minus, division or logical not, so the lexer rejects their characters early with a clear E102 instead of letting the parser produce a vaguer E201. |
| `>>` is two tokens. | No shift operator exists, and nested list types need two closing `>`. |
| A tab counts as one column. | Columns then match character offsets in the line, which is what the editor uses for squiggles. Editors that render a tab wider will show a different visual column; this is accepted. |

Limitations:

- `123abc` lexes as `INT 123` followed by `IDENT abc`; the parser then reports E201. The lexer
  does not require a separator after a number.
- The language defines no size limit for integer literals; values are Python integers, so there
  is no overflow check anywhere in the pipeline.
- Only ASCII letters, digits and `_` are allowed in identifiers. Any other character outside a
  string or comment is E102.
- Only the first lexical error is reported.

## 7. Where it lives in the code

> Filled in at M1: list `agentscript/lexer.py` with its main definitions (`TokenKind`, `Token`, `tokenize(source)`, `tokens_artifact(tokens)` and any helpers), how `agentscript/pipeline.py` calls it, and the tests in `tests/test_lexer.py`.
