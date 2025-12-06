import pytest
from fastapi import FastAPI

from fastapi_views import ViewRouter


def view_as_fixture(name: str, prefix: str = "/test"):
    def wrapper(cls):
        @pytest.fixture(name=name)
        def _view_fixture(app: FastAPI) -> None:
            router = ViewRouter()
            router.register_view(cls, prefix=prefix)
            app.include_router(router)

        return _view_fixture

    return wrapper
