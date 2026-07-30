from typing import Annotated, Any, Literal

import jsonpatch
from pydantic import Field, RootModel
from typing_extensions import TypedDict


class AddOperation(TypedDict):
    op: Literal["add"]
    path: str
    value: Any


class RemoveOperation(TypedDict):
    op: Literal["remove"]
    path: str


class ReplaceOperation(TypedDict):
    op: Literal["replace"]
    path: str
    value: Any


MoveOperation = TypedDict(
    "MoveOperation", {"op": Literal["move"], "path": str, "from": str}
)

CopyOperation = TypedDict(
    "CopyOperation", {"op": Literal["copy"], "path": str, "from": str}
)


class TestOperation(TypedDict):
    op: Literal["test"]
    path: str
    value: Any


PatchOperation = Annotated[
    AddOperation
    | RemoveOperation
    | ReplaceOperation
    | MoveOperation
    | CopyOperation
    | TestOperation,
    Field(discriminator="op"),
]

JsonPatch = list[PatchOperation]


def apply(doc: Any, operations: JsonPatch, *, in_place: bool = False) -> Any:
    """Apply RFC 6902 ``operations`` to ``doc`` and return the patched document.

    With ``in_place=False`` (the default) ``doc`` is left untouched and a
    patched copy is returned. Root-path operations always produce a new
    document, so use the return value rather than relying on mutation.
    """
    patch = jsonpatch.JsonPatch(operations)
    return patch.apply(doc, in_place=in_place)


class JsonPatchModel(RootModel[JsonPatch]):
    """RFC 6902 JSON Patch document."""

    __content_type__ = "application/json-patch+json"

    def apply(self, doc: Any, *, in_place: bool = False) -> Any:
        """Apply the patch operations to ``doc`` and return the patched document."""
        return apply(doc, self.root, in_place=in_place)
