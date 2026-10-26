# 04. Semantic analysis: scopes, types, permission and budget

## 1. What this phase does

| | |
| --- | --- |
| Input | The AST from the parser. |
| Output | The same AST with a static type set on every expression (`Expr.type`), a symbol table, the budget result per task, and a list of warnings (W306). Packed as a `SemanticResult` whose `{text, data}` artifact fills the Symbols tab. |
| Place in the pipeline | Stage 3 of 10, the third classic phase and the last front-end phase. It is also the first safety stage: the permission and budget checks happen here, on the source program, long before any optimization. IR generation (stage 4) assumes the AST it receives has passed this phase. |
| Errors | E301 undeclared name / unknown tool, E302 duplicate declaration, E303 type mismatch, E304 missing return, E305 tool not permitted, E306 budget exceeded; warning W306. |

The parser only knows what the program looks like. This phase decides what it means: which
declaration every name refers to, what type every expression has, whether every tool call is
allowed, and whether the task can stay inside its call budget.

It runs in two passes:

1. **One walk over the AST in source order** that checks scopes, types, returns and permissions
   together. The first error found stops compilation.
2. **The budget check**, once per task, after the walk has succeeded.

## 2. Key data structures

**Symbol.** One entry per declared name. It records the name, its kind (`tool`, `task`,
`param` or a `let` variable), its type (for a tool, its signature from the tool table) and the
line and column of its declaration (the built-in tools have no source position).

**Scope.** A dictionary from name to `Symbol` plus a link to the enclosing scope. The chain
for a statement inside an `if` in task `report`:

```
builtins   web_search, read_file, llm, send_email, delete_file, sanitize, confirm   (kind tool)
  agent    report                                                                  (kind task)
    task   topic : string                                                          (kind param)
      block  raw, clean, summary                                                   (the task body)
        block  ...                                                                 (the if block)
```

| Operation | Behaviour |
| --- | --- |
| `lookup(name)` | Search this scope, then each enclosing scope outward; not found means E301. |
| `declare(symbol)` | If `lookup(name)` finds anything (in this scope **or any enclosing one**), E302. Otherwise add it here. |

Because `declare` checks the whole chain, there is no shadowing: a `let` cannot reuse a
parameter, task or tool name, and a nested block cannot reuse a name from an outer block.
Sibling blocks can reuse a name, because a sibling's scope is gone by the time the next block
is entered.

**Types.** `Type` values from `agentscript/typesys.py`: `STRING`, `INT`, `BOOL` and
`list_of(T)`. Equality of types is structural (`list<string> == list<string>`).

**Tool table.** `TOOLS` from `agentscript/tools.py`: each `ToolSpec` gives the parameter types
and the return type used for call checking. The safety annotations in it are not used here;
they are used by the taint, approval and optimizer stages.

**Permitted set.** The set of tool names from all `permit` declarations.

**BudgetInfo.** Per task: the worst-path call count, the agent's budget, and the worst path
itself as a list of call sites (line, column, tool name). It is what E306 reports and what the
Symbols tab shows next to each task.

**SemanticResult.** The symbol tables, the `BudgetInfo` of every task, and `warnings` (a list of
`Diagnostic`, currently only W306). Its `artifact()` method produces the `{text, data}` pair.

## 3. Algorithm

### 3.1 Declarations and permits

In plain words: fill the builtins scope with the seven tools, then read the `permit` lists, then
declare every task name in the agent scope before looking at any task body.

```
builtins = Scope(parent=None);  for tool in TOOLS: builtins.declare(Symbol(tool, "tool", ...))
permitted = {}
for ref in every permit list (source order):
    if ref.name not in TOOLS:   E301 "unknown tool" at ref
    if ref.name in permitted:   E302 "tool listed twice in permit" at ref
    permitted.add(ref.name)
agent_scope = Scope(parent=builtins)
for task in tasks:              agent_scope.declare(task.name)        # E302 on a duplicate task
```

### 3.2 The source-order walk (scopes, types, permission, returns)

In plain words: for each task, open a scope for its parameters and a scope for its body, then
visit every statement in order. Each statement declares or uses names and checks the types of
its expressions. Each expression is checked bottom-up: first its children get a type, then the
operator or call rule decides the expression's own type (or reports E303). The type is stored in
`Expr.type`, where later phases read it.

```
check_task(task):
    params = Scope(parent=agent_scope)
    for p in task.params: params.declare(p.name, "param", p.declared_type)   # E302
    check_block(task.body, params, task.return_type)
    if not always_returns(task.body):  E304 at the closing "}" of task.body

check_block(block, parent, ret):
    scope = Scope(parent)
    for s in block.statements:
        Let:      t = type_of(s.value, scope); scope.declare(s.name, "var", t)   # E302 at the name
        If:       require type_of(s.cond) == bool                                # E303
                  check_block(s.then_block, scope, ret); check_block(s.else_block, scope, ret)
        Repeat:   if s.count is a Name: require lookup(count).type == int        # E301 / E303
                  check_block(s.body, scope, ret)
        Return:   require type_of(s.value) == ret                                # E303
        ExprStmt: type_of(s.expr)

type_of(e, scope):
    IntLit -> int;  StrLit -> string;  BoolLit -> bool
    Name   -> lookup(e.name).type                                             # E301
    Index  -> base must be list<T>, index must be int; result T               # E303
    Binary -> operand rule from the operator table below; result type         # E303
    Call   -> 1. e.tool must be a built-in tool                               # E301 "unknown tool"
              2. type every argument; count and types must match the signature  # E303
              3. e.tool must be in permitted                                  # E305
              result = the tool's return type

always_returns(block):
    any statement s in block where
        s is Return, or
        s is If with an else block and always_returns(then) and always_returns(else)
    (Repeat never counts: it may run zero times)
```

The operator rules (E303 when the operands do not fit):

| Operator | Operands | Result |
| --- | --- | --- |
| `+` | `int, int` or `string, string` | `int` or `string` |
| `-` `*` | `int, int` | `int` |
| `<` `<=` `>` `>=` | `int, int` | `bool` |
| `==` `!=` | same type, one of `int`, `bool`, `string` | `bool` |
| `e[i]` | `list<T>`, `int` | `T` |

A call to a task name is E301 "unknown tool", because tasks live in the agent scope with kind
`task`, not `tool`. This is how "tasks cannot call tasks" is enforced: there is no separate rule.

### 3.3 The budget check (worst-path count)

In plain words: walk each task body again and build the longest possible sequence of tool calls
that one run could make, following these rules. If that sequence is longer than the budget,
report E306 at the first call that does not fit.

| Construct | Worst path |
| --- | --- |
| sequence of statements | the paths of the statements, concatenated |
| tool call | the calls inside its arguments (left to right), then the call itself |
| other expression | the calls inside it, left to right |
| `if (c) A else B` | calls in `c`, then the longer of the paths of `A` and `B` (missing `else` = empty) |
| `repeat 3 { A }` | the path of `A`, three times |
| `repeat x { A }` | the path of `A`, once, plus warning W306 at `x` |

Every tool counts 1, including `sanitize` and `confirm`.

```
worst_block(stmts):  return concat(worst_stmt(s) for s in stmts)

worst_stmt(s):
    Let / Return / ExprStmt:  return calls_in(s's expression)
    If:      a = worst_block(then); b = worst_block(else) if else else []
             return calls_in(cond) + (a if len(a) >= len(b) else b)
    Repeat:  body = worst_block(s.body)
             if count is IntLit: return body repeated max(count, 0) times
             else: warn W306 "repeat count `x` is not a literal; the budget for this loop
                   is enforced at runtime" at the count; return body

calls_in(e):          # evaluation order: arguments first, then the call
    Call:   concat(calls_in(a) for a in args) + [call site of e]
    Binary: calls_in(left) + calls_in(right)
    Index:  calls_in(base) + calls_in(index)
    other:  []

check_budget(task):
    path = worst_block(task.body.statements)
    if len(path) > budget:
        E306 at path[budget]          # the (budget+1)-th call, 0-based index = budget
             message: task name, worst-path count, budget;  diagnostic path = path
```

Ties between `then` and `else` keep the `then` path. Any choice gives the same count; this one
is simply deterministic.

**Runtime enforcement.** The static count cannot be exact when a `repeat` count is a variable,
so the VM counts every executed `CALL` again and stops with E601 before executing the call that
would exceed the budget ([09-codegen-and-vm.md](09-codegen-and-vm.md)). The two checks are
complementary:

| Program | Compile time | Run time |
| --- | --- | --- |
| no `repeat`, or only literal counts | exact upper bound; E306 if too many | VM guard never trips |
| a `repeat x` with a variable count | W306, body counted once | VM guard trips with E601 if the real count is too large |

`runtime_budget.as` shows the second row: `repeat times` with one `web_search` inside and
`budget calls = 3`. The compile warns at the count (6:12) and succeeds; a run with `times = 5`
makes three calls and stops with E601 at the fourth (7:15).

For `valid_report.as` the worst path is `web_search` (6:15), `sanitize` (7:17), `llm` (8:19),
`confirm` (9:9) and `send_email` (10:14): 5 calls, budget 5, so no error.

## 4. Worked example

> Filled in at M1: paste the symbol table (scopes and inferred types of `raw`, `clean`, `summary`) printed by `.venv/bin/python -m agentscript compile examples/valid_report.as --phase symbols`.

> Filled in at M2: paste the budget lines for task `report` (worst path of 5 calls, budget 5) printed by `.venv/bin/python -m agentscript compile examples/valid_report.as --phase symbols`.

## 5. Errors this phase catches

> Filled in at M1: paste the E301 to E305 diagnostics printed by `.venv/bin/python -m agentscript compile examples/<file>` for E301 `sem_undeclared.as` (6:12), E302 `sem_duplicate.as` (7:9), E303 `sem_type_mismatch.as` (6:23), E304 `sem_missing_return.as` (9:3) and E305 `sem_not_permitted.as` (6:16), all five part of the M1 gate.

> Filled in at M2: paste the E306 and W306 diagnostics printed by `.venv/bin/python -m agentscript compile examples/<file>` for E306 `sem_budget.as` (9:12, with its call-site path) and the W306 warning of `runtime_budget.as` (6:12).

## 6. Design decisions and limitations

| Decision | Why |
| --- | --- |
| Scopes, types and permissions in one source-order walk. | Each check needs the same information (what a name refers to and its type), and walking in source order makes "first error wins" mean the first error in the file, which is what a user expects. |
| The budget check runs after the walk. | It needs a fully valid task (every call known to be a real, permitted tool) and works on whole tasks rather than single statements. |
| No shadowing; checked by `declare` looking at the whole scope chain. | One name means one thing within a task, so error messages and taint paths are unambiguous. It also lets the IR generator keep user variable names, renaming only sibling reuses. |
| `let` infers its type from the initializer. | No type annotations on `let` keeps programs short; every initializer already has a known type because tool signatures are fixed. |
| Missing-return check is purely structural. | It is easy to explain and never wrong in the dangerous direction: if it says "always returns", every path really does return. It can reject a program that returns in practice (for example `if (true) { return x; }` with no `else`). |
| Permission is a compile-time check (E305) plus a VM guard (E602). | The compile check gives a precise error; the VM guard only protects against bytecode that did not come from this compiler, so it is defensive and cannot trip for a compiled program. |
| Every tool counts 1 toward the budget, including `sanitize` and `confirm`. | One simple rule that matches what the VM counts at runtime. Exempting some tools would make the static and the runtime numbers disagree. |
| Worst-path count over the AST, not the CFG. | On a structured AST the count is a simple recursion (sum, max, multiply). On the CFG, loops would need a bound analysis. |
| The count ignores early returns. | Keeps the rule structural. The result is an over-estimate, never an under-estimate, so a program that passes really stays within budget (when all loop counts are literals). |
| A variable loop count is a warning, not an error. | Rejecting every non-literal count would make data-driven loops impossible. The VM guard keeps the budget a hard limit anyway. |
| E306 points at the (budget+1)-th call on the worst path. | That is the first call that does not fit, which tells the user where to cut. |

Limitations:

- The budget is guaranteed statically only for code whose `repeat` counts are literals; for
  variable counts it is enforced at runtime only (E601).
- The static count is conservative: early `return`s and conditions that are always false are not
  taken into account, so a program can be rejected although no run could exceed the budget.
- A large literal count (`repeat 100000`) makes the worst path list long; the count is still
  correct, but the path in E306 is long.
- Only the first error is reported.
- The budget is per task run; there is no budget across runs or across tasks.

## 7. Where it lives in the code

> Filled in at M1: list the `agentscript/semantic.py` scopes and types (`Symbol`, `Scope`, `SemanticResult`, `analyze(agent)` and the walk and type functions, including the E305 permission check), the tool table in `agentscript/tools.py`, the types in `agentscript/typesys.py`, and the tests in `tests/test_semantic.py`, from the source files.

> Filled in at M2: list the budget functions and `BudgetInfo` in `agentscript/semantic.py` and the permission and budget tests added to `tests/test_semantic.py`, from the source files.
