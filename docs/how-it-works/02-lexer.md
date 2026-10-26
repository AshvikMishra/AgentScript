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
| `text` | The exact characters from the source, e.g. `web_search`, `<=`, `"Send report?"` (with the quotes and any backslashes). `""` for `EOF`. |
| `value` | `int` for `INT`, the unescaped `str` for `STRING`, `None` for every other kind. |
| `line`, `col` | Position of the token's first character. 1-based; a tab counts as one column. |

For a string literal `value` is the unescaped string (the characters between the quotes with
escapes resolved), which the parser copies into `StrLit.value`. For an integer literal the
lexer already converts the digits to a Python `int`, which the parser copies into
`IntLit.value` (and `Budget.calls`).

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

Each keyword, punctuation and operator member has its spelling as its enum value (for example
`TokenKind.ARROW.value == "->"`). Most keyword members are the upper-cased spelling (`AGENT`,
`LET`, `FALSE`, ...); the four type keywords are `STRING_T`, `INT_T`, `BOOL_T` and `LIST_T`, so
they do not clash with the literal kinds `STRING` and `INT`. Punctuation and operators have
names such as `LBRACE`, `SEMI`, `ASSIGN`, `ARROW`, `PLUS`, `EQ`, `LE`, `GT`.

**Keyword set.** `KEYWORDS`, a dict from the 16 keyword spellings to their kinds, built from the
enum. An identifier-shaped word is looked up in it after it has been scanned; if found, it gets
the keyword's kind instead of `IDENT`.

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
before the closing quote is E101, reported at the **opening** quote (a backslash directly before
the newline or the end of the file does not help: it is still E101). Any character is allowed
inside a string except a lone UTF-16 surrogate (`\ud800` to `\udfff`, which can reach the
compiler through the JSON API), which is E102 at that character because it cannot be encoded
as UTF-8 in any artifact.

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
        tokens.append(Token(kind, word, value, *start))  # value: int, unescaped str, or None
    tokens.append(Token(EOF, "", None, line, col))
    return tokens
```

`TWO_CHAR` is `-> == != <= >=`; `ONE_CHAR` is `{ } ( ) [ ] , ; : = + - * < >`. Because `>>` is in
neither table, `list<list<string>>` ends with two separate `>` tokens, which is exactly what the
parser's `type` rule needs.

## 4. Worked example

Input, `examples/valid_report.as` (with line numbers):

```
     1	agent Assistant {
     2	  permit web_search, llm, sanitize, send_email, confirm;
     3	  budget calls = 5;
     4	
     5	  task report(topic: string) -> bool {
     6	    let raw = web_search(topic);
     7	    let clean = sanitize(raw[0]);
     8	    let summary = llm("Summarize: " + clean);
     9	    if (confirm("Send report?")) {
    10	      return send_email("me@example.com", summary);
    11	    }
    12	    return false;
    13	  }
    14	}
```

Output of `.venv/bin/python -m agentscript compile examples/valid_report.as --phase tokens`
(each line is `line:col`, the `TokenKind` name, then the raw text):

```
  1:1   AGENT      agent
  1:7   IDENT      Assistant
  1:17  LBRACE     {
  2:3   PERMIT     permit
  2:10  IDENT      web_search
  2:20  COMMA      ,
...
  3:3   BUDGET     budget
  3:10  CALLS      calls
  3:16  ASSIGN     =
  3:18  INT        5
  3:19  SEMI       ;
  5:3   TASK       task
  5:8   IDENT      report
  5:14  LPAREN     (
  5:15  IDENT      topic
  5:20  COLON      :
  5:22  STRING_T   string
  5:28  RPAREN     )
  5:30  ARROW      ->
  5:33  BOOL_T     bool
  5:38  LBRACE     {
  6:5   LET        let
  6:9   IDENT      raw
  6:13  ASSIGN     =
  6:15  IDENT      web_search
  6:25  LPAREN     (
  6:26  IDENT      topic
  6:31  RPAREN     )
  6:32  SEMI       ;
  7:5   LET        let
  7:9   IDENT      clean
  7:15  ASSIGN     =
  7:17  IDENT      sanitize
  7:25  LPAREN     (
  7:26  IDENT      raw
  7:29  LBRACKET   [
  7:30  INT        0
  7:31  RBRACKET   ]
  7:32  RPAREN     )
  7:33  SEMI       ;
  8:5   LET        let
  8:9   IDENT      summary
  8:17  ASSIGN     =
  8:19  IDENT      llm
  8:22  LPAREN     (
  8:23  STRING     "Summarize: "
  8:37  PLUS       +
  8:39  IDENT      clean
  8:44  RPAREN     )
  8:45  SEMI       ;
...
 12:5   RETURN     return
 12:12  FALSE      false
 12:17  SEMI       ;
 13:3   RBRACE     }
 14:1   RBRACE     }
 15:1   EOF
```

What to notice:

- **Keyword or identifier.** `let`, `task`, `string`, `bool`, `false` are scanned exactly like
  identifiers and then found in `KEYWORDS`, so they get their own kinds (`LET`, `TASK`,
  `STRING_T`, `BOOL_T`, `FALSE`). `raw`, `topic`, `report` are not keywords and become `IDENT`.
  Tool names are not keywords either: `web_search`, `sanitize` and `llm` are plain `IDENT`s;
  that they name tools is decided later, by the parser (an `IDENT` followed by `(`) and the
  semantic checker.
- **Positions.** `web_search` on line 6 starts at **6:15**: four spaces of indentation, `let`
  at 6:5, `raw` at 6:9, `=` at 6:13, then `web_search`. Its `(` is at 6:25 because the
  identifier is 10 characters long. Every later phase that talks about this call (types,
  taint, budget) reports 6:15.
- **Longest match.** `->` on line 5 is one `ARROW` token, not `MINUS` followed by `GT`.
- **Strings keep their quotes.** `"Summarize: "` is shown with its quotes and is 13 characters
  wide, which is why the `+` after it sits at 8:37 (8:23 + 13 + one space). The unescaped value
  `Summarize: ` is in the token's `value` field (the `data` part of the artifact).
- **Whitespace leaves no trace.** Line 4 is empty and there is no token for it; a `//` comment
  would be skipped the same way.
- **EOF** sits just after the last character: the file ends with a newline after the `}` on
  line 14, so `EOF` is at 15:1.

## 5. Errors this phase catches

| Code | Demo file (`examples/manifest.json`) | Expected location |
| --- | --- | --- |
| E101 unterminated string | `lex_unterminated.as` | 6:13 |
| E102 illegal character | `lex_illegal_char.as` | 6:15 |

**E101.** Line 6 of `examples/lex_unterminated.as` opens a string that never closes:

```
     5	  task greet() -> string {
     6	    let s = "abc;
     7	    return s;
```

`.venv/bin/python -m agentscript compile examples/lex_unterminated.as` prints:

```
== diagnostics ==
E101 [lexer] 6:13: unterminated string: missing closing '"' before end of line
compilation failed
```

6:13 is the opening `"`, not the end of the line. The `;` is swallowed into the string, which
is why the error is lexical and not a missing-semicolon E201.

**E102.** Line 6 of `examples/lex_illegal_char.as` uses `#`, which is not a character of the
language:

```
     5	  task count() -> int {
     6	    let n = 2 # 3;
     7	    return n;
```

`.venv/bin/python -m agentscript compile examples/lex_illegal_char.as` prints:

```
== diagnostics ==
E102 [lexer] 6:15: illegal character '#'
compilation failed
```

In both cases no tokens listing is printed: the lexer stops at the first error, so there is no
complete token stream and no later phase runs. The same E102 message is used for `!` without
`=`, a single `/`, and any non-ASCII letter outside a string or comment.

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

**`agentscript/lexer.py`**

| Name | What it is |
| --- | --- |
| `TokenKind` | `Enum` of all token kinds; fixed-spelling kinds have their spelling as value, `IDENT`, `INT`, `STRING`, `EOF` have placeholder values (`"<ident>"`, ...). |
| `KEYWORDS` | dict spelling to `TokenKind` for the 16 keywords, derived from the enum. |
| `_TWO_CHAR`, `_ONE_CHAR` | operator and punctuation tables, also derived from the enum; two-character forms are tried first. |
| `Token` | frozen dataclass `(kind, text, value, line, col)` with `to_dict()` for the JSON artifact. |
| `_Lexer` | the scanner. `run()` is the main loop; `peek()`, `advance()` (updates line and column), `emit()`; one method per token class: `skip_comment()`, `lex_word()`, `lex_int()`, `lex_string()` (escapes, E101, surrogate E102), `lex_operator()` (longest match, E102). |
| `tokenize(source)` | public entry point: returns the token list ending in `EOF`, or raises `CompileError` (E101/E102, built with `diagnostics.make_error`). |
| `format_token(tok)` | one listing line, e.g. `  6:5   LET        let`. |
| `tokens_artifact(tokens)` | the `tokens` phase artifact: `{"text": listing, "data": [token dicts]}`. |

**`agentscript/pipeline.py`** runs the lexer as the first stage of `_run_stages()`:
`res.tokens = tokenize(self.source)` and `phases["tokens"] = tokens_artifact(res.tokens)`. A
raised `CompileError` becomes the single error diagnostic with phase `lexer`.

**`tests/test_lexer.py`** covers every keyword, operator and punctuation token, longest match
and `>>`, 1-based positions (including `\r` and tabs), comments, string escapes, E101 and E102
positions, the surrogate cases, the artifact format, and checks every example in
`examples/manifest.json` (`test_examples_lex_per_manifest`): lexer-phase examples must fail with
the expected code and position, all others must lex cleanly.
