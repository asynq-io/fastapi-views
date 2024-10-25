from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

try:
    from opentelemetry import trace
    from opentelemetry.trace import format_trace_id

    def get_correlation_id() -> str | None:
        span = trace.get_current_span()
        if span.is_recording():
            span_context = span.get_span_context()
            return format_trace_id(span_context.trace_id)
        return None

except ImportError:

    def get_correlation_id() -> str | None:
        return None


try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
except ImportError:
    FastAPIInstrumentor = None


def maybe_instrument_app(app: FastAPI, **options: Any) -> None:
    if FastAPIInstrumentor is not None:
        FastAPIInstrumentor.instrument_app(app, **options)
