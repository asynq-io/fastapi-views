from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, NoReturn, TypeVar

from pydantic import BaseModel

from fastapi_views.permissions.abc import BasePermission, _Composite
from fastapi_views.views.generics import (
    AsyncGenericCreateAPIView,
    AsyncGenericDestroyAPIView,
    AsyncGenericListAPIView,
    AsyncGenericPartialUpdateAPIView,
    AsyncGenericRetrieveAPIView,
    AsyncGenericUpdateAPIView,
    GenericCreateAPIView,
    GenericDestroyAPIView,
    GenericListAPIView,
    GenericPartialUpdateAPIView,
    GenericRetrieveAPIView,
    GenericUpdateAPIView,
    WithAsyncRepositoryMixin,
    WithRepositoryMixin,
)

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "AsyncObjectPermissionsMixin",
    "AsyncProtectedGenericDestroyAPIView",
    "AsyncProtectedGenericPartialUpdateAPIView",
    "AsyncProtectedGenericUpdateAPIView",
    "AsyncProtectedGenericViewSet",
    "ObjectPermissionsMixin",
    "ProtectedGenericDestroyAPIView",
    "ProtectedGenericPartialUpdateAPIView",
    "ProtectedGenericUpdateAPIView",
    "ProtectedGenericViewSet",
]

M = TypeVar("M")
PK = TypeVar("PK", bound=BaseModel)


def _checks_objects(permission: BasePermission) -> bool:
    """Whether ``permission`` implements a real object-level check.

    Permissions leaving :meth:`BasePermission.has_object_permission` untouched
    always pass, so fetching the row for them would be a wasted roundtrip. A
    composite counts as soon as one of its children implements one.
    """
    if isinstance(permission, _Composite):
        return any(_checks_objects(child) for child in permission.children)
    return (
        type(permission).has_object_permission
        is not BasePermission.has_object_permission
    )


class ObjectPermissionsMixin(WithRepositoryMixin[M]):
    """Object-level permission checks for mutating actions.

    ``update`` / ``partial_update`` / ``destroy`` write through the repository
    without ever holding the row, so there is nothing to hand
    :meth:`check_object_permissions`. This mixin fetches the target first and
    authorizes it before the write happens.
    """

    raise_on_none: bool
    get_permissions: Callable[[], list[BasePermission]]
    check_object_permissions: Callable[[Any], None]
    raise_not_found_error: Callable[[], NoReturn]

    def authorize_object(self, *args: Any, **kwargs: Any) -> None:
        """Fetch the addressed object and run its object-level permissions."""
        if not any(_checks_objects(perm) for perm in self.get_permissions()):
            return
        obj = self.repository.get(*args, **kwargs)
        if obj is None:
            if self.raise_on_none:
                self.raise_not_found_error()
            return
        self.check_object_permissions(obj)


class AsyncObjectPermissionsMixin(WithAsyncRepositoryMixin[M]):
    """Async counterpart of :class:`ObjectPermissionsMixin`."""

    raise_on_none: bool
    get_permissions: Callable[[], list[BasePermission]]
    check_object_permissions: Callable[[Any], None]
    raise_not_found_error: Callable[[], NoReturn]

    async def authorize_object(self, *args: Any, **kwargs: Any) -> None:
        """Fetch the addressed object and run its object-level permissions."""
        if not any(_checks_objects(perm) for perm in self.get_permissions()):
            return
        obj = await self.repository.get(*args, **kwargs)
        if obj is None:
            if self.raise_on_none:
                self.raise_not_found_error()
            return
        self.check_object_permissions(obj)


class ProtectedGenericUpdateAPIView(
    ObjectPermissionsMixin[M],
    GenericUpdateAPIView[PK, M],
    Generic[PK, M],
):
    """GenericUpdateAPIView enforcing object-level permissions."""


class AsyncProtectedGenericUpdateAPIView(
    AsyncObjectPermissionsMixin[M],
    AsyncGenericUpdateAPIView[PK, M],
    Generic[PK, M],
):
    """AsyncGenericUpdateAPIView enforcing object-level permissions."""


class ProtectedGenericPartialUpdateAPIView(
    ObjectPermissionsMixin[M],
    GenericPartialUpdateAPIView[PK, M],
    Generic[PK, M],
):
    """GenericPartialUpdateAPIView enforcing object-level permissions."""


class AsyncProtectedGenericPartialUpdateAPIView(
    AsyncObjectPermissionsMixin[M],
    AsyncGenericPartialUpdateAPIView[PK, M],
    Generic[PK, M],
):
    """AsyncGenericPartialUpdateAPIView enforcing object-level permissions."""


class ProtectedGenericDestroyAPIView(
    ObjectPermissionsMixin[M],
    GenericDestroyAPIView[PK],
    Generic[PK, M],
):
    """GenericDestroyAPIView enforcing object-level permissions."""


class AsyncProtectedGenericDestroyAPIView(
    AsyncObjectPermissionsMixin[M],
    AsyncGenericDestroyAPIView[PK],
    Generic[PK, M],
):
    """AsyncGenericDestroyAPIView enforcing object-level permissions."""


class ProtectedGenericViewSet(
    GenericListAPIView,
    GenericRetrieveAPIView,
    GenericCreateAPIView,
    ProtectedGenericUpdateAPIView,
    ProtectedGenericPartialUpdateAPIView,
    ProtectedGenericDestroyAPIView,
):
    """GenericViewSet enforcing object-level permissions on mutating actions."""


class AsyncProtectedGenericViewSet(
    AsyncGenericListAPIView,
    AsyncGenericRetrieveAPIView,
    AsyncGenericCreateAPIView,
    AsyncProtectedGenericUpdateAPIView,
    AsyncProtectedGenericPartialUpdateAPIView,
    AsyncProtectedGenericDestroyAPIView,
):
    """AsyncGenericViewSet enforcing object-level permissions on mutating actions."""
