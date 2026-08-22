from collections.abc import Mapping
from typing import ClassVar

from fastapi import params

from fastapi_views.exceptions import APIError, BadRequest, Forbidden, Unauthorized
from fastapi_views.permissions.abc import app_auth_security
from fastapi_views.types import Action
from fastapi_views.views import APIView

from .abc import ScopesAuth


class AutoScopesAuthView(APIView):
    """Derives per-action scopes from :attr:`action_scopes` and enforces them.

    Enforced with :attr:`auth` when the class declares one, else with the
    app-wide auth (``configure_app(auth=…)`` / ``set_app_auth``).
    """

    auth: ClassVar[ScopesAuth | None] = None
    resource: str | None = None
    default_errors: tuple[type[APIError], ...] = (BadRequest, Unauthorized, Forbidden)
    #: Scope prefix required per action; extend when registering custom actions.
    action_scopes: ClassVar[Mapping[str, str]] = {
        "list": "read",
        "retrieve": "read",
        "events": "read",
        "create": "edit",
        "update": "edit",
        "partial_update": "edit",
        "bulk_create": "edit",
        "bulk_update": "edit",
        "update_many": "edit",
        "destroy": "delete",
        "bulk_delete": "delete",
    }

    @classmethod
    def get_dependencies(cls, action: Action | None = None) -> list[params.Depends]:
        dependencies = super().get_dependencies(action)
        if action is None:
            return dependencies
        if action not in cls.action_scopes:
            msg = (
                f"No scope configured for action {action!r} on {cls.__name__}; "
                "add it to `action_scopes`"
            )
            raise LookupError(msg)
        resource_name = cls.resource or cls.get_name()
        scope = f"{cls.action_scopes[action]}:{resource_name}"
        security = app_auth_security(cls.get_auth(), [scope], raising=True)
        return [security, *dependencies]
