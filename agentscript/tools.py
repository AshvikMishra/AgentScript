"""The fixed table of built-in tools and their safety annotations (T1, A1).

Annotations are not syntax: programs cannot declare tools or change these flags.
"""

from __future__ import annotations

from dataclasses import dataclass

from .typesys import BOOL, STRING, Type, list_of


@dataclass(frozen=True)
class ToolSpec:
    name: str
    params: tuple[Type, ...]
    returns: Type
    untrusted_result: bool = False  # taint source: the result is untrusted
    propagates_taint: bool = False  # result taint = join of the argument taints (llm)
    sanitizer: bool = False  # result is always trusted (sanitize)
    privileged: bool = False  # taint sink: every argument must be trusted
    irreversible: bool = False  # must be guarded by a confirm result
    approval: bool = False  # this is the human approval step (confirm)
    mergeable: bool = False  # read-only: safe for duplicate-call elimination

    @property
    def barrier(self) -> bool:
        """Calls the scheduler must never reorder (L3)."""
        return self.privileged or self.irreversible or self.approval

    def signature(self) -> str:
        args = ", ".join(str(p) for p in self.params)
        return f"({args}) -> {self.returns}"


TOOLS: dict[str, ToolSpec] = {
    t.name: t
    for t in [
        ToolSpec("web_search", (STRING,), list_of(STRING), untrusted_result=True, mergeable=True),
        ToolSpec("read_file", (STRING,), STRING, untrusted_result=True, mergeable=True),
        ToolSpec("llm", (STRING,), STRING, propagates_taint=True, mergeable=True),
        ToolSpec("send_email", (STRING, STRING), BOOL, privileged=True),
        ToolSpec("delete_file", (STRING,), BOOL, privileged=True, irreversible=True),
        ToolSpec("sanitize", (STRING,), STRING, sanitizer=True, mergeable=True),
        ToolSpec("confirm", (STRING,), BOOL, approval=True),
    ]
}
