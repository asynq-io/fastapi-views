from __future__ import annotations

from inspect import isabstract
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

if TYPE_CHECKING:
    from .views.api import View


class ViewRouter(APIRouter):
    def register_view(self, view: type[View], prefix: str = "", **kwargs: Any) -> None:
        if isabstract(view):
            msg = f"Cannot register abstract view {view}"
            raise TypeError(msg)
        for route_params in view.get_api_actions(prefix):
            route_params.update(kwargs)
            self.add_api_route(**route_params)
