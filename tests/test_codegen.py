"""Tests for agentscript.codegen: layout, jump omission, address resolution, stack balance,
and end-to-end runs (codegen + vm.run) over the examples on unoptimized CFGs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentscript import ir
from agentscript.bytecode import BInstr, BytecodeProgram, Op, format_program
from agentscript.cfg import build_cfg, link_blocks
from agentscript.codegen import bytecode_artifact, generate
from agentscript.diagnostics import AgentRuntimeError
from agentscript.irgen import lower
from agentscript.lexer import tokenize
from agentscript.parser import parse
from agentscript.registry import MockRegistry
from agentscript.semantic import analyze
from agentscript.typesys import BOOL, INT
from agentscript.vm import run

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text())
RUNNABLE = [e for e in MANIFEST if e["run"] is not None]

STACK_EFFECT = {
    Op.PUSH_CONST: 1,
    Op.LOAD: 1,
    Op.STORE: -1,
    Op.INDEX: -1,
    Op.JUMP: 0,
    Op.JUMP_IF_FALSE: -1,
    Op.RETURN: -1,
    **{op: -1 for op in (Op.ADD, Op.SUB, Op.MUL, Op.EQ, Op.NE, Op.LT, Op.LE, Op.GT, Op.GE)},
}


# ---------------------------------------------------------------- helpers


def front_end(source: str):
    agent = parse(tokenize(source))
    analyze(agent)
    return agent, [build_cfg(fn) for fn in lower(agent)]


def compile_source(source: str) -> BytecodeProgram:
    agent, cfgs = front_end(source)
    return generate(agent, cfgs)


def compile_example(file: str) -> BytecodeProgram:
    return compile_source((EXAMPLES / file).read_text())


def agent_src(body: str, params: str = "x: int", ret: str = "int", permits: str = "web_search, llm", budget: int = 10) -> str:
    return f"agent A {{\n  permit {permits};\n  budget calls = {budget};\n  task t({params}) -> {ret} {{\n{body}\n  }}\n}}\n"


def code_of(source: str, task: str = "t") -> list[BInstr]:
    return compile_source(source).tasks[task].code


def ops(code: list[BInstr]) -> list[Op]:
    return [i.op for i in code]


def effect(instr: BInstr) -> int:
    if instr.op is Op.CALL:
        return 1 - instr.arg2
    if instr.op is Op.CALL_PARALLEL:
        return sum(1 - argc for _, argc in instr.arg)
    return STACK_EFFECT[instr.op]


def stack_depths(code: list[BInstr]) -> list[int]:
    """Stack depth after each instruction of straight-line code; never negative."""
    depth, depths = 0, []
    for instr in code:
        needed = {Op.CALL: instr.arg2 or 0}.get(instr.op, 0)
        if instr.op is Op.CALL_PARALLEL:
            needed = sum(argc for _, argc in instr.arg)
        elif instr.op in (Op.STORE, Op.JUMP_IF_FALSE, Op.RETURN):
            needed = 1
        elif instr.op in (Op.INDEX, Op.ADD, Op.SUB, Op.MUL, Op.EQ, Op.NE, Op.LT, Op.LE, Op.GT, Op.GE):
            needed = 2
        assert depth >= needed, f"stack underflow at {instr.format()}"
        depth += effect(instr)
        depths.append(depth)
    return depths


def run_example(file: str, task: str, args: dict, confirm: bool = True):
    return run(compile_example(file), task, args, MockRegistry(confirm_answer=confirm))


def runtime_error(file: str, task: str, args: dict) -> AgentRuntimeError:
    with pytest.raises(AgentRuntimeError) as info:
        run_example(file, task, args)
    return info.value


# ---------------------------------------------------------------- program shape


def test_program_header_from_agent():
    prog = compile_example("valid_report.as")
    assert prog.agent == "Assistant"
    assert prog.permits == ["web_search", "llm", "sanitize", "send_email", "confirm"]
    assert prog.budget == 5
    task = prog.tasks["report"]
    assert task.name == "report"
    assert task.params == [("topic", "string")]
    assert task.return_type == "bool"


def test_list_param_types_are_text():
    src = agent_src("    return xs[0];", params="xs: list<list<string>>, n: int", ret="list<string>")
    task = compile_source(src).tasks["t"]
    assert task.params == [("xs", "list<list<string>>"), ("n", "int")]
    assert task.return_type == "list<string>"


def test_one_task_per_cfg_in_order():
    src = (
        "agent A {\n  permit llm;\n  budget calls = 1;\n"
        "  task b() -> int { return 1; }\n  task a() -> int { return 2; }\n}\n"
    )
    prog = compile_source(src)
    assert list(prog.tasks) == ["b", "a"]


def test_generate_is_deterministic():
    first = compile_example("valid_report.as").to_dict()
    second = compile_example("valid_report.as").to_dict()
    assert first == second


def test_artifact_text_and_data():
    prog = compile_example("valid_report.as")
    art = bytecode_artifact(prog)
    assert art["text"] == format_program(prog)
    assert art["data"] == prog.to_dict()
    json.dumps(art)  # JSON-serializable
    assert "CALL web_search 1" in art["text"]


# ---------------------------------------------------------------- per-instruction lowering


def test_assign_const_and_var():
    code = code_of(agent_src('    let a = 5;\n    let b = a;\n    let s = "hi";\n    return b;'))
    assert [(i.op, i.arg) for i in code] == [
        (Op.PUSH_CONST, 5),
        (Op.STORE, "a"),
        (Op.LOAD, "a"),
        (Op.STORE, "b"),
        (Op.PUSH_CONST, "hi"),
        (Op.STORE, "s"),
        (Op.LOAD, "b"),
        (Op.RETURN, None),
    ]


@pytest.mark.parametrize(
    "op,expected",
    [("+", Op.ADD), ("-", Op.SUB), ("*", Op.MUL), ("<", Op.LT), ("<=", Op.LE), (">", Op.GT), (">=", Op.GE)],
)
def test_binop_operators(op, expected):
    ret = "int" if op in "+-*" else "bool"
    code = code_of(agent_src(f"    let r = x {op} 2;\n    return r;", ret=ret))
    assert [(i.op, i.arg) for i in code[:4]] == [(Op.LOAD, "x"), (Op.PUSH_CONST, 2), (expected, None), (Op.STORE, "r")]


@pytest.mark.parametrize("op,expected", [("==", Op.EQ), ("!=", Op.NE)])
def test_equality_operators(op, expected):
    code = code_of(agent_src(f"    let r = x {op} 2;\n    return r;", ret="bool"))
    assert code[2].op is expected


def test_index_lowering():
    code = code_of(agent_src("    let r = xs[1];\n    return r;", params="xs: list<string>", ret="string"))
    assert [(i.op, i.arg) for i in code[:4]] == [(Op.LOAD, "xs"), (Op.PUSH_CONST, 1), (Op.INDEX, None), (Op.STORE, "r")]


def test_call_lowering_pushes_args_in_order():
    src = agent_src('    let ok = send_email("a@b.c", s);\n    return ok;', params="s: string", ret="bool", permits="send_email")
    code = code_of(src)
    assert [(i.op, i.arg, i.arg2) for i in code[:4]] == [
        (Op.PUSH_CONST, "a@b.c", None),
        (Op.LOAD, "s", None),
        (Op.CALL, "send_email", 2),
        (Op.STORE, "ok", None),
    ]


def test_expression_statement_result_stored_in_temp():
    code = code_of(agent_src('    llm("hi");\n    return 1;'))
    assert [(i.op, i.arg) for i in code[:3]] == [(Op.PUSH_CONST, "hi"), (Op.CALL, "llm"), (Op.STORE, "t1")]


def test_return_bool_literal():
    code = code_of(agent_src("    return false;", ret="bool"))
    assert [(i.op, i.arg) for i in code] == [(Op.PUSH_CONST, False), (Op.RETURN, None)]


def test_every_instruction_carries_ir_location():
    prog = compile_example("valid_report.as")
    code = prog.tasks["report"].code
    assert all(i.line > 0 and i.col > 0 for i in code)
    calls = {i.arg: (i.line, i.col) for i in code if i.op is Op.CALL}
    assert calls["web_search"] == (6, 15)
    assert calls["send_email"] == (10, 14)


def test_locations_match_ir_instructions():
    agent, cfgs = front_end((EXAMPLES / "valid_report.as").read_text())
    code = generate(agent, cfgs).tasks["report"].code
    ir_locs = {(i.line, i.col) for b in cfgs[0].blocks.values() for i in b.instrs}
    assert {(i.line, i.col) for i in code} <= ir_locs


# ---------------------------------------------------------------- layout, jumps, addresses


IF_ELSE = agent_src("    if (x < 3) {\n      let a = 1;\n    } else {\n      let b = 2;\n    }\n    return x;")


def test_if_else_layout_and_addresses():
    code = code_of(IF_ELSE)
    assert [(i.op, i.arg) for i in code] == [
        (Op.LOAD, "x"),
        (Op.PUSH_CONST, 3),
        (Op.LT, None),
        (Op.STORE, "t1"),
        (Op.LOAD, "t1"),
        (Op.JUMP_IF_FALSE, 9),  # else block (L2)
        # then block (L1) is next: the JUMP to it is omitted
        (Op.PUSH_CONST, 1),
        (Op.STORE, "a"),
        (Op.JUMP, 11),  # goto Lend over the else block
        (Op.PUSH_CONST, 2),
        (Op.STORE, "b"),
        # else's goto Lend falls through: omitted
        (Op.LOAD, "x"),
        (Op.RETURN, None),
    ]


@pytest.mark.parametrize("x,expected", [(1, "then"), (5, "else")])
def test_if_else_runs_correct_branch(x, expected):
    src = agent_src('    if (x < 3) {\n      return "then";\n    } else {\n      return "else";\n    }', ret="string")
    assert run(compile_source(src), "t", {"x": x}, MockRegistry()).value == expected


def test_branch_emits_jump_when_true_target_is_not_next():
    # Build a CFG whose true target is laid out after the false target.
    then = ir.BasicBlock("T", [ir.Return(ir.Const(1), line=3, col=1)])
    other = ir.BasicBlock("F", [ir.Return(ir.Const(2), line=4, col=1)])
    entry = ir.BasicBlock("entry", [ir.Branch(ir.Var("c"), "T", "F", line=2, col=5)])
    cfg = ir.CFG("t", [("c", BOOL)], INT, {"entry": entry, "F": other, "T": then})
    link_blocks(cfg)
    agent, _ = front_end(agent_src("    return 1;"))
    code = generate(agent, [cfg]).tasks["t"].code
    assert [(i.op, i.arg) for i in code] == [
        (Op.LOAD, "c"),
        (Op.JUMP_IF_FALSE, 3),
        (Op.JUMP, 5),
        (Op.PUSH_CONST, 2),
        (Op.RETURN, None),
        (Op.PUSH_CONST, 1),
        (Op.RETURN, None),
    ]
    assert all((i.line, i.col) == (2, 5) for i in code[:3])
    prog = generate(agent, [cfg])
    assert run(prog, "t", {"c": True}, MockRegistry()).value == 1
    assert run(prog, "t", {"c": False}, MockRegistry()).value == 2


def test_jump_to_empty_block_resolves_to_following_block():
    # A block whose only instruction is a goto to the next block emits nothing; jumps to it
    # resolve to the next block's start address.
    blocks = {
        "entry": ir.BasicBlock("entry", [ir.Jump("B", line=1, col=1)]),
        "A": ir.BasicBlock("A", [ir.Return(ir.Const(0), line=2, col=1)]),
        "B": ir.BasicBlock("B", [ir.Jump("C", line=3, col=1)]),
        "C": ir.BasicBlock("C", [ir.Return(ir.Const(7), line=4, col=1)]),
    }
    cfg = ir.CFG("t", [], INT, blocks)
    link_blocks(cfg)
    agent, _ = front_end(agent_src("    return 1;"))
    code = generate(agent, [cfg]).tasks["t"].code
    assert [(i.op, i.arg) for i in code] == [
        (Op.JUMP, 3),
        (Op.PUSH_CONST, 0),
        (Op.RETURN, None),
        (Op.PUSH_CONST, 7),
        (Op.RETURN, None),
    ]
    assert run(generate(agent, [cfg]), "t", {}, MockRegistry()).value == 7


def test_repeat_layout_and_backward_jump():
    src = agent_src('    repeat 2 {\n      let c = llm("q");\n    }\n    return x;')
    code = code_of(src)
    assert [(i.op, i.arg) for i in code] == [
        (Op.PUSH_CONST, 0),
        (Op.STORE, "t1"),
        (Op.PUSH_CONST, 2),
        (Op.STORE, "t2"),
        # goto Lhead falls through: omitted; Lhead starts at 4
        (Op.LOAD, "t1"),
        (Op.LOAD, "t2"),
        (Op.LT, None),
        (Op.STORE, "t3"),
        (Op.LOAD, "t3"),
        (Op.JUMP_IF_FALSE, 18),  # Lexit
        # Lbody is next: no JUMP
        (Op.PUSH_CONST, "q"),
        (Op.CALL, "llm"),
        (Op.STORE, "c"),
        (Op.LOAD, "t1"),
        (Op.PUSH_CONST, 1),
        (Op.ADD, None),
        (Op.STORE, "t1"),
        (Op.JUMP, 4),  # back edge to Lhead
        (Op.LOAD, "x"),
        (Op.RETURN, None),
    ]


@pytest.mark.parametrize("n,calls", [(0, 0), (1, 1), (3, 3)])
def test_repeat_runs_n_times(n, calls):
    src = agent_src('    repeat x {\n      let c = llm("q");\n    }\n    return x;')
    result = run(compile_source(src), "t", {"x": n}, MockRegistry())
    assert result.value == n
    assert result.calls_used == calls


def test_negative_repeat_count_runs_zero_times():
    src = agent_src('    repeat x {\n      let c = llm("q");\n    }\n    return x;')
    assert run(compile_source(src), "t", {"x": -2}, MockRegistry()).calls_used == 0


def test_all_jump_targets_in_range():
    for entry in MANIFEST:
        if entry["expect"] is not None:
            continue
        for task in compile_example(entry["file"]).tasks.values():
            for instr in task.code:
                if instr.op in (Op.JUMP, Op.JUMP_IF_FALSE):
                    assert isinstance(instr.arg, int) and 0 <= instr.arg < len(task.code)


def test_no_jump_to_next_instruction():
    for entry in MANIFEST:
        if entry["expect"] is not None:
            continue
        for task in compile_example(entry["file"]).tasks.values():
            for addr, instr in enumerate(task.code):
                if instr.op is Op.JUMP:
                    assert instr.arg != addr + 1


# ---------------------------------------------------------------- stack balance


def test_straight_line_stack_balance():
    src = agent_src(
        '    let a = x + 2 * 3;\n    let r = web_search("q");\n    let s = r[0] + "!";\n'
        "    let b = a == 5;\n    let c = llm(s);\n    return a;"
    )
    code = code_of(src)
    assert all(i.op not in (Op.JUMP, Op.JUMP_IF_FALSE) for i in code)
    depths = stack_depths(code)
    # every statement leaves the stack empty: depth 0 after each STORE
    assert all(d == 0 for i, d in zip(code, depths) if i.op is Op.STORE)
    assert depths[-1] == 0
    assert max(depths) <= 2


def consistent_depths(code: list[BInstr]) -> dict[int, int]:
    """Stack depth before each reachable address, following every jump; asserts that all
    paths agree on the depth at each address and that no instruction underflows."""
    before: dict[int, int] = {0: 0}
    work = [0]
    while work:
        addr = work.pop()
        instr = code[addr]
        after = stack_depths_from(before[addr], instr)
        if instr.op is Op.RETURN:
            assert after == 0, f"RETURN at {addr} leaves {after} values on the stack"
            continue
        succs = {Op.JUMP: [instr.arg], Op.JUMP_IF_FALSE: [instr.arg, addr + 1]}.get(instr.op, [addr + 1])
        for succ in succs:
            assert 0 <= succ < len(code), f"control falls off the code at {addr}"
            if succ in before:
                assert before[succ] == after, f"inconsistent stack depth at {succ}"
            else:
                before[succ] = after
                work.append(succ)
    return before


def stack_depths_from(depth: int, instr: BInstr) -> int:
    """Depth after one instruction, checking that it does not underflow."""
    prefix = [BInstr(Op.PUSH_CONST, 0)] * depth
    return stack_depths(prefix + [instr])[-1]


def test_every_path_is_stack_balanced():
    for entry in MANIFEST:
        if entry["expect"] is not None:
            continue
        for task in compile_example(entry["file"]).tasks.values():
            depths = consistent_depths(task.code)
            targets = {i.arg for i in task.code if i.op in (Op.JUMP, Op.JUMP_IF_FALSE)}
            # every jump lands on a block start, where the stack is empty
            assert all(depths[t] == 0 for t in targets if t in depths)


def test_if_else_and_repeat_paths_balanced():
    for src in (IF_ELSE, agent_src('    repeat x {\n      let c = llm("q");\n    }\n    return x;')):
        depths = consistent_depths(code_of(src))
        assert set(depths.values()) <= {0, 1, 2}


# ---------------------------------------------------------------- end to end over the examples


def test_valid_report_runs_five_calls():
    result = run_example("valid_report.as", "report", {"topic": "AI safety"})
    assert result.value is True
    assert [c.tool for c in result.calls] == ["web_search", "sanitize", "llm", "confirm", "send_email"]
    assert result.calls_used == 5
    assert result.budget == 5
    assert result.rounds == 5
    assert result.calls[0].args == ["AI safety"]
    assert "[removed instruction]" in result.calls[1].result
    assert result.calls[4].args[0] == "me@example.com"


def test_valid_report_confirm_denied():
    result = run_example("valid_report.as", "report", {"topic": "AI safety"}, confirm=False)
    assert result.value is False
    assert [c.tool for c in result.calls] == ["web_search", "sanitize", "llm", "confirm"]


@pytest.mark.parametrize("confirm,expected,ncalls", [(True, True, 2), (False, False, 1)])
def test_valid_cleanup(confirm, expected, ncalls):
    result = run_example("valid_cleanup.as", "cleanup", {"path": "/tmp/old.log"}, confirm=confirm)
    assert result.value is expected
    assert result.calls_used == ncalls
    assert result.calls[0].tool == "confirm"
    assert result.calls[0].args == ["Delete /tmp/old.log?"]
    if confirm:
        assert result.calls[1].tool == "delete_file"


def test_optimize_demo_unoptimized_returns_string():
    result = run_example("optimize_demo.as", "research", {"topic": "compilers"})
    assert isinstance(result.value, str)
    assert result.value.startswith("[llm] Compare: ")
    assert [c.tool for c in result.calls] == ["web_search", "web_search", "llm"]


def test_runtime_budget_within_budget():
    result = run_example("runtime_budget.as", "poll", {"topic": "news", "times": 2})
    assert result.value == 2
    assert result.calls_used == 2


def test_runtime_budget_exceeded():
    err = runtime_error("runtime_budget.as", "poll", {"topic": "news", "times": 5})
    diag = err.diagnostic
    assert (diag.code, diag.phase, diag.line, diag.col) == ("E601", "runtime", 7, 15)
    assert err.calls_used == 3


def test_runtime_index_out_of_range():
    err = runtime_error("runtime_index.as", "tenth", {"topic": "AI"})
    diag = err.diagnostic
    assert (diag.code, diag.line, diag.col) == ("E603", 7, 19)
    assert err.calls_used == 1


@pytest.mark.parametrize("entry", RUNNABLE, ids=lambda e: e["file"])
def test_manifest_runs(entry):
    spec = entry["run"]
    expect = spec["expect"]
    if expect is None:
        result = run_example(entry["file"], spec["task"], spec["args"])
        assert result.calls_used <= result.budget
        json.dumps(result.to_dict())
    else:
        err = runtime_error(entry["file"], spec["task"], spec["args"])
        diag = err.diagnostic
        assert (diag.code, diag.phase, diag.line, diag.col) == (
            expect["code"],
            expect["phase"],
            expect["line"],
            expect["col"],
        )


# ---------------------------------------------------------------- parallel calls (M7)


def _parallelize_first_three_calls(cfg: ir.CFG) -> None:
    """Hand-made schedule for parallel_demo: the three web_search calls become one round."""
    block = cfg.blocks["entry"]
    calls = [i for i in block.instrs if isinstance(i, ir.Call) and i.tool == "web_search"]
    assert len(calls) == 3
    group = ir.ParallelCalls(calls, line=calls[0].line, col=calls[0].col)
    rest = [i for i in block.instrs if i not in calls]
    block.instrs = [group] + rest


def test_parallel_calls_lowering():
    agent, cfgs = front_end((EXAMPLES / "parallel_demo.as").read_text())
    _parallelize_first_three_calls(cfgs[0])
    code = generate(agent, cfgs).tasks["scout"].code
    assert [(i.op, i.arg) for i in code[:7]] == [
        (Op.LOAD, "a"),
        (Op.LOAD, "b"),
        (Op.LOAD, "c"),
        (Op.CALL_PARALLEL, [("web_search", 1), ("web_search", 1), ("web_search", 1)]),
        (Op.STORE, "rc"),
        (Op.STORE, "rb"),
        (Op.STORE, "ra"),
    ]
    assert [i.line for i in code[:7]] == [6, 7, 8, 6, 8, 7, 6]
    assert stack_depths(code[:7])[-1] == 0


def test_parallel_demo_runs_one_round_of_three():
    agent, cfgs = front_end((EXAMPLES / "parallel_demo.as").read_text())
    _parallelize_first_three_calls(cfgs[0])
    prog = generate(agent, cfgs)
    result = run(prog, "scout", {"a": "rust", "b": "go", "c": "zig"}, MockRegistry())
    assert [c.tool for c in result.calls] == ["web_search"] * 3 + ["llm"]
    assert [c.args for c in result.calls[:3]] == [["rust"], ["go"], ["zig"]]
    assert [c.round for c in result.calls] == [1, 1, 1, 2]
    assert result.rounds == 2
    # each result landed in the right variable
    assert result.value == "[llm] rust: overview article | go: overview article | zig: overview article"[:120]


def test_parallel_demo_matches_sequential_value():
    sequential = run_example("parallel_demo.as", "scout", {"a": "rust", "b": "go", "c": "zig"})
    assert sequential.rounds == 4
    agent, cfgs = front_end((EXAMPLES / "parallel_demo.as").read_text())
    _parallelize_first_three_calls(cfgs[0])
    parallel = run(generate(agent, cfgs), "scout", {"a": "rust", "b": "go", "c": "zig"}, MockRegistry())
    assert parallel.value == sequential.value


def test_parallel_demo_via_scheduler():
    scheduler = pytest.importorskip("agentscript.scheduler")
    agent, cfgs = front_end((EXAMPLES / "parallel_demo.as").read_text())
    scheduled = [scheduler.schedule(cfg)[0] for cfg in cfgs]
    result = run(generate(agent, scheduled), "scout", {"a": "rust", "b": "go", "c": "zig"}, MockRegistry())
    assert result.rounds == 2
    assert [c.round for c in result.calls] == [1, 1, 1, 2]


def test_parallel_calls_carry_member_locations():
    agent, cfgs = front_end((EXAMPLES / "parallel_demo.as").read_text())
    _parallelize_first_three_calls(cfgs[0])
    code = generate(agent, cfgs).tasks["scout"].code
    group = code[3]
    assert group.op is Op.CALL_PARALLEL
    assert [tuple(loc) for loc in group.arg2] == [(c.line, c.col) for c in cfgs[0].blocks["entry"].instrs[0].calls]
    assert [loc[0] for loc in group.arg2] == [6, 7, 8]
    assert group.to_dict()["arg2"] == [list(loc) for loc in group.arg2]
    result = run(generate(agent, cfgs), "scout", {"a": "rust", "b": "go", "c": "zig"}, MockRegistry())
    assert [c.line for c in result.calls] == [6, 7, 8, 9]
