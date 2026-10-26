"""Static types: string, int, bool and list<T>."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Type:
    name: str  # "string" | "int" | "bool" | "list"
    elem: Type | None = None  # element type when name == "list"

    def __str__(self) -> str:
        if self.name == "list":
            return f"list<{self.elem}>"
        return self.name

    @property
    def is_list(self) -> bool:
        return self.name == "list"


STRING = Type("string")
INT = Type("int")
BOOL = Type("bool")


def list_of(elem: Type) -> Type:
    return Type("list", elem)
