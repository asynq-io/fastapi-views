from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(kw_only=True)
class FieldOperation:
    field: str

    def set_prefix(self, prefix: str) -> None:
        self.field = f"{prefix}__{self.field}"


@dataclass(kw_only=True)
class FilterOperation(FieldOperation):
    operator: str
    values: Any


@dataclass(kw_only=True)
class SortOperation(FieldOperation):
    desc: bool = False


@dataclass(kw_only=True)
class LogicalOperation:
    operator: Literal["and", "or"]
    values: list[FilterOperation] | list[LogicalOperation]

    def set_prefix(self, prefix: str) -> None:
        for value in self.values:
            value.set_prefix(prefix)


Operation = FilterOperation | SortOperation | LogicalOperation
