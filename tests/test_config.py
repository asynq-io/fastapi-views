from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from fastapi_views import configure_app
from fastapi_views.config import custom_openapi, simplify_operation_ids


def test_configure_app(app):
    configure_app(app)


def test_simplify_operation_ids():
    app = FastAPI()

    @app.get("/hello")
    def hello_world():
        return {}

    simplify_operation_ids(app)
    for route in app.routes:
        if isinstance(route, APIRoute) and route.name == "hello_world":
            assert route.operation_id == "hello_world"


def test_custom_openapi_removes_422():
    app = FastAPI()

    @app.post("/items")
    def create_item(name: str):
        return {"name": name}

    schema = custom_openapi(app)
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "responses" in operation:
                assert "422" not in operation["responses"]


def test_custom_openapi_caches():
    app = FastAPI()

    @app.get("/test")
    def test_route():
        return {}

    schema1 = custom_openapi(app)
    schema2 = custom_openapi(app)
    assert schema1 is schema2
