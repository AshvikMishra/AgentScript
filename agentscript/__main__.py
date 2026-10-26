"""Command line interface: `python -m agentscript compile|run|serve ...`.

    compile FILE [--phase NAME] [--json] [--no-parallel]
    run FILE --task T [--args JSON] [--live] [--deny-confirm]
    serve [--host 127.0.0.1] [--port 8000]

Exit status: 0 on success, 1 when compilation or the run fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .diagnostics import AgentRuntimeError
from .pipeline import PHASES, CompileResult, compile_source, execute
from .vm import format_call_log


def _read_source(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as err:
        print(f"error: cannot read {path}: {err.strerror or err}", file=sys.stderr)
        return None


def _print_diagnostics(result: CompileResult, stream) -> None:
    for diag in result.diagnostics:
        print(diag.format(), file=stream)


def cmd_compile(args: argparse.Namespace) -> int:
    source = _read_source(args.file)
    if source is None:
        return 1
    result = compile_source(source, parallel=not args.no_parallel)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if result.ok else 1

    if args.phase:
        # only the requested artifact on stdout, so it can be redirected to a file
        artifact = result.phases[args.phase]
        if artifact is None:
            print(f"phase '{args.phase}' did not run", file=sys.stderr)
        else:
            print(artifact["text"])
        _print_diagnostics(result, sys.stderr)
        return 0 if result.ok else 1

    for name in PHASES:
        artifact = result.phases[name]
        if artifact is not None:
            print(f"== {name} ==")
            print(artifact["text"])
            print()
    print("== diagnostics ==")
    if result.diagnostics:
        _print_diagnostics(result, sys.stdout)
    else:
        print("(none)")
    print("compiled OK" if result.ok else "compilation failed")
    return 0 if result.ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    source = _read_source(args.file)
    if source is None:
        return 1
    try:
        run_args = json.loads(args.args)
    except ValueError as err:  # JSONDecodeError is a ValueError
        print(f"error: --args is not valid JSON: {err}", file=sys.stderr)
        return 1

    result = compile_source(source)
    _print_diagnostics(result, sys.stderr)
    if not result.ok:
        print("compilation failed; nothing was run", file=sys.stderr)
        return 1
    try:
        run = execute(result, args.task, run_args, live=args.live, confirm=not args.deny_confirm)
    except AgentRuntimeError as err:
        budget = result.program.budget if result.program else 0
        print(f"calls: {err.calls_used} of budget {budget}")
        print(format_call_log(err.calls))
        print(err.diagnostic.format())
        return 1
    print(run.format())
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("agentscript.api:app", host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentscript", description="AgentScript compiler and VM")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("compile", help="compile a file and print its phase artifacts")
    p.add_argument("file")
    p.add_argument("--phase", choices=PHASES, help="print only this phase's artifact")
    p.add_argument("--json", action="store_true", help="print the full /compile JSON")
    p.add_argument("--no-parallel", action="store_true", help="skip the M7 scheduler")
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("run", help="compile a file and run one task")
    p.add_argument("file")
    p.add_argument("--task", required=True)
    p.add_argument("--args", default="{}", help="task arguments as a JSON object")
    p.add_argument("--live", action="store_true", help="real llm / web_search / read_file")
    p.add_argument("--deny-confirm", action="store_true", help="confirm(...) answers false")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("serve", help="serve the web editor and the API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy code page; program values may be any Unicode
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
