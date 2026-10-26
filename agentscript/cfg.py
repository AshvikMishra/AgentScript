"""Basic blocks, the control-flow graph, reachability and dominators.

build_cfg splits a task's linear IR (irgen.lower) into basic blocks:

- the first block is `entry`; a new block starts at every Label and after every terminator
  (Jump/Branch/Return);
- code after a terminator that has no label gets a generated label `U1, U2, ...` (it is
  unreachable);
- a block that falls through into a label gets an explicit `goto`; a trailing block that
  falls off the end of the listing (only possible in unreachable code of a valid program)
  gets `goto <itself>`, so every block ends with exactly one terminator.

Dominators use the simple iterative algorithm over the reachable blocks:
Dom(entry) = {entry}; Dom(n) = {n} | intersection of Dom(p) over reachable preds p,
iterated in layout order until nothing changes.
"""

from __future__ import annotations

from . import ir
from .ir import CFG, BasicBlock, IRFunction
from .irgen import instr_to_dict


def build_cfg(fn: IRFunction) -> CFG:
    blocks: dict[str, BasicBlock] = {}
    unreachable_count = 0
    current: BasicBlock | None = BasicBlock("entry", [])
    blocks["entry"] = current

    for instr in fn.instrs:
        if isinstance(instr, ir.Label):
            if current is not None:
                current.instrs.append(ir.Jump(instr.name, line=instr.line, col=instr.col))
            current = BasicBlock(instr.name, [])
            blocks[instr.name] = current
            continue
        if current is None:
            unreachable_count += 1
            current = BasicBlock(f"U{unreachable_count}", [])
            blocks[current.label] = current
        current.instrs.append(instr)
        if isinstance(instr, ir.TERMINATORS):
            current = None

    if current is not None:
        last = current.instrs[-1] if current.instrs else None
        line, col = (last.line, last.col) if last is not None else (0, 0)
        current.instrs.append(ir.Jump(current.label, line=line, col=col))

    cfg = CFG(fn.name, list(fn.params), fn.return_type, blocks)
    link_blocks(cfg)
    return cfg


def successors(block: BasicBlock) -> list[str]:
    term = block.terminator
    if isinstance(term, ir.Jump):
        return [term.target]
    if isinstance(term, ir.Branch):
        return [term.if_true, term.if_false]
    return []


def link_blocks(cfg: CFG) -> None:
    """(Re)compute succs and preds from the terminators; preds follow layout order."""
    for block in cfg.blocks.values():
        block.succs = successors(block)
        block.preds = []
    for block in cfg.blocks.values():
        for succ in block.succs:
            preds = cfg.blocks[succ].preds
            if block.label not in preds:
                preds.append(block.label)


def reachable(cfg: CFG) -> set[str]:
    seen = {cfg.entry}
    stack = [cfg.entry]
    while stack:
        for succ in cfg.blocks[stack.pop()].succs:
            if succ not in seen:
                seen.add(succ)
                stack.append(succ)
    return seen


def dominators(cfg: CFG) -> dict[str, set[str]]:
    """Dominator sets of the reachable blocks (keys in layout order)."""
    live = reachable(cfg)
    order = [label for label in cfg.blocks if label in live]
    dom: dict[str, set[str]] = {label: set(live) for label in order}
    dom[cfg.entry] = {cfg.entry}
    changed = True
    while changed:
        changed = False
        for label in order:
            if label == cfg.entry:
                continue
            preds = [p for p in cfg.blocks[label].preds if p in live]
            new = set.intersection(*(dom[p] for p in preds)) if preds else set()
            new = new | {label}
            if new != dom[label]:
                dom[label] = new
                changed = True
    return dom


def immediate_dominators(cfg: CFG) -> dict[str, str | None]:
    """idom of each reachable block (None for the entry).

    The immediate dominator is the strict dominator that every other strict dominator
    dominates, i.e. the one with the largest dominator set.
    """
    dom = dominators(cfg)
    idom: dict[str, str | None] = {}
    for label, doms in dom.items():
        strict = doms - {label}
        idom[label] = max(strict, key=lambda d: len(dom[d])) if strict else None
    return idom


# -------------------------------------------------------------------- printing


def format_cfg(cfg: CFG) -> str:
    """Per block: label, preds, succs, then the instructions with their source lines."""
    live = reachable(cfg)
    params = ", ".join(f"{n}: {t}" for n, t in cfg.params)
    out = [f"task {cfg.name}({params}) -> {cfg.return_type}"]
    for block in cfg.blocks.values():
        head = f"  {block.label}:"
        if block.label not in live:
            head += "  (unreachable)"
        out.append(head)
        out.append(f"      preds: {', '.join(block.preds) or '-'}")
        out.append(f"      succs: {', '.join(block.succs) or '-'}")
        for instr in block.instrs:
            out.append(f"      {ir.format_instr(instr):<40} ; line {instr.line}")
    return "\n".join(out)


def cfg_to_dict(cfg: CFG) -> dict:
    live = reachable(cfg)
    return {
        "name": cfg.name,
        "entry": cfg.entry,
        "blocks": [
            {
                "label": block.label,
                "instrs": [instr_to_dict(i) for i in block.instrs],
                "succs": list(block.succs),
                "preds": list(block.preds),
                "reachable": block.label in live,
            }
            for block in cfg.blocks.values()
        ],
    }


def _mermaid_escape(text: str) -> str:
    """Make text safe inside a quoted Mermaid label (entity codes, no raw quotes/HTML)."""
    text = text.replace("#", "#35;")  # first: every later replacement introduces '#'
    for ch, code in (
        ('"', "#quot;"),
        ("&", "#amp;"),
        ("<", "#lt;"),
        (">", "#gt;"),
        ("`", "#96;"),
        ("\\", "#92;"),
    ):
        text = text.replace(ch, code)
    return text


def cfg_to_mermaid(cfg: CFG) -> str:
    """A `flowchart TD` with one node per block; Branch edges are labelled T and F."""
    live = reachable(cfg)
    node_ids = {label: f"B{i}" for i, label in enumerate(cfg.blocks)}
    lines = ["flowchart TD"]
    for block in cfg.blocks.values():
        title = block.label + ("  (unreachable)" if block.label not in live else "")
        rows = [title] + [ir.format_instr(i) for i in block.instrs]
        text = "<br/>".join(_mermaid_escape(r) for r in rows)
        lines.append(f'  {node_ids[block.label]}["{text}"]')
    for block in cfg.blocks.values():
        src = node_ids[block.label]
        if isinstance(block.terminator, ir.Branch):
            true_target, false_target = block.succs
            lines.append(f"  {src} -->|T| {node_ids[true_target]}")
            lines.append(f"  {src} -->|F| {node_ids[false_target]}")
        else:
            for succ in block.succs:
                lines.append(f"  {src} --> {node_ids[succ]}")
    dead = [node_ids[label] for label in cfg.blocks if label not in live]
    if dead:
        lines.append("  classDef unreachable stroke-dasharray: 5 5")
        lines.append(f"  class {','.join(dead)} unreachable")
    return "\n".join(lines)


def cfg_artifact(cfgs: list[CFG]) -> dict:
    tasks = []
    for cfg in cfgs:
        entry = cfg_to_dict(cfg)
        entry["mermaid"] = cfg_to_mermaid(cfg)
        entry["dominators"] = {label: sorted(d) for label, d in dominators(cfg).items()}
        tasks.append(entry)
    return {"text": "\n\n".join(format_cfg(c) for c in cfgs), "data": {"tasks": tasks}}
