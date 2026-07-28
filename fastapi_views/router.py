from __future__ import annotations

from inspect import isabstract
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from starlette.status import HTTP_200_OK

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi.params import Depends

    from .models import ResponseHeaders
    from .views.api import View
    from .views.websockets import WebSocketAPIView


def _path_specificity(path: str) -> tuple[int, ...]:
    """Rank a path so literal segments sort before parameterized ones.

    Starlette matches routes in registration order, so a static route like
    ``/items/stats`` must be registered before ``/items/{id}`` or the latter
    swallows it. Each segment maps to ``0`` (literal) or ``1`` (``{param}``);
    ascending tuple order yields most-specific-first.
    """
    return tuple(
        1 if segment.startswith("{") else 0 for segment in path.strip("/").split("/")
    )


def _route_sort_key(route_params: dict[str, Any]) -> tuple[int, ...]:
    return _path_specificity(route_params["path"])


class ViewRouter(APIRouter):
    def __init__(
        self,
        *args: Any,
        response_headers: type[ResponseHeaders] | None = None,
        **kwargs: Any,
    ) -> None:
        """``response_headers`` documents headers on every route's success response."""
        super().__init__(*args, **kwargs)
        self.response_headers = response_headers

    def _check_not_abstract(self, type_: object) -> None:
        if isabstract(type_):
            msg = f"Cannot register abstract view {type_}"
            raise TypeError(msg)

    def register_view(self, view: type[View], prefix: str = "", **kwargs: Any) -> None:
        self._check_not_abstract(view)
        # Sort is stable, so same-specificity routes keep their declared order.
        routes = sorted(view.get_api_actions(prefix), key=_route_sort_key)
        response_headers = self.response_headers
        for route_params in routes:
            route_params.update(kwargs)
            if response_headers is not None:
                self._document_response_headers(route_params, response_headers)
            self.add_api_route(**route_params)

    def _document_response_headers(
        self,
        route_params: dict[str, Any],
        response_headers: type[ResponseHeaders],
    ) -> None:
        status_code = route_params.get("status_code") or HTTP_200_OK
        responses = route_params.setdefault("responses", {})
        # Copy before mutating: the per-status dict may be the very object
        # stored on a decorated method, shared across routers.
        entry = {**responses.get(status_code, {})}
        entry["headers"] = {
            **entry.get("headers", {}),
            **response_headers.get_openapi_headers(),
        }
        responses[status_code] = entry

    def register_websocket_view(
        self,
        view: type[WebSocketAPIView],
        prefix: str = "",
        dependencies: Sequence[Depends] | None = None,
    ) -> None:
        self._check_not_abstract(view)
        websocket_route = view.get_websocket_action(prefix)
        websocket_route["dependencies"] = dependencies
        self.add_api_websocket_route(**websocket_route)
