from __future__ import annotations

from inspect import isabstract
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi.params import Depends

    from .views.api import View
    from .views.websockets import WebSocketAPIView


class ViewRouter(APIRouter):
    def _check_not_abstract(self, type_: object) -> None:
        if isabstract(type_):
            msg = f"Cannot register abstract view {type_}"
            raise TypeError(msg)

    def register_view(self, view: type[View], prefix: str = "", **kwargs: Any) -> None:
        self._check_not_abstract(view)
        for route_params in view.get_api_actions(prefix):
            route_params.update(kwargs)
            self.add_api_route(**route_params)

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
