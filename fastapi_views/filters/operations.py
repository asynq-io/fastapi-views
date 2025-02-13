from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Union

Operator = Literal[
    "eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "is_null", "like", "ilike"
]
LogicalOperator = Literal["and", "or"]


@dataclass
class FieldOperation:
    field: str

    def set_prefix(self, prefix: str) -> None:
        self.field = f"{prefix}__{self.field}"


@dataclass
class FilterOperation(FieldOperation):
    operator: Operator
    values: Any


@dataclass
class SortOperation(FieldOperation):
    desc: bool = False


@dataclass
class LogicalOperation:
    operator: LogicalOperator
    values: list[FilterOperation] | list[LogicalOperation]

    def set_prefix(self, prefix: str) -> None:
        for value in self.values:
            value.set_prefix(prefix)


Operation = Union[FilterOperation, SortOperation, LogicalOperation]
