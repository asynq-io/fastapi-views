from fastapi import params

from fastapi_views.exceptions import APIError, BadRequest, Forbidden, Unauthorized
from fastapi_views.types import Action
from fastapi_views.views import APIView

from .abc import ScopesAuth


class AutoScopesAuthView(APIView):
    auth: ScopesAuth
    resource: str | None = None
    default_errors: tuple[type[APIError], ...] = (BadRequest, Unauthorized, Forbidden)

    @classmethod
    def get_dependencies(cls, action: Action | None = None) -> list[params.Depends]:
        if action is None:
            return []
        resource_name = cls.resource or cls.get_name()
        if action in ("list", "retrieve", "events"):
            return [cls.auth.requires(f"read:{resource_name}")]
        if action in (
            "create",
            "update",
            "partial_update",
            "bulk_create",
            "bulk_update",
            "update_many",
        ):
            return [cls.auth.requires(f"edit:{resource_name}")]
        if action in ("destroy", "bulk_delete"):
            return [cls.auth.requires(f"delete:{resource_name}")]
        return []
