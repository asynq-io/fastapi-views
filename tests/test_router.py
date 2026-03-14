from __future__ import annotations

import pytest

import fastapi_views.types as t
from fastapi_views.router import ViewRouter
from fastapi_views.views.api import AsyncListAPIView


def test_register_abstract_view_raises():
    router = ViewRouter()
    with pytest.raises(TypeError, match="abstract"):
        router.register_view(AsyncListAPIView, prefix="/test")


def test_types_module_importable():
    assert hasattr(t, "Action")
    assert hasattr(t, "SerializerOptions")
    assert hasattr(t, "RouteOptions")
    assert hasattr(t, "PathRouteOptions")
