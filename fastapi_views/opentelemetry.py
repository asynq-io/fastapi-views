from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI


try:
    import opentelemetry.instrumentation.fastapi  # noqa: F401
    from opentelemetry.trace import format_trace_id, get_current_span

    def get_correlation_id() -> str | None:
        context = get_current_span().get_span_context()
        if context.is_valid:
            return format_trace_id(context.trace_id)
        return None

    OPENTELEMETRY_INSTALLED = True
except ImportError:
    OPENTELEMETRY_INSTALLED = False

    def get_correlation_id() -> str | None:
        return None


def maybe_instrument_app(app: FastAPI, **options: Any) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        return

    FastAPIInstrumentor.instrument_app(app, **options)
