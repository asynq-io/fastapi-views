from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Annotated, Any, ClassVar

from pydantic import BeforeValidator, StringConstraints

Scope = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=255,
        to_lower=True,
        strip_whitespace=True,
        pattern=r"^[a-z]+:(\*|[a-z]+)$",
    ),
]

Read = "read"
Edit = "edit"
All = "*"


class ScopeValidator(ABC):
    """Abstract base class for scope validation strategies.

    Implement :meth:`has_scope` to control how token scopes are compared against the
    scope required by an endpoint.
    """

    @abstractmethod
    def has_scope(self, scope: Scope, required_scopes: Sequence[str]) -> bool:
        """Return ``True`` if *required_scopes* satisfies *scope*.

        :param scope: The single scope string required by the endpoint (e.g. ``"items:read"``).
        :type scope: Scope
        :param required_scopes: The scopes present in the token.
        :type required_scopes: Sequence[str]
        :rtype: bool
        """
        raise NotImplementedError


class SimpleScopeValidator(ScopeValidator):
    """Scope validator that requires an exact match.

    The token must contain the scope string verbatim.  This is the default validator
    used by :class:`~fastapi_views.security.auth.Auth`.

    :Example:

    .. code-block:: python

        validator = SimpleScopeValidator()
        validator.has_scope("items:read", ["items:read", "orders:read"])  # True
        validator.has_scope("items:edit", ["items:read"])                 # False
    """

    def has_scope(self, scope: Scope, required_scopes: Sequence[str]) -> bool:
        """Return ``True`` when *scope* is present verbatim in *required_scopes*.

        :param scope: Required scope string.
        :type scope: Scope
        :param required_scopes: Scopes present in the token.
        :type required_scopes: Sequence[str]
        :rtype: bool
        """
        return scope in required_scopes


class AdvancedScopeValidator(ScopeValidator):
    """Scope validator with hierarchical action inheritance.

    Scopes follow the ``resource:action`` convention.  The default hierarchy is:

    - ``*`` (wildcard) implies ``edit`` and ``read``
    - ``edit`` implies ``read``
    - ``read`` implies nothing

    A token with ``items:edit`` therefore satisfies a requirement of ``items:read``,
    and a token with ``items:*`` satisfies both ``items:read`` and ``items:edit``.

    :param scope_hierarhy: Custom action hierarchy mapping an action to the set of
        actions it implies.  Defaults to :attr:`DEFAULT_SCOPE_HIERARCHY`.
    :type scope_hierarhy: dict[str, set[str]] | None

    :Example:

    .. code-block:: python

        from fastapi_views.security.scopes import AdvancedScopeValidator

        validator = AdvancedScopeValidator()
        validator.has_scope("items:read", ["items:edit"])  # True  (edit ⊇ read)
        validator.has_scope("items:edit", ["items:read"])  # False (read ⊄ edit)
        validator.has_scope("items:read", ["items:*"])     # True  (* ⊇ read)
    """

    DEFAULT_SCOPE_HIERARCHY: ClassVar[dict[str, set[str]]] = {
        Read: set(),
        Edit: {Read},
        All: {Read, Edit},
    }

    def __init__(self, scope_hierarhy: dict[str, set[str]] | None = None) -> None:
        self.scope_hierarhy = scope_hierarhy or self.DEFAULT_SCOPE_HIERARCHY

    def _resolve_action(self, action: str) -> set[str]:
        return self.scope_hierarhy.get(action, set()) | {action}

    def has_scope(self, scope: Scope, required_scopes: Sequence[Scope]) -> bool:
        """Return ``True`` if any scope in *required_scopes* satisfies *scope*.

        Matching respects both resource wildcards (``*:read``) and action inheritance.

        :param scope: Required scope string.
        :type scope: Scope
        :param required_scopes: Scopes present in the token.
        :type required_scopes: Sequence[Scope]
        :rtype: bool
        """
        required_resource, _, required_action = scope.partition(":")
        for s in required_scopes:
            granted_resource, _, granted_action = s.partition(":")
            if granted_resource not in (required_resource, All):
                continue
            if granted_action == All or required_action in self._resolve_action(
                granted_action
            ):
                return True
        return False


def _split_scopes(value: Any) -> Any:
    if isinstance(value, str):
        return value.split(" ")
    return value


ValidatedScopes = Annotated[list[Scope], BeforeValidator(_split_scopes)]
