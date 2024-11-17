import socket
from typing import Any

from fastapi import FastAPI


def add_prometheus_middleware(
    app: FastAPI, endpoint: str = "/metrics", **kwargs: Any
) -> None:
    from starlette_exporter import PrometheusMiddleware, handle_metrics

    kwargs.setdefault("group_paths", True)
    kwargs.setdefault("app_name", app.title.lower().replace(" ", "_"))
    kwargs.setdefault("skip_paths", ["/healthz", "/docs", "/openapi.json", "/metrics"])
    kwargs.setdefault("labels", {"server": socket.gethostname()})
    kwargs.setdefault("always_use_int_status", True)
    kwargs.setdefault("filter_unhandled_paths", False)
    kwargs.setdefault("group_unhandled_paths", True)
    app.add_middleware(PrometheusMiddleware, **kwargs)
    app.add_route(endpoint, handle_metrics)
