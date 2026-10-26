"""The compiler driver: runs every phase in order and collects artifacts and diagnostics.

`compile_source` never raises: a phase error (CompileError) becomes the one error diagnostic,
and an unexpected Python exception becomes an internal E000 diagnostic, so the API never
answers 500 on user input. Phases after the failing one stay null. `CompileResult.to_dict()`
is the `/compile` response and `run_source` builds the `/run` response (brief section 7).

The phases are recursive over the AST, so compilation runs in a worker thread with a large
stack and a raised recursion limit; with the parser's MAX_NESTING bound, no valid program
can hit Python's recursion limit.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import ast_nodes as ast
from .approval import ApprovalReport, analyze_approval
from .ast_nodes import ast_to_dict, format_ast
from .bytecode import BytecodeProgram
from .cfg import build_cfg, cfg_artifact
from .codegen import bytecode_artifact, generate
from .diagnostics import AgentRuntimeError, CompileError, Diagnostic, make_diagnostic
from .ir import CFG, IRFunction
from .irgen import ir_artifact, lower
from .lexer import Token, tokenize, tokens_artifact
from .optimizer import OptReport, optimize, optimized_artifact
from .parser import parse
from .registry import LiveRegistry, MockRegistry, ToolRegistry
from .scheduler import ScheduleReport, schedule, schedule_artifact
from .semantic import SemanticResult, analyze
from .taint import TaintReport, analyze_taint
from .vm import RunResult, run

PHASES: tuple[str, ...] = (
    "tokens",
    "ast",
    "symbols",
    "ir",
    "cfg",
    "taint",
    "approval",
    "optimized_ir",
    "schedule",
    "bytecode",
)


@dataclass
class CompileResult:
    ok: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)
    phases: dict[str, dict | None] = field(default_factory=lambda: {p: None for p in PHASES})
    stats: dict | None = None
    tasks: list[dict] = field(default_factory=list)
    program: BytecodeProgram | None = None
    # intermediate objects, for tests and the CLI
    tokens: list[Token] | None = None
    agent: ast.Agent | None = None
    semantic: SemanticResult | None = None
    functions: list[IRFunction] | None = None
    cfgs: list[CFG] | None = None
    taint: TaintReport | None = None
    approval: ApprovalReport | None = None
    optimized: list[tuple[CFG, OptReport]] | None = None
    scheduled: list[tuple[CFG, ScheduleReport]] | None = None

    @property
    def error(self) -> Diagnostic | None:
        return next((d for d in self.diagnostics if d.severity == "error"), None)

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "warnings_count": len(self.warnings),
            "phases": {p: self.phases.get(p) for p in PHASES},
            "stats": self.stats,
            "tasks": self.tasks,
        }

    def format_diagnostics(self) -> str:
        return "\n".join(d.format() for d in self.diagnostics)


# ------------------------------------------------------------------------ compile


def _task_signatures(agent: ast.Agent) -> list[dict]:
    return [
        {
            "name": t.name,
            "params": [{"name": p.name, "type": str(p.declared_type)} for p in t.params],
            "return_type": str(t.return_type),
        }
        for t in agent.tasks
    ]


def _internal_error(exc: Exception) -> Diagnostic:
    message = f"internal compiler error: {type(exc).__name__}: {exc}"
    return make_diagnostic("E000", message, 0, 0)


class _Driver:
    """Runs the stages in order; `self.current` names the phase being run (for error artifacts)."""

    def __init__(self, source: str, parallel: bool):
        self.source = source
        self.parallel = parallel
        self.result = CompileResult()
        self.current = "tokens"

    def compile(self) -> CompileResult:
        res = self.result
        try:
            self._run_stages()
            res.ok = True
        except CompileError as err:
            res.diagnostics.append(err.diagnostic)
            artifact = getattr(err, "artifact", None)
            if artifact is not None:
                res.phases[self.current] = artifact
        except Exception as exc:  # never let user input crash the API
            res.diagnostics.append(_internal_error(exc))
        if not res.ok:
            res.program = None
        return res

    def _run_stages(self) -> None:
        res = self.result
        phases = res.phases

        self.current = "tokens"
        res.tokens = tokenize(self.source)
        phases["tokens"] = tokens_artifact(res.tokens)

        self.current = "ast"
        res.agent = parse(res.tokens)
        phases["ast"] = {"text": format_ast(res.agent), "data": ast_to_dict(res.agent)}
        res.tasks = _task_signatures(res.agent)

        self.current = "symbols"
        res.semantic = analyze(res.agent)
        res.diagnostics.extend(res.semantic.warnings)
        phases["symbols"] = res.semantic.artifact()
        # re-render so the AST tab shows the static type of every expression
        phases["ast"] = {"text": format_ast(res.agent), "data": ast_to_dict(res.agent)}

        self.current = "ir"
        res.functions = lower(res.agent)
        phases["ir"] = ir_artifact(res.functions)

        self.current = "cfg"
        res.cfgs = [build_cfg(fn) for fn in res.functions]
        phases["cfg"] = cfg_artifact(res.cfgs)

        # safety analyses run on the unoptimized CFGs, before the optimizer may remove code
        self.current = "taint"
        res.taint = analyze_taint(res.cfgs)
        phases["taint"] = res.taint.artifact()

        self.current = "approval"
        res.approval = analyze_approval(res.cfgs)
        phases["approval"] = res.approval.artifact()

        self.current = "optimized_ir"
        res.optimized = [optimize(c) for c in res.cfgs]
        opt = optimized_artifact(res.optimized)
        phases["optimized_ir"] = opt
        calls_after = opt["data"]["after"]["calls"]
        res.stats = {
            "before": opt["data"]["before"],
            "after": opt["data"]["after"],
            "rounds_before": calls_after,
            "rounds_after": calls_after,
        }
        final_cfgs = [c for c, _ in res.optimized]

        if self.parallel:
            self.current = "schedule"
            res.scheduled = [schedule(c) for c in final_cfgs]
            sched = schedule_artifact(res.scheduled)
            phases["schedule"] = sched
            res.stats["rounds_before"] = sched["data"]["rounds_before"]
            res.stats["rounds_after"] = sched["data"]["rounds_after"]
            final_cfgs = [c for c, _ in res.scheduled]

        self.current = "bytecode"
        res.program = generate(res.agent, final_cfgs)
        phases["bytecode"] = bytecode_artifact(res.program)


# Tried in order: Windows rejects >= 256 MB, and some platforms cap lower still.
_DEEP_STACK_CANDIDATES = (128 * 1024 * 1024, 64 * 1024 * 1024, 16 * 1024 * 1024)
_RECURSION_LIMIT = 100_000
_stack_size_lock = threading.Lock()


def _set_deep_stack_size() -> int:
    """Set the largest accepted thread stack size; return the previous setting."""
    for size in _DEEP_STACK_CANDIDATES:
        try:
            return threading.stack_size(size)
        except (ValueError, RuntimeError):
            continue
    return threading.stack_size()  # no candidate accepted: keep the platform default


def _with_deep_stack(fn: Callable[[], Any]) -> Any:
    """Run fn() in a fresh thread with a large C stack and a raised recursion limit."""
    if sys.getrecursionlimit() < _RECURSION_LIMIT:
        sys.setrecursionlimit(_RECURSION_LIMIT)  # process-wide; only ever raised
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    with _stack_size_lock:  # stack_size() is global: set it only around this thread's start
        old = _set_deep_stack_size()
        try:
            worker = threading.Thread(target=target, name="agentscript-compile")
            worker.start()
        finally:
            threading.stack_size(old)
    worker.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


def compile_source(source: str, parallel: bool = True) -> CompileResult:
    """Compile `source` through every phase; never raises (see the module docstring)."""
    return _with_deep_stack(_Driver(source, parallel).compile)


# ---------------------------------------------------------------------------- run


def make_registry(live: bool, confirm: bool) -> ToolRegistry:
    return LiveRegistry(confirm_answer=confirm) if live else MockRegistry(confirm_answer=confirm)


def execute(
    compiled: CompileResult, task: str, args: Any, live: bool = False, confirm: bool = True
) -> RunResult:
    """Run one task of a successfully compiled program; raises AgentRuntimeError (E601-E604).

    The raised error always carries `calls` (CallRecords made so far) and `calls_used`.
    """
    if not compiled.ok or compiled.program is None:
        raise ValueError("execute() needs a program that compiled without errors")
    try:
        return run(compiled.program, task, args, make_registry(live, confirm))
    except AgentRuntimeError as err:
        if not hasattr(err, "calls"):
            err.calls = []
        if not hasattr(err, "calls_used"):
            err.calls_used = len(err.calls)
        raise


def rounds_of(calls: list) -> int:
    """Rounds used by the calls made so far (each call record knows its round)."""
    return max((c.round for c in calls), default=0)


def run_source(
    source: str,
    task: str,
    args: Any,
    live: bool = False,
    confirm: bool = True,
    parallel: bool = True,
) -> dict:
    """Compile, then run `task` with JSON `args`; returns the `/run` response dict; never raises.

    `diagnostics` repeats the compile diagnostics (warnings) and adds the runtime one, if any.
    """
    compiled = compile_source(source, parallel=parallel)
    diagnostics = [d.to_dict() for d in compiled.diagnostics]
    agent = compiled.agent
    response: dict = {
        "ok": False,
        "diagnostics": diagnostics,
        "value": None,
        "calls": [],
        "calls_used": 0,
        "budget": agent.budget.calls if agent is not None else 0,
        "rounds": 0,
    }
    if not compiled.ok:
        return response
    try:
        result = execute(compiled, task, args, live=live, confirm=confirm)
    except AgentRuntimeError as err:
        diagnostics.append(err.diagnostic.to_dict())
        response.update(
            calls=[c.to_dict() for c in err.calls],
            calls_used=err.calls_used,
            rounds=rounds_of(err.calls),
        )
        return response
    except Exception as exc:  # a VM or registry bug must not become an HTTP 500
        diag = make_diagnostic("E000", f"internal VM error: {type(exc).__name__}: {exc}", 0, 0)
        diagnostics.append(diag.to_dict())
        return response
    response.update(ok=True, **result.to_dict())
    return response
