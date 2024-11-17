from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

CORRELATION_ID: ContextVar[str | None] = ContextVar("CORRELATION_ID", default=None)


def get_correlation_id() -> str | None:
    return CORRELATION_ID.get()


def maybe_instrument_app(app: FastAPI, **options: Any) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.trace import Span, format_trace_id

        def server_request_hook(span: Span, _scope: dict[str, Any]) -> None:
            if span and span.is_recording():
                span_context = span.get_span_context()
                trace_id = format_trace_id(span_context.trace_id)
                CORRELATION_ID.set(trace_id)

        options.setdefault("server_request_hook", server_request_hook)
        FastAPIInstrumentor.instrument_app(app, **options)
    except ImportError:
        pass
