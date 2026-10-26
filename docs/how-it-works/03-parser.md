# 03. Parser (syntax analysis)

## 1. What this phase does

| | |
| --- | --- |
| Input | The token list from the lexer, ending in `EOF`. |
| Output | The abstract syntax tree (AST): one `Agent` node at the root. Also a `{text, data}` artifact for the AST tab (an indented tree as text, the node dictionaries as data). |
| Place in the pipeline | Stage 2 of 10, the second classic phase. The AST goes to semantic analysis (stage 3), which fills in each expression's type. |
| Errors | E201 "expected X, found Y", including "expected at most 1000 levels of nesting" for programs nested too deeply. Only the first syntax error is reported; there is no error recovery. |

The parser checks that the tokens follow the grammar and builds a tree that later phases can
walk without caring about punctuation, precedence or parentheses.

## 2. Key data structures

**The grammar** (complete; repeated from [01-language.md](01-language.md)):

```
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
             | IDENT [ "(" [ expr { "," expr } ] ")" ]
             | "(" expr ")" ;
```

**AST nodes** (`agentscript/ast_nodes.py`, dataclasses). Every node keeps a source position,
because every later diagnostic needs one.

| Node | Fields | Position (`line`, `col`) points at |
| --- | --- | --- |
| `Agent` | `name`, `permits: list[Permit]`, `budget: Budget`, `tasks: list[Task]` | `agent` keyword |
| `Permit` | `tools: list[NameRef]` | `permit` keyword |
| `NameRef` | `name` (a tool name inside `permit`) | the identifier |
| `Budget` | `calls: int` | `budget` keyword |
| `Task` | `name`, `params: list[Param]`, `return_type: Type`, `body: Block` | `task` keyword |
| `Param` | `name`, `declared_type: Type` | the parameter name |
| `Block` | `statements`, plus `end_line`, `end_col` of the closing `}` | the `{` |
| `Let` | `name`, `value: Expr`, plus `name_line`, `name_col` | `let` keyword (E302 uses the name position) |
| `If` | `cond`, `then_block`, `else_block` (or `None`) | `if` keyword |
| `Repeat` | `count: IntLit or Name`, `body: Block` | `repeat` keyword |
| `Return` | `value: Expr` | `return` keyword |
| `ExprStmt` | `expr: Expr` | its expression |
| `IntLit`, `StrLit`, `BoolLit` | `value` (`StrLit.value` is unescaped) | the literal token |
| `Name` | `name` | the identifier |
| `Call` | `tool`, `args: list[Expr]` | the tool name |
| `Index` | `base`, `index` | the `[` |
| `Binary` | `op`, `left`, `right` | the operator |

Every expression node also has a `type` field, empty after parsing and filled in by semantic
analysis. Types written in the source (`list<string>`) are parsed straight into `Type` values
from `agentscript/typesys.py`.

Two helpers come with the nodes: `ast_to_dict()` (JSON for the editor and the API) and
`format_ast()` (the indented text tree, also what the golden files store).

What the AST leaves out: parentheses (grouping is in the tree shape), semicolons, commas and
the `->`. The end position of a block is kept because E304 (missing return) is reported at
the closing `}` of a task body.

## 3. Algorithm

In plain words: recursive descent. There is one function per grammar rule; each function
consumes the tokens of its rule and returns the AST node for it. The parser keeps one index
into the token list. `peek()` looks at the current token, and `expect(kind)` consumes it if it
has the right kind or raises E201 otherwise. Repetition in the grammar (`{ ... }`) becomes a
`while` loop, optional parts (`[ ... ]`) become an `if`.

The grammar is LL(1): one token of lookahead is always enough to pick the right rule, so the
parser never backtracks.

| Decision point | Token that decides |
| --- | --- |
| which statement | `let`, `if`, `repeat`, `return`; anything else starts an expression statement |
| more permits or the budget | `permit` vs `budget` |
| another task | `task` vs `}` |
| `else` part | `else` |
| call or plain name | an `IDENT` followed by `(` is a call |
| repeat count | `INT` or `IDENT` (anything else is E201) |

**Precedence and associativity** come from the layering of the expression rules: each level
calls the next-higher level for its operands, so `*` binds tighter than `+`, which binds tighter
than `<`, which binds tighter than `==`. Each level is a loop that folds operators to the left,
which makes every binary operator left-associative: `a - b - c` parses as `(a - b) - c`. Postfix
indexing is a loop too, so `xs[0][1]` is `(xs[0])[1]`.

```
parse_program():
    expect("agent"); name = expect(IDENT); expect("{")
    permits = []
    while peek() is "permit": permits.append(parse_permit())
    budget = parse_budget()      # E201 "expected 'permit' or 'budget'" if the next token is neither
    tasks = [parse_task()]       # E201 "expected 'task'" if there is none
    while peek() is "task": tasks.append(parse_task())
    expect("}")                  # E201 "expected 'task' or '}'"
    expect(EOF)
    return Agent(name, permits, budget, tasks)

parse_statement():
    if peek() is "let":     t = advance(); n = expect(IDENT); expect("="); e = parse_expr(); expect(";")
                            return Let(n.text, e, at t, name at n)
    if peek() is "if":      t = advance(); expect("("); c = parse_expr(); expect(")")
                            then = parse_block()
                            other = parse_block() if accept("else") else None
                            return If(c, then, other, at t)
    if peek() is "repeat":  t = advance(); count = IntLit or Name from expect(INT or IDENT)
                            return Repeat(count, parse_block(), at t)
    if peek() is "return":  t = advance(); e = parse_expr(); expect(";"); return Return(e, at t)
    e = parse_expr(); expect(";"); return ExprStmt(e)

parse_binary_level(ops, next_level):        # used for equality, relational, additive, term
    left = next_level()
    while peek() in ops:
        op = advance(); right = next_level()
        left = Binary(op.text, left, right, at op)
    return left

parse_postfix():
    e = parse_primary()
    while peek() is "[":
        b = advance(); i = parse_expr(); expect("]"); e = Index(e, i, at b)
    return e

parse_primary():
    INT / STRING / true / false  -> literal node
    IDENT followed by "("        -> Call(name, comma-separated parse_expr() list, at name)
    IDENT                        -> Name
    "("                          -> e = parse_expr(); expect(")"); return e
    otherwise                    -> E201 "expected expression, found <token>"

parse_type():
    "string" | "int" | "bool"    -> STRING | INT | BOOL
    "list" "<" parse_type() ">"  -> list_of(elem)
```

**E201 location rule.** When `expect` fails, it reports "expected X, found Y". The position is
chosen like this:

```
if found.line > prev.line:      # the missing token belonged at the end of the previous line
    report at (prev.line, prev.col + len(prev.text))
else:
    report at (found.line, found.col)
```

`prev` is the last token consumed. For `syntax_missing_semicolon.as`, line 6 is
`let a = web_search(topic)` with no `;`; the token found is `return` on line 7, so the error is
reported just after the `)` that ends line 6, at 6:30, which is where the user has to type the
`;`.

The "expected X" part is usually the token kind (`';'`, `identifier`), but some call sites name
what makes sense to the user: `agent name`, `task name`, `parameter name`, `tool name`, `type`,
`expression`, `integer or identifier` (repeat count), `',' or ')'` (argument and parameter
lists), `',' or ';'` (permit). The "found Y" part shows the token: `'return'`,
`identifier 'x'`, `integer 42`, `string "abc"` or `end of file`.

**Nesting limit.** Later phases walk the AST recursively, so the parser bounds nesting at
`MAX_NESTING = 1000`. While parsing, every block and every expression (each `(`, `[` index and
call argument opens a new one) increases a depth counter; going past 1000 is E201 "expected at
most 1000 levels of nesting, found <token>". After parsing, `check_nesting()` walks the finished
AST iteratively and reports the first node deeper than 1000 statement/block/expression levels
(for example a chain of 5000 `+`, which is left-deep but needs no parentheses) as E201 "expected
at most 1000 levels of nesting, found a deeper expression".

## 4. Worked example

Input: `examples/valid_report.as` (the full listing with line numbers is in
[02-lexer.md](02-lexer.md), section 4). Output of
`.venv/bin/python -m agentscript compile examples/valid_report.as --phase ast`:

```
Agent Assistant @1:1
  Permit [web_search, llm, sanitize, send_email, confirm] @2:3
  budget:
    Budget 5 @3:3
  Task report return_type=bool @5:3
    Param topic declared_type=string @5:15
    body:
      Block @5:38
        Let raw @6:5
          Call web_search : list<string> @6:15
            Name topic : string @6:26
        Let clean @7:5
          Call sanitize : string @7:17
            Index : string @7:29
              Name raw : list<string> @7:26
              IntLit 0 : int @7:30
        Let summary @8:5
          Call llm : string @8:19
            Binary + : string @8:37
              StrLit 'Summarize: ' : string @8:23
              Name clean : string @8:39
        If @9:5
          Call confirm : bool @9:9
            StrLit 'Send report?' : string @9:17
          then_block:
            Block @9:34
              Return @10:7
                Call send_email : bool @10:14
                  StrLit 'me@example.com' : string @10:25
                  Name summary : string @10:43
        Return @12:5
          BoolLit False : bool @12:12
```

Each line is one node, its main fields, and `@line:col`. The `: type` after each expression is
not produced by the parser: the pipeline re-renders the AST tab after semantic analysis so
that it shows the static types (straight after parsing every `type` field is still empty).

What to notice:

- **Punctuation is gone.** No `;`, `,`, `->` or parentheses appear; `let raw = web_search(topic);`
  is just `Let raw` with one child, the `Call`.
- **Calls by syntax.** `web_search(topic)` is a `Call` because the `IDENT` is followed by `(`;
  `topic` on its own is a `Name`. The call sits at the tool name (6:15), the same position the
  lexer gave the `web_search` token.
- **Postfix indexing.** In `sanitize(raw[0])` (line 7) the argument is an `Index` node with
  `base = Name raw` and `index = IntLit 0`, positioned at the `[` (7:29), not at `raw` (7:26).
- **Binary node.** `"Summarize: " + clean` on line 8 went through the expression levels
  `equality -> relational -> additive`: `parse_additive` read the `StrLit` as its left operand,
  saw `+`, read `Name clean` as the right operand, and folded them into `Binary +`. The node is
  positioned at the operator (8:37), its two children at their own tokens (8:23 and 8:39). The
  `StrLit` holds the unescaped value `'Summarize: '`, without the source quotes.
- **If with no else.** The `If` on line 9 has a `Call confirm` as its condition and a
  `then_block`; there is no `else_block` line because the field is `None`.
- **Blocks keep their `{`.** `Block @5:38` is the task body's `{`; its closing `}` (13:3) is
  stored in `end_line`/`end_col` and is not printed in the tree, but E304 uses it.

## 5. Errors this phase catches

| Code | Demo file (`examples/manifest.json`) | Expected location |
| --- | --- | --- |
| E201 syntax error | `syntax_missing_semicolon.as` | 6:30 |

**Missing semicolon.** `examples/syntax_missing_semicolon.as`:

```
     5	  task find(topic: string) -> list<string> {
     6	    let a = web_search(topic)
     7	    return a;
```

`.venv/bin/python -m agentscript compile examples/syntax_missing_semicolon.as` prints the token
listing (the lexer succeeded) and then the diagnostic:

```
== tokens ==
  1:1   AGENT      agent
...
  6:5   LET        let
  6:9   IDENT      a
  6:11  ASSIGN     =
  6:13  IDENT      web_search
  6:23  LPAREN     (
  6:24  IDENT      topic
  6:29  RPAREN     )
  7:5   RETURN     return
  7:12  IDENT      a
  7:13  SEMI       ;
...

== diagnostics ==
E201 [parser] 6:30: expected ';', found 'return'
compilation failed
```

The token found is `return` at 7:5, but it is on a later line than the previous token `)` at
6:29, so the location rule reports 6:29 + len(")") = **6:30**, the end of line 6.

**Missing closing brace.** Covered by `test_missing_closing_brace_at_eof` in
`tests/test_parser.py` (no demo file). The same program saved as a scratch file `missing_brace.as`:

```
     1	agent A {
     2	  budget calls = 1;
     3	  task t() -> int {
     4	    return 1;
     5	  }
```

`.venv/bin/python -m agentscript compile missing_brace.as` ends with:

```
== diagnostics ==
E201 [parser] 5:4: expected 'task' or '}', found end of file
compilation failed
```

After the task, the parser accepts another `task` or the agent's `}`; it finds `EOF` on line 6,
so the error goes right after the task's `}` on line 5.

**Nesting limit.** A `return` of 1001 nested parentheses (`return ((((...1...))));` on line 4,
scratch file) gives:

```
== diagnostics ==
E201 [parser] 4:1011: expected at most 1000 levels of nesting, found '('
compilation failed
```

`parse_expr` is entered once for the return value and once per `(`, so the 1000th `(` (column
12 + 999 = 1011) is the one refused.

## 6. Design decisions and limitations

| Decision | Why |
| --- | --- |
| Hand-written recursive descent, no parser generator. | The PRD asks for it (F2), the grammar is LL(1), and each grammar rule maps to one readable function, which is easy to present and to step through in a debugger. |
| Precedence by grammar layering instead of a precedence table (Pratt parsing). | With five levels, layered rules are the textbook approach and the grammar itself documents the precedence. |
| Operators are left-associative, including comparisons. | One loop shape for every level. `a < b < c` parses as `(a < b) < c` and is then rejected by the type checker (E303: `bool < int`), which gives a clearer message than a special syntax rule. |
| `repeat` takes only an `INT` or an `IDENT`, not an expression. | The budget check needs to see at a glance whether the count is a literal (exact count) or a variable (W306 and runtime check). `repeat 2 + 1` is a syntax error. |
| No `else if`. | `else` must be followed by a block; write `else { if (...) { ... } }`. One less grammar rule, and the CFG shape is the same. |
| Exactly one `budget`, after the permits, and at least one task. | Fixed order means the parser needs no extra checks: a missing or second `budget` is simply "expected X, found Y". |
| Calls are recognised by syntax (`IDENT (`), not by name. | The parser does not need the tool table; whether the name is a real tool is a semantic question (E301), checked in one place. |
| No error recovery; the first E201 stops compilation. | Recovery is hard to get right and produces cascades of follow-on errors. The PRD lists it as a risk; one precise error is more useful for a demo. |
| The E201 location rule above. | Without it, a missing `;` at the end of a line would be reported at the first token of the next line, which points the user at the wrong line. |
| Positions on every node. | Every later phase reports errors at source positions, and the IR copies them from the AST. |

Limitations:

- Only the first syntax error is reported.
- The message only names what was expected and what was found; it does not suggest a fix.
- Expression statements accept any expression (`1 + 2;` is legal and does nothing); only tool
  calls are useful there.

## 7. Where it lives in the code

**`agentscript/parser.py`**

| Name | What it is |
| --- | --- |
| `parse(tokens)` | public entry point: `Parser(tokens).parse_program()`, then `check_nesting()`; returns the `Agent` or raises `CompileError` E201. |
| `Parser` | the recursive-descent parser. Holds `tokens`, `pos` and the nesting `depth`; the constructor rejects a token list that does not end in `EOF`. |
| `peek()`, `check(*kinds)`, `advance()`, `expect(kind, what=None)` | token helpers; `advance()` never steps past `EOF`; `expect` raises through `error()`. |
| `error(expected)` | builds the E201 diagnostic and applies the location rule (found token, or just after the previous token when the found token is on a later line). |
| `describe_kind()`, `describe_token()` | the "expected X" and "found Y" wording. |
| `parse_program`, `parse_permit` (+ `_name_ref`), `parse_budget`, `parse_task`, `parse_param`, `parse_type` | declaration rules. |
| `parse_block` (+ `_block`), `parse_statement`, `parse_let`, `parse_if`, `parse_repeat`, `parse_return` | statement rules; `parse_statement` dispatches on `let`/`if`/`repeat`/`return`, otherwise an expression statement. |
| `parse_expr`, `parse_equality`, `parse_relational`, `parse_additive`, `parse_term`, `parse_postfix`, `parse_primary` (+ `_call_args`) | expression rules, one per precedence level; the four binary levels share `_binary_level(ops, operand)`. |
| `enter()`, `MAX_NESTING`, `check_nesting(agent)` | the nesting bound (during parsing and on the finished AST). |

**`agentscript/ast_nodes.py`**: the node dataclasses (`Agent`, `Permit`, `NameRef`, `Budget`,
`Task`, `Param`, `Block`, `Let`, `If`, `Repeat`, `Return`, `ExprStmt`, `IntLit`, `StrLit`,
`BoolLit`, `Name`, `Call`, `Index`, `Binary`, with the base classes `Expr` and `Stmt`), plus
`ast_to_dict()` and `format_ast()`. `Agent.permitted_tools()` flattens the permit lists.

**`agentscript/pipeline.py`** runs the parser as stage 2 of `_run_stages()`:
`res.agent = parse(res.tokens)`, then
`phases["ast"] = {"text": format_ast(res.agent), "data": ast_to_dict(res.agent)}`; after
semantic analysis the `ast` artifact is rendered again so it shows the expression types.

**`tests/test_parser.py`** covers the AST shape and positions of `valid_report.as`,
`format_ast`/`ast_to_dict`, every statement form, types, precedence and associativity, node
positions, many E201 cases (missing `;`, `)`, `}`, budget order, trailing tokens, bad repeat
counts, unsupported constructs), the location rule, the nesting limit, and every example in
`examples/manifest.json` (`test_examples_parse_per_manifest`).
