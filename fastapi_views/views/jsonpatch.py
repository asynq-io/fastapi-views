from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jsonpatch
import jsonpointer
from pydantic import BaseModel, ValidationError

from fastapi_views.exceptions import BadRequest
from fastapi_views.models.jsonpatch import JsonPatchModel

from .api import AsyncPartialUpdateAPIView, PartialUpdateAPIView
from .generics import (
    PK,
    DetailGenericView,
    M,
    WithAsyncRepositoryMixin,
    WithRepositoryMixin,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_MISSING = object()


class JsonPatchViewMixin:
    partial_update_schema: type[BaseModel]

    def apply_patch(self, obj: Any, operations: JsonPatchModel) -> dict[str, Any]:
        """Patch ``obj`` and return only the changed, schema-validated fields.

        The object is projected onto ``partial_update_schema`` and dumped in
        JSON mode, as patch operations compare against raw JSON values. The
        patched document is validated again so the update cannot produce an
        invalid resource; a patch or validation failure maps to ``400``.
        """
        schema = self.partial_update_schema
        doc = schema.model_validate(obj, from_attributes=True).model_dump(mode="json")
        try:
            patched_doc = operations.apply(doc)
            patched = schema.model_validate(patched_doc)
        except (
            jsonpatch.JsonPatchException,
            jsonpointer.JsonPointerException,
            ValidationError,
        ):
            raise BadRequest("Invalid operations") from None
        changed = {
            field
            for field in doc.keys() | patched_doc.keys()
            if doc.get(field, _MISSING) != patched_doc.get(field, _MISSING)
        }
        return patched.model_dump(include=changed)


class BaseGenericJsonPatchAPIView(DetailGenericView[PK]):
    """Base view handling PATCH requests with RFC 6902 JSON Patch documents."""

    if TYPE_CHECKING:
        partial_update: Callable

    partial_update_schema: type[BaseModel]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not hasattr(cls, "partial_update_schema"):
            return

        cls._patch_pk_param(cls.partial_update)
        cls.partial_update.__annotations__["partial_update_schema"] = JsonPatchModel


class AsyncGenericJsonPatchAPIView(
    BaseGenericJsonPatchAPIView[PK],
    AsyncPartialUpdateAPIView,
    JsonPatchViewMixin,
    WithAsyncRepositoryMixin[M],
):
    """AsyncGenericJsonPatchAPIView"""

    async def partial_update(
        self, pk: PK, partial_update_schema: JsonPatchModel
    ) -> Any:
        args, kwargs = self.get_primary_key(pk, action="partial_update")
        model = await self.repository.get(*args, **kwargs)
        if model is None:
            self.raise_not_found_error()
        data = self.apply_patch(model, partial_update_schema)
        await self.before_partial_update(data)
        obj = await self.repository.update_one(data, *args, **kwargs)
        if obj is None:
            self.raise_not_found_error()
        await self.after_partial_update(obj)
        return obj

    async def before_partial_update(self, data: dict[str, Any]) -> None:
        pass

    async def after_partial_update(self, model: M) -> None:
        pass


class GenericJsonPatchAPIView(
    BaseGenericJsonPatchAPIView[PK],
    PartialUpdateAPIView,
    JsonPatchViewMixin,
    WithRepositoryMixin[M],
):
    """GenericJsonPatchAPIView"""

    def partial_update(self, pk: PK, partial_update_schema: JsonPatchModel) -> Any:
        args, kwargs = self.get_primary_key(pk, action="partial_update")
        model = self.repository.get(*args, **kwargs)
        if model is None:
            self.raise_not_found_error()
        data = self.apply_patch(model, partial_update_schema)
        self.before_partial_update(data)
        obj = self.repository.update_one(data, *args, **kwargs)
        if obj is None:
            self.raise_not_found_error()
        self.after_partial_update(obj)
        return obj

    def before_partial_update(self, data: dict[str, Any]) -> None:
        pass

    def after_partial_update(self, model: M) -> None:
        pass
