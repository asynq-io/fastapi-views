import logging
import sys
from collections.abc import MutableMapping
from typing import Any, Literal

import orjson
import structlog


def _json_dumps(obj: Any, **options: Any) -> str:
    return orjson.dumps(obj, **options).decode("utf-8")


try:
    from opentelemetry.trace import format_span_id, format_trace_id, get_current_span

    def _add_trace_info(
        _: Any, __: Any, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:

        span = get_current_span()
        if not span.is_recording():
            return event_dict

        ctx = span.get_span_context()
        event_dict.update(
            {
                "span_id": format_span_id(ctx.span_id),
                "trace_id": format_trace_id(ctx.trace_id),
            }
        )
        return event_dict
except ImportError:
    _add_trace_info = None  # type: ignore[assignment]


def configure_logging(
    log_format: Literal["console", "json"] = "console", log_level: int = logging.INFO
) -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if _add_trace_info is not None:
        shared_processors.append(_add_trace_info)

    if log_format == "console":
        format_processors: list[structlog.types.Processor] = [
            structlog.dev.set_exc_info,
        ]
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            exception_formatter=structlog.dev.RichTracebackFormatter()
        )
    elif log_format == "json":
        format_processors = [
            structlog.processors.ExceptionRenderer(
                structlog.tracebacks.ExceptionDictTransformer(show_locals=False)
            ),
        ]
        renderer = structlog.processors.JSONRenderer(_json_dumps)
    else:
        msg = f"Unknown config log format {log_format}"
        raise ValueError(msg)

    structlog.configure(
        processors=[
            *shared_processors,
            *format_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Single handler renders everything — structlog and foreign stdlib loggers alike
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
            foreign_pre_chain=[
                *shared_processors,
                *format_processors,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    for name in logging.root.manager.loggerDict:
        existing = logging.getLogger(name)
        existing.handlers = []
        existing.propagate = True
