from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi_views.permissions.abc import BasePermission

if TYPE_CHECKING:
    from fastapi_views.auth.scopes import ScopeValidator
    from fastapi_views.views.api import APIView

__all__ = [
    "AllowAny",
    "HasPermissions",
    "HasScopes",
    "IsAdmin",
    "IsAdminOrOwner",
    "IsAuthenticated",
    "IsAuthenticatedOrReadOnly",
    "IsOwner",
]

_SAFE_METHODS = ("GET", "HEAD")


def _is_authenticated(principal: Any) -> bool:
    return principal is not None


class AllowAny(BasePermission):
    """Always pass — the default."""

    def has_permission(self, principal: Any, view: APIView | None = None) -> bool:
        return True


class IsAuthenticated(BasePermission):
    """The caller resolved to a principal (non-``None``)."""

    def has_permission(self, principal: Any, view: APIView | None = None) -> bool:
        return _is_authenticated(principal)


class HasPermissions(BasePermission):
    """Every required permission must be satisfied by the principal's granted ones.

    Matching is delegated to a :class:`~fastapi_views.auth.scopes.ScopeValidator`,
    defaulting to ``SimpleScopeValidator`` (verbatim match) — pass the validator
    used at the auth layer (``HierarchicalScopeValidator``) when tokens carry
    ``*`` wildcards or implied actions, so both layers agree.
    """

    def __init__(
        self, *permissions: str, scope_validator: ScopeValidator | None = None
    ) -> None:
        from fastapi_views.auth.scopes import SimpleScopeValidator

        self.permissions: tuple[str, ...] = permissions
        self.scope_validator = scope_validator or SimpleScopeValidator()

    def has_permission(self, principal: Any, view: APIView | None = None) -> bool:
        if not _is_authenticated(principal):
            return False
        granted = getattr(principal, "permissions", ())
        return all(
            self.scope_validator.has_scope(perm, granted) for perm in self.permissions
        )

    @property
    def required_scopes(self) -> list[str]:
        return list(self.permissions)


#: Alias for token-scope naming conventions (``HasScopes("read:items")``).
HasScopes = HasPermissions


class IsOwner(BasePermission):
    """Object-level: a principal attr equals an object attr.

    ``IsOwner("user_id", "owner_id")`` checks
    ``getattr(principal, "user_id") == getattr(obj, "owner_id")`` — read typed
    fields off your own principal model.
    """

    def __init__(
        self, principal_attr: str = "user_id", obj_attr: str = "owner_id"
    ) -> None:
        self.principal_attr = principal_attr
        self.obj_attr = obj_attr

    def has_object_permission(
        self,
        principal: Any,
        view: APIView | None = None,
        obj: Any = None,
    ) -> bool:
        if not _is_authenticated(principal) or obj is None:
            return False
        return getattr(obj, self.obj_attr, None) == getattr(
            principal, self.principal_attr, None
        )


class IsAdmin(BasePermission):
    """The principal holds the admin permission (default ``"admin"``)."""

    def __init__(self, admin_permission: str = "admin") -> None:
        self.admin_permission = admin_permission

    def _is_admin(self, principal: Any) -> bool:
        if not _is_authenticated(principal):
            return False
        return self.admin_permission in getattr(principal, "permissions", ())

    def has_permission(self, principal: Any, view: APIView | None = None) -> bool:
        return self._is_admin(principal)

    def has_object_permission(
        self,
        principal: Any,
        view: APIView | None = None,
        obj: Any = None,
    ) -> bool:
        return self._is_admin(principal)

    @property
    def required_scopes(self) -> list[str]:
        return [self.admin_permission]


class IsAdminOrOwner(BasePermission):
    """Admins act on anything; otherwise the caller must own the object."""

    def __init__(
        self,
        admin_permission: str = "admin",
        principal_attr: str = "user_id",
        obj_attr: str = "owner_id",
    ) -> None:
        self.admin = IsAdmin(admin_permission)
        self.owner = IsOwner(principal_attr, obj_attr)

    def has_permission(self, principal: Any, view: APIView | None = None) -> bool:
        return self.admin.has_permission(principal, view)

    def has_object_permission(
        self,
        principal: Any,
        view: APIView | None = None,
        obj: Any = None,
    ) -> bool:
        return self.admin.has_object_permission(
            principal, view, obj
        ) or self.owner.has_object_permission(principal, view, obj)

    @property
    def required_scopes(self) -> list[str]:
        return self.admin.required_scopes


class IsAuthenticatedOrReadOnly(BasePermission):
    """Authenticated for writes; safe methods (``GET``/``HEAD``) allowed for anyone."""

    def has_permission(self, principal: Any, view: APIView | None = None) -> bool:
        method = getattr(getattr(view, "request", None), "method", None)
        if method in _SAFE_METHODS:
            return True
        return _is_authenticated(principal)
