"""Diagnostics shared by every phase, the CLI, the API and the editor squiggles."""

from __future__ import annotations

from dataclasses import dataclass


# code -> (phase, short title). The phase is what Diagnostic.phase reports.
ERROR_CODES: dict[str, tuple[str, str]] = {
    "E000": ("internal", "internal compiler error"),
    "E101": ("lexer", "unterminated string"),
    "E102": ("lexer", "illegal character"),
    "E201": ("parser", "syntax error"),
    "E301": ("semantic", "undeclared name"),
    "E302": ("semantic", "duplicate declaration"),
    "E303": ("semantic", "type mismatch"),
    "E304": ("semantic", "missing return"),
    "E305": ("semantic", "tool not permitted"),
    "E306": ("semantic", "budget exceeded"),
    "W306": ("semantic", "budget checked at runtime"),
    "E401": ("taint", "untrusted data reaches privileged tool"),
    "E501": ("approval", "irreversible call reachable without confirm"),
    "E502": ("approval", "confirm does not guard every path"),
    "E601": ("runtime", "budget exceeded at runtime"),
    "E602": ("runtime", "tool not permitted at runtime"),
    "E603": ("runtime", "index out of range"),
    "E604": ("runtime", "invalid run request"),
}


@dataclass(frozen=True)
class PathStep:
    """One step of a source-to-sink (taint) or entry-to-call (approval) path."""

    line: int
    col: int
    note: str

    def to_dict(self) -> dict:
        return {"line": self.line, "col": self.col, "note": self.note}


@dataclass
class Diagnostic:
    phase: str  # "lexer" | "parser" | "semantic" | "taint" | "approval" | "runtime"
    code: str  # key of ERROR_CODES
    message: str
    line: int
    col: int
    severity: str = "error"  # "error" | "warning"
    path: list[PathStep] | None = None

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "path": None if self.path is None else [s.to_dict() for s in self.path],
        }

    def format(self) -> str:
        """Text form: `E401 [taint] 9:14: message`, then one indented line per path step."""
        lines = [f"{self.code} [{self.phase}] {self.line}:{self.col}: {self.message}"]
        for step in self.path or []:
            lines.append(f"    {step.line}:{step.col}  {step.note}")
        return "\n".join(lines)


class CompileError(Exception):
    """Raised by a compile-time phase; carries exactly one diagnostic."""

    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.format())
        self.diagnostic = diagnostic


class AgentRuntimeError(Exception):
    """Raised by the VM (E601-E604); carries exactly one diagnostic."""

    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.format())
        self.diagnostic = diagnostic


def make_diagnostic(
    code: str, message: str, line: int, col: int, path: list[PathStep] | None = None
) -> Diagnostic:
    phase, _ = ERROR_CODES[code]
    severity = "warning" if code.startswith("W") else "error"
    return Diagnostic(phase, code, message, line, col, severity, path)


def make_error(
    code: str, message: str, line: int, col: int, path: list[PathStep] | None = None
) -> CompileError | AgentRuntimeError:
    """Build the exception for `code`: AgentRuntimeError for E6xx, CompileError otherwise.

    Usage: `raise make_error("E303", "expected string, found int", tok.line, tok.col)`.
    """
    diag = make_diagnostic(code, message, line, col, path)
    if diag.phase == "runtime":
        return AgentRuntimeError(diag)
    return CompileError(diag)
