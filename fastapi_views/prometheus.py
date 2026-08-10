from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Any

from starlette.responses import Response

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.resources import Resource
    from starlette.requests import Request


def render_metrics(request: Request) -> Response:
    """Render the default `prometheus_client` registry in the negotiated format."""
    from prometheus_client import REGISTRY
    from prometheus_client.exposition import choose_encoder

    encoder, content_type = choose_encoder(request.headers.get("accept", ""))
    return Response(encoder(REGISTRY), media_type=content_type)


def add_prometheus_exporter(
    app: FastAPI,
    resource: Resource | None = None,
    endpoint: str = "/metrics",
) -> None:
    from opentelemetry import metrics
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.sdk.metrics import MeterProvider

    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[PrometheusMetricReader()])
    )

    app.add_route(endpoint, render_metrics)


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
