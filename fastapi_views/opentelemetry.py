from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI


try:
    import opentelemetry.instrumentation.fastapi  # noqa: F401

    OPENTELEMETRY_INSTALLED = True
except ImportError:
    OPENTELEMETRY_INSTALLED = False


_CORRELATION_ID: ContextVar[str | None] = ContextVar("_CORRELATION_ID", default=None)


def get_correlation_id() -> str | None:
    return _CORRELATION_ID.get()


def set_correlation_id(correlation_id: str) -> None:
    _CORRELATION_ID.set(correlation_id)


def maybe_instrument_app(app: FastAPI, **options: Any) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.trace import Span, format_trace_id
    except ImportError:
        return

    def server_request_hook(span: Span, _scope: dict[str, Any]) -> None:
        if span and span.is_recording():
            span_context = span.get_span_context()
            trace_id = format_trace_id(span_context.trace_id)
            set_correlation_id(trace_id)

    options.setdefault("server_request_hook", server_request_hook)
    FastAPIInstrumentor.instrument_app(app, **options)
