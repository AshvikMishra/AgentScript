"""Optimizer (F8): classic clean-ups on the CFG of one task, after the safety analyses pass.

`optimize(cfg)` works on a deep copy and repeats four passes until none changes anything:

1. constant folding + local constant/copy propagation within each block
   (a BinOp of two constants becomes an Assign; a Branch on a constant becomes a Jump);
2. unreachable-block elimination (blocks not reachable from the entry);
3. dead-assignment elimination: Assign/BinOp whose destination is never read anywhere in the
   task (Call is never removed: side effects and budget; Index is never removed: it may
   raise E603);
4. duplicate tool-call elimination: in one block, a Call to a mergeable tool whose immediately
   preceding Call has the same tool and identical operands (and neither that call's
   destination nor any argument variable is redefined in between) becomes a copy of the
   earlier result.

Propagation is local to a block on purpose: loop counters are the only variables with more
than one definition, and a block-local map never carries `k = 0` into the loop head.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from . import ir
from .cfg import cfg_to_dict, cfg_to_mermaid, format_cfg, link_blocks, reachable
from .ir import CFG, Assign, BasicBlock, BinOp, Branch, Call, Const, Instr, Jump, Operand, Var
from .tools import TOOLS


@dataclass
class OptReport:
    before: dict[str, int]  # {"instructions": n, "calls": n}
    after: dict[str, int]
    changes: list[str] = field(default_factory=list)
    iterations: int = 0  # rounds of the four passes, including the final one that changed nothing

    def to_dict(self) -> dict:
        return {
            "before": dict(self.before),
            "after": dict(self.after),
            "changes": list(self.changes),
            "iterations": self.iterations,
        }


def _counts(cfg: CFG) -> dict[str, int]:
    return {"instructions": ir.count_instructions(cfg), "calls": ir.count_calls(cfg)}


def optimize(cfg: CFG) -> tuple[CFG, OptReport]:
    """Optimize a copy of `cfg`; the input is never mutated."""
    out = copy.deepcopy(cfg)
    link_blocks(out)
    report = OptReport(before=_counts(out), after={})
    while True:
        report.iterations += 1
        changed = False
        for opt_pass in (_fold_and_propagate, _remove_unreachable, _remove_dead, _merge_calls):
            changed |= opt_pass(out, report.changes)
        if not changed:
            break
    link_blocks(out)
    report.after = _counts(out)
    return out, report


# -------------------------------------------------- pass 1: folding + propagation


def _same_operand(a: Operand, b: Operand) -> bool:
    """Operand equality that keeps true and 1 apart (dataclass == would not)."""
    if isinstance(a, Const) and isinstance(b, Const):
        return type(a.value) is type(b.value) and a.value == b.value
    return a == b


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def fold_binop(op: str, left: object, right: object) -> Const | None:
    """The VM's result of `left op right` for well-typed constants, else None (not folded)."""
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        return Const(left + right)
    if op in ("==", "!=") and type(left) is type(right) and isinstance(left, (int, str, bool)):
        return Const((left == right) if op == "==" else (left != right))
    if not (_is_int(left) and _is_int(right)):
        return None
    results = {
        "+": lambda: left + right,
        "-": lambda: left - right,
        "*": lambda: left * right,
        "<": lambda: left < right,
        "<=": lambda: left <= right,
        ">": lambda: left > right,
        ">=": lambda: left >= right,
    }
    return Const(results[op]()) if op in results else None


def _substitute(instr: Instr, env: dict[str, Operand], changes: list[str]) -> bool:
    """Replace every operand variable that `env` maps; report one change per replacement."""

    def sub(op: Operand) -> Operand:
        if isinstance(op, Var) and op.name in env:
            new = env[op.name]
            changes.append(
                f"line {instr.line}: replaced {op.name} with {ir.format_operand(new)}"
            )
            return new
        return op

    before = len(changes)
    if isinstance(instr, Assign):
        instr.src = sub(instr.src)
    elif isinstance(instr, BinOp):
        instr.left, instr.right = sub(instr.left), sub(instr.right)
    elif isinstance(instr, ir.Index):
        instr.base, instr.index = sub(instr.base), sub(instr.index)
    elif isinstance(instr, Call):
        instr.args = [sub(a) for a in instr.args]
    elif isinstance(instr, Branch):
        instr.cond = sub(instr.cond)
    elif isinstance(instr, ir.Return):
        instr.value = sub(instr.value)
    elif isinstance(instr, ir.ParallelCalls):
        for call in instr.calls:
            call.args = [sub(a) for a in call.args]
    return len(changes) > before


def _kill(env: dict[str, Operand], name: str) -> None:
    """`name` is redefined: forget its value and every copy that reads it."""
    env.pop(name, None)
    for key in [k for k, v in env.items() if v == Var(name)]:
        del env[key]


def _fold_block(block: BasicBlock, changes: list[str]) -> bool:
    env: dict[str, Operand] = {}
    changed = False
    for pos, instr in enumerate(block.instrs):
        changed |= _substitute(instr, env, changes)
        if isinstance(instr, BinOp) and isinstance(instr.left, Const) and isinstance(instr.right, Const):
            value = fold_binop(instr.op, instr.left.value, instr.right.value)
            if value is not None:
                folded = Assign(instr.dst, value, line=instr.line, col=instr.col)
                changes.append(
                    f"line {instr.line}: folded {ir.format_instr(instr)} -> {ir.format_operand(value)}"
                )
                block.instrs[pos] = instr = folded
                changed = True
        if isinstance(instr, Branch) and isinstance(instr.cond, Const) and isinstance(instr.cond.value, bool):
            target = instr.if_true if instr.cond.value else instr.if_false
            changes.append(
                f"line {instr.line}: branch on {ir.format_operand(instr.cond)} -> goto {target}"
            )
            block.instrs[pos] = Jump(target, line=instr.line, col=instr.col)
            changed = True
        for name in ir.defined_vars(instr):
            _kill(env, name)
        if isinstance(instr, Assign) and instr.src != instr.dst:
            env[instr.dst.name] = instr.src
    return changed


def _fold_and_propagate(cfg: CFG, changes: list[str]) -> bool:
    changed = False
    for block in cfg.blocks.values():
        changed |= _fold_block(block, changes)
    if changed:
        link_blocks(cfg)
    return changed


# ------------------------------------------------------ pass 2: unreachable blocks


def _remove_unreachable(cfg: CFG, changes: list[str]) -> bool:
    link_blocks(cfg)
    live = reachable(cfg)
    dead = [label for label in cfg.blocks if label not in live]
    for label in dead:
        block = cfg.blocks.pop(label)
        line = block.instrs[0].line if block.instrs else 0
        changes.append(f"removed unreachable block {label} (line {line})")
    if dead:
        link_blocks(cfg)
    return bool(dead)


# ------------------------------------------------------- pass 3: dead assignments


def _remove_dead(cfg: CFG, changes: list[str]) -> bool:
    used = {name for block in cfg.blocks.values() for instr in block.instrs for name in ir.used_vars(instr)}
    changed = False
    for block in cfg.blocks.values():
        kept: list[Instr] = []
        for instr in block.instrs:
            if isinstance(instr, (Assign, BinOp)) and instr.dst.name not in used:
                changes.append(f"line {instr.line}: removed dead assignment {ir.format_instr(instr)}")
                changed = True
            else:
                kept.append(instr)
        block.instrs = kept
    return changed


# -------------------------------------------------- pass 4: duplicate tool calls


def _format_call(call: Call) -> str:
    return f"{call.tool}({', '.join(ir.format_operand(a) for a in call.args)})"


def _same_call(a: Call, b: Call) -> bool:
    return (
        a.tool == b.tool
        and len(a.args) == len(b.args)
        and all(_same_operand(x, y) for x, y in zip(a.args, b.args))
    )


def _merge_block(block: BasicBlock, changes: list[str]) -> bool:
    earlier: Call | None = None
    redefined: set[str] = set()  # variables defined after `earlier`
    changed = False
    for pos, instr in enumerate(block.instrs):
        if isinstance(instr, Call):
            spec = TOOLS.get(instr.tool)
            watched = {earlier.dst.name, *ir.used_vars(earlier)} if earlier else set()
            if (
                earlier is not None
                and spec is not None
                and spec.mergeable
                and _same_call(earlier, instr)
                and earlier.dst.name not in ir.used_vars(earlier)
                and not (watched & redefined)
            ):
                block.instrs[pos] = Assign(instr.dst, Var(earlier.dst.name), line=instr.line, col=instr.col)
                changes.append(
                    f"line {instr.line}: duplicate call {_format_call(instr)} replaced by copy of "
                    f"{earlier.dst.name} (line {earlier.line})"
                )
                changed = True
                redefined.add(instr.dst.name)
                continue
            earlier, redefined = instr, set()
        elif isinstance(instr, ir.ParallelCalls):
            earlier, redefined = None, set()  # never produced before scheduling; be conservative
        else:
            redefined.update(ir.defined_vars(instr))
    return changed


def _merge_calls(cfg: CFG, changes: list[str]) -> bool:
    changed = False
    for block in cfg.blocks.values():
        changed |= _merge_block(block, changes)
    return changed


# ----------------------------------------------------------------------- artifact


def _total(reports: list[OptReport], key: str) -> dict[str, int]:
    return {
        "instructions": sum(getattr(r, key)["instructions"] for r in reports),
        "calls": sum(getattr(r, key)["calls"] for r in reports),
    }


def _report_text(cfg: CFG, report: OptReport) -> str:
    b, a = report.before, report.after
    lines = [
        format_cfg(cfg),
        f"instructions {b['instructions']} -> {a['instructions']}, "
        f"tool calls {b['calls']} -> {a['calls']}",
    ]
    if report.changes:
        lines.append("changes:")
        lines.extend(f"  {c}" for c in report.changes)
    else:
        lines.append("changes: none")
    return "\n".join(lines)


def optimized_artifact(results: list[tuple[CFG, OptReport]]) -> dict:
    """Phase artifact `optimized_ir`: optimized CFG per task plus the before/after report."""
    tasks = []
    for cfg, report in results:
        entry = cfg_to_dict(cfg)
        entry["mermaid"] = cfg_to_mermaid(cfg)
        tasks.append({"name": cfg.name, "cfg": entry, "report": report.to_dict()})
    reports = [r for _, r in results]
    return {
        "text": "\n\n".join(_report_text(c, r) for c, r in results),
        "data": {"tasks": tasks, "before": _total(reports, "before"), "after": _total(reports, "after")},
    }
