# 03. Parser (syntax analysis)

## 1. What this phase does

| | |
| --- | --- |
| Input | The token list from the lexer, ending in `EOF`. |
| Output | The abstract syntax tree (AST): one `Agent` node at the root. Also a `{text, data}` artifact for the AST tab (an indented tree as text, the node dictionaries as data). |
| Place in the pipeline | Stage 2 of 10, the second classic phase. The AST goes to semantic analysis (stage 3), which fills in each expression's type. |
| Errors | E201 "expected X, found Y". Only the first syntax error is reported; there is no error recovery. |

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
parse_agent():
    expect("agent"); name = expect(IDENT); expect("{")
    permits = []
    while peek() is "permit": permits.append(parse_permit())
    budget = parse_budget()                         # E201 if the next token is not "budget"
    tasks = [parse_task()]
    while peek() is "task": tasks.append(parse_task())
    expect("}"); expect(EOF)
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

## 4. Worked example

> Filled in at M1: paste the real AST tree printed by `.venv/bin/python -m agentscript compile examples/valid_report.as --phase ast` (at least the `Let clean` subtree on line 7 and the `If` on line 9), and point out how `"Summarize: " + clean` became a `Binary` node.

## 5. Errors this phase catches

> Filled in at M1: paste the exact E201 diagnostic printed by `.venv/bin/python -m agentscript compile examples/syntax_missing_semicolon.as` (expected 6:30), and one more E201 from a missing `}` if a test covers it.

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

> Filled in at M1: list `agentscript/parser.py` with its main functions (`parse(tokens)`, the per-rule `parse_*` functions, `expect` and the E201 location helper), the node definitions in `agentscript/ast_nodes.py`, and the tests in `tests/test_parser.py`.
