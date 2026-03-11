from __future__ import annotations

import pytest

from fastapi_views.router import ViewRouter


def test_register_abstract_view_raises():
    from fastapi_views.views.api import AsyncListAPIView

    router = ViewRouter()
    with pytest.raises(TypeError, match="abstract"):
        router.register_view(AsyncListAPIView, prefix="/test")


def test_types_module_importable():
    import fastapi_views.types as t

    assert hasattr(t, "Action")
    assert hasattr(t, "SerializerOptions")
    assert hasattr(t, "RouteOptions")
    assert hasattr(t, "PathRouteOptions")
