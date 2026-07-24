from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.resources import Resource


def add_prometheus_exporter(app: FastAPI, resource: Resource | None = None) -> None:
    from opentelemetry import metrics
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.sdk.metrics import MeterProvider
    from prometheus_client import make_asgi_app

    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[PrometheusMetricReader()])
    )

    app.mount("/metrics", make_asgi_app())


def add_prometheus_middleware(
    app: FastAPI,
    endpoint: str = "/metrics",
    **kwargs: Any,
) -> None:
    from starlette_exporter import PrometheusMiddleware, handle_metrics

    kwargs.setdefault("group_paths", True)
    kwargs.setdefault("app_name", app.title.lower().replace(" ", "_"))
    kwargs.setdefault("labels", {"server": socket.gethostname()})
    kwargs.setdefault("always_use_int_status", True)
    kwargs.setdefault("filter_unhandled_paths", False)
    kwargs.setdefault("group_unhandled_paths", True)
    app.add_middleware(PrometheusMiddleware, **kwargs)
    app.add_route(endpoint, handle_metrics)
