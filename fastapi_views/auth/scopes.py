from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Annotated, ClassVar

from pydantic import StringConstraints

Read = "read"
Edit = "edit"
All = "*"

Scope = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=255,
        to_lower=True,
        strip_whitespace=True,
    ),
]


class ScopeValidator(ABC):
    """Strategy that decides whether a required scope is covered by granted ones."""

    @abstractmethod
    def has_scope(self, scope: Scope, granted_scopes: Sequence[Scope]) -> bool:
        """Return ``True`` when ``scope`` is satisfied by ``granted_scopes``."""
        raise NotImplementedError


class SimpleScopeValidator(ScopeValidator):
    """Grant access only when the required scope is present verbatim."""

    def has_scope(self, scope: Scope, granted_scopes: Sequence[Scope]) -> bool:
        return scope in granted_scopes


class HierarchicalScopeValidator(ScopeValidator):
    """Parse scopes into ``resource:action`` segments and validate hierarchically.

    A granted scope covers a required one when its resource matches (or is the
    ``*`` wildcard) and its action matches, is the ``*`` wildcard, or implies the
    required action through :attr:`scope_hierarchy`.
    """

    scope_hierarchy: ClassVar[dict[str, set[str]]] = {
        Read: set(),
        Edit: {Read},
        All: {Read, Edit},
    }

    def _resolve_action(self, action: str) -> set[str]:
        return self.scope_hierarchy.get(action, set()) | {action}

    def has_scope(self, scope: Scope, granted_scopes: Sequence[Scope]) -> bool:
        required_resource, _, required_action = scope.partition(":")
        for s in granted_scopes:
            granted_resource, _, granted_action = s.partition(":")
            if granted_resource not in (required_resource, All):
                continue
            if granted_action == All or required_action in self._resolve_action(
                granted_action
            ):
                return True
        return False
