from inspect import isabstract
from typing import Any

from fastapi import APIRouter

from .views.api import View


def register_view(
    router: APIRouter, view: type[View], prefix: str = "", **kwargs: Any
) -> None:
    if isabstract(view):
        msg = f"Cannot register abstract view {view}"
        raise TypeError(msg)
    for route_params in view.get_api_actions(prefix):
        route_params.update(kwargs)
        router.add_api_route(**route_params)


class ViewRouter(APIRouter):
    register_view = register_view
