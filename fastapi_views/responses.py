from typing import Any

from fastapi.responses import StreamingResponse


class EventStreamResponse(StreamingResponse):
    """Streaming response with the `text/event-stream` media type."""

    def __init__(self, content: Any, **kwargs: Any) -> None:
        kwargs.setdefault("media_type", "text/event-stream")
        super().__init__(content, **kwargs)
