from __future__ import annotations

from inspect import signature
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Protocol,
    Union,
    get_args,
    get_origin,
    runtime_checkable,
)

from fastapi import Depends, Request, Security, params
from fastapi.security.base import SecurityBase
from pydantic import BaseModel, ValidationError
from starlette.status import HTTP_401_UNAUTHORIZED

from fastapi_views.exceptions import APIError, Forbidden, Unauthorized

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "AUTH_CHALLENGE_SCOPE_KEY",
    "AUTH_ERROR_SCOPE_KEY",
    "AndPermission",
    "Authenticated",
    "BasePermission",
    "CurrentUser",
    "NotPermission",
    "OrPermission",
    "Principal",
    "get_app_auth",
    "permission_denied",
    "set_app_auth",
    "unauthorized",
]

#: Request-scope key holding the ``APIError`` the non-raising auth dependency
#: swallowed, so the ``401`` raised later can state the real reason.
AUTH_ERROR_SCOPE_KEY = "auth_error"
#: Request-scope key holding the auth's ``WWW-Authenticate`` challenge headers.
AUTH_CHALLENGE_SCOPE_KEY = "auth_challenge"


#: Auth registered process-wide by :func:`set_app_auth`; wired eagerly.
_APP_AUTH: Any = None
#: Auth of the most recent :func:`bind_app_auth`; documents deferred routes.
_BOUND_AUTH: Any = None

_NO_APP_AUTH = (
    "No app auth configured; call configure_app(app, auth=auth) or "
    "set_app_auth(auth) to protect views that use permission_classes."
)


def set_app_auth(auth: Any) -> None:
    """Register the app-wide auth process-wide (``None`` clears it).

    Views registered while this is set wire it immediately. Prefer
    ``configure_app(app, auth=auth)``, which binds the auth to a single app and
    works whatever the order of registration and configuration.
    """
    global _APP_AUTH, _BOUND_AUTH  # noqa: PLW0603
    _APP_AUTH = auth
    if auth is None:
        _BOUND_AUTH = None


def get_app_auth() -> Any:
    """The registered app auth (process-wide, else last bound); raises if none."""
    auth = _APP_AUTH if _APP_AUTH is not None else _BOUND_AUTH
    if auth is None:
        raise RuntimeError(_NO_APP_AUTH)
    return auth


def get_app_auth_or_none() -> Any:
    """The process-wide auth, or ``None`` when a view has to defer to its app."""
    return _APP_AUTH


def bind_app_auth(app: Any, auth: Any) -> None:
    """Bind ``auth`` to ``app`` (called by ``configure_app``).

    Deferred security dependencies resolve through ``app.dependency_overrides``,
    so routers may be registered before the auth is known and two apps in one
    process never share a trust domain.
    """
    global _BOUND_AUTH  # noqa: PLW0603
    _BOUND_AUTH = auth
    for deferred in _DEFERRED_AUTH.values():
        app.dependency_overrides[deferred] = getattr(auth, deferred.attr)


def _find_security_scheme(dependency: Any) -> SecurityBase | None:
    """The ``SecurityBase`` an auth dependency extracts its credential with."""
    if isinstance(dependency, SecurityBase):
        return dependency
    try:
        parameters = signature(dependency).parameters.values()
    except (TypeError, ValueError):
        return None
    for parameter in parameters:
        default = parameter.default
        if isinstance(default, params.Depends) and default.dependency is not None:
            scheme = _find_security_scheme(default.dependency)
            if scheme is not None:
                return scheme
    return None


class _DeferredAppAuth(SecurityBase):
    """Placeholder for an app auth dependency that is not known yet.

    Wired on routes registered before ``configure_app(app, auth=auth)`` runs,
    which binds it to the app's own auth via ``dependency_overrides``. It is a
    ``SecurityBase`` so the schema — generated lazily — still advertises the
    security scheme, and it fails closed when no auth was ever bound.
    """

    def __init__(self, attr: str) -> None:
        self.attr = attr

    @property
    def model(self) -> Any:  # type: ignore[override]
        return self._scheme().model

    @property
    def scheme_name(self) -> str:  # type: ignore[override]
        return self._scheme().scheme_name

    def _scheme(self) -> SecurityBase:
        dependency = getattr(get_app_auth(), self.attr)
        scheme = _find_security_scheme(dependency)
        if scheme is None:
            msg = (
                f"{dependency!r} extracts its credential without a FastAPI "
                "security scheme, so it cannot be documented; configure the "
                "auth before registering the routers that use it."
            )
            raise RuntimeError(msg)
        return scheme

    async def __call__(self, request: Request) -> Any:
        raise RuntimeError(_NO_APP_AUTH)


#: One placeholder per ``AuthBase`` dependency, keyed by its attribute name.
_DEFERRED_AUTH = {
    attr: _DeferredAppAuth(attr) for attr in ("dependency", "resolve_dependency")
}


def app_auth_security(
    auth: Any,
    scopes: Sequence[str] = (),
    *,
    raising: bool = False,
) -> params.Security:
    """``Security`` requiring ``scopes``, deferred when ``auth`` is ``None``.

    ``raising`` picks the auth's own dependency — ``401`` on a missing or
    invalid credential, plus scope validation — over the non-raising one that
    lets the permission classes decide between ``401`` and ``403``.
    """
    attr = "dependency" if raising else "resolve_dependency"
    dependency = _DEFERRED_AUTH[attr] if auth is None else getattr(auth, attr)
    return Security(dependency, scopes=list(scopes))


@runtime_checkable
class Principal(Protocol):
    """Structural contract for the resolved principal (your own model).

    The auth dependency returns your model (via ``custom_class``); anonymous is
    ``None``. ``is_authenticated`` is implied by non-``None`` (the model is only
    built when a credential verifies), so only ``permissions`` is required here.
    """

    permissions: Sequence[str]


def _is_permission(item: Any) -> bool:
    if isinstance(item, BasePermission):
        return True
    return isinstance(item, type) and issubclass(item, BasePermission)


class _PermissionMeta(type):
    """Let permission *classes* compose with ``&``, ``|``, ``~`` like instances.

    Non-permission operands fall back to ``type``'s own behaviour so PEP 604
    unions (``IsAuthenticated | None``) keep working.
    """

    def __and__(cls, other: Any) -> Any:
        if not _is_permission(other):
            return NotImplemented
        return cls() & other

    def __or__(cls, other: Any) -> Any:
        if not _is_permission(other):
            return super().__or__(other)
        return cls() | other

    def __invert__(cls) -> NotPermission:
        return ~cls()


class BasePermission(metaclass=_PermissionMeta):
    """DRF-style permission check.

    Sync, and takes the resolved ``principal`` (your model or ``None``) — not the
    request. Compose with ``&`` (AND), ``|`` (OR), ``~`` (NOT); classes and
    instances compose interchangeably.
    """

    @property
    def required_scopes(self) -> list[str]:
        """Scopes advertised on OpenAPI for this permission (default none)."""
        return []

    def has_permission(self, principal: Any, view: Any | None = None) -> bool:
        return True

    def has_object_permission(
        self,
        principal: Any,
        view: Any | None = None,
        obj: Any = None,
    ) -> bool:
        return True

    def __and__(self, other: Any) -> AndPermission:
        return AndPermission(self, BasePermission.resolve(other))

    def __or__(self, other: Any) -> OrPermission:
        return OrPermission(self, BasePermission.resolve(other))

    def __invert__(self) -> NotPermission:
        return NotPermission(self)

    @staticmethod
    def resolve(item: Any) -> BasePermission:
        """Normalize a class-or-instance to an instance."""
        if isinstance(item, BasePermission):
            return item
        if isinstance(item, type) and issubclass(item, BasePermission):
            return item()
        msg = f"Expected a BasePermission class or instance, got {item!r}"
        raise TypeError(msg)


class _Composite(BasePermission):
    def __init__(self, *children: Any) -> None:
        self.children: list[BasePermission] = [
            BasePermission.resolve(child) for child in children
        ]


class AndPermission(_Composite):
    """All children must pass."""

    def has_permission(self, principal: Any, view: Any | None = None) -> bool:
        return all(child.has_permission(principal, view) for child in self.children)

    def has_object_permission(
        self,
        principal: Any,
        view: Any | None = None,
        obj: Any = None,
    ) -> bool:
        return all(
            child.has_object_permission(principal, view, obj) for child in self.children
        )

    @property
    def required_scopes(self) -> list[str]:
        return [scope for child in self.children for scope in child.required_scopes]


class OrPermission(_Composite):
    """At least one child must pass (a failing child returns ``False``)."""

    def has_permission(self, principal: Any, view: Any | None = None) -> bool:
        return any(child.has_permission(principal, view) for child in self.children)

    def has_object_permission(
        self,
        principal: Any,
        view: Any | None = None,
        obj: Any = None,
    ) -> bool:
        return any(
            child.has_object_permission(principal, view, obj) for child in self.children
        )

    @property
    def required_scopes(self) -> list[str]:
        """Always empty: OR semantics don't map to FastAPI's all-required scopes."""
        return []


class NotPermission(BasePermission):
    """The child must *not* pass."""

    def __init__(self, child: Any) -> None:
        self.child: BasePermission = BasePermission.resolve(child)

    def has_permission(self, principal: Any, view: Any | None = None) -> bool:
        return not self.child.has_permission(principal, view)

    def has_object_permission(
        self,
        principal: Any,
        view: Any | None = None,
        obj: Any = None,
    ) -> bool:
        return not self.child.has_object_permission(principal, view, obj)


def unauthorized(request: Any = None) -> APIError:
    """``401`` carrying the auth's challenge and the real rejection reason.

    The non-raising dependency swallows whatever a presented credential raised
    so that authorization — not resolution — picks ``401`` vs ``403``, and
    stashes it on the request scope. Reinstating it here keeps an expired or
    tampered token distinguishable from an anonymous call, and the
    ``WWW-Authenticate`` challenge on every ``401`` (RFC 6750).
    """
    scope: Mapping[str, Any] = getattr(request, "scope", None) or {}
    error = scope.get(AUTH_ERROR_SCOPE_KEY)
    if isinstance(error, APIError) and error.status_code == HTTP_401_UNAUTHORIZED:
        return error
    return Unauthorized(
        "Authentication required",
        headers=scope.get(AUTH_CHALLENGE_SCOPE_KEY) or None,
    )


def permission_denied(principal: Any, request: Any = None) -> APIError:
    """401 when anonymous (``None``), 403 otherwise — matching DRF.

    ``request`` lets the ``401`` carry the challenge and the reason a rejected
    credential produced; a ``403`` never gains those artifacts.
    """
    if principal is None:
        return unauthorized(request)
    return Forbidden("Permission denied")


_COERCE_ERRORS = (
    AttributeError,
    KeyError,
    TypeError,
    ValueError,
    IndexError,
    ValidationError,
)
_UNION_SKIP = (APIError, *_COERCE_ERRORS)
_COERCE_FAILED = "Authenticated principal does not satisfy required type"


def _is_union(cls: Any) -> bool:
    return get_origin(cls) in (Union, UnionType)


def _is_instance_of(principal: Any, cls: Any) -> bool:
    """``isinstance`` that tolerates parameterized generics and non-classes."""
    origin = get_origin(cls) or cls
    if not isinstance(origin, type):
        return False
    try:
        return isinstance(principal, origin)
    except TypeError:
        return False


def _coerce_single(principal: Any, cls: Any) -> Any:
    """Coerce ``principal`` into a non-union ``cls`` (see ``_coerce_principal``)."""
    if _is_instance_of(principal, cls):
        return principal

    from_principal = getattr(cls, "from_principal", None)
    if callable(from_principal):
        try:
            return from_principal(principal)
        except _COERCE_ERRORS as exc:
            raise Forbidden(_COERCE_FAILED) from exc

    if isinstance(cls, type) and issubclass(cls, BaseModel):
        try:
            return cls.model_validate(principal)
        except ValidationError as exc:
            raise Forbidden(_COERCE_FAILED) from exc

    try:
        return cls(principal)
    except _COERCE_ERRORS as exc:
        raise Forbidden(_COERCE_FAILED) from exc


def _coerce_principal(principal: Any, cls: Any) -> Any:
    """Build a ``cls`` instance from the resolved ``principal``.

    Order: an existing ``cls`` instance is returned as-is; else
    ``cls.from_principal(principal)`` if present; else ``cls.model_validate``
    for pydantic models; else the constructor. A ``Union`` tries each member
    and returns the first that fits. Any failure surfaces as ``403`` — the
    caller authenticated but doesn't satisfy the required type (e.g. a token
    missing ``org_id`` where ``Authenticated[User]`` requires it).
    """
    if not _is_union(cls):
        return _coerce_single(principal, cls)

    for member in get_args(cls):
        try:
            return _coerce_principal(principal, member)
        except _UNION_SKIP:  # noqa: PERF203
            continue
    raise Forbidden("Authenticated principal does not match any allowed type")


def _authenticated_dependency(cls: Any) -> Callable[..., Any]:
    def _dependency(request: Request) -> Any:
        principal = request.scope.get("principal")
        if principal is None:
            raise unauthorized(request)
        return _coerce_principal(principal, cls)

    _dependency.__name__ = f"authenticated_{getattr(cls, '__name__', 'principal')}"
    return _dependency


class _AuthenticatedFactory:
    """Parameterized dependency: ``Authenticated[User]``.

    Expands to ``Annotated[User, Depends(resolver)]`` — the resolver reads the
    principal the auth dependency published on ``request.scope['principal']``,
    raises ``401`` when anonymous, and coerces it into ``User`` (``403`` on
    failure)::

        async def me(user: Authenticated[User]) -> dict[str, Any]:
            return {"id": str(user.user_id), "org": str(user.org_id)}
    """

    def __init__(self) -> None:
        self._cache: dict[Any, Any] = {}
        self._unhashable: list[tuple[Any, Any]] = []

    def __getitem__(self, cls: Any) -> Any:
        try:
            cached = self._cache.get(cls)
        except TypeError:
            return self._get_unhashable(cls)
        if cached is None:
            cached = self._cache[cls] = self._build(cls)
        return cached

    def _get_unhashable(self, cls: Any) -> Any:
        for key, alias in self._unhashable:
            if key == cls:
                return alias
        alias = self._build(cls)
        self._unhashable.append((cls, alias))
        return alias

    @staticmethod
    def _build(target: Any) -> Any:
        return Annotated[target, Depends(_authenticated_dependency(target))]


if TYPE_CHECKING:
    from typing import TypeAlias, TypeVar

    _PrincipalT = TypeVar("_PrincipalT")

    #: Usage: ``user: Authenticated[CustomUserClass]``.
    Authenticated: TypeAlias = Annotated[_PrincipalT, "authenticated-principal"]
else:
    #: Usage: ``user: Authenticated[CustomUserClass]``.
    Authenticated = _AuthenticatedFactory()


def _current_user(request: Request) -> Any:
    principal = request.scope.get("principal")
    if principal is None:
        raise unauthorized(request)
    return principal


#: Inject the authenticated principal as-is (raises ``401`` when anonymous).
CurrentUser = Annotated[Principal, Depends(_current_user)]
