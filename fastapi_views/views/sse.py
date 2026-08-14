from abc import abstractmethod
from collections.abc import AsyncIterator, Generator
from typing import Any, ClassVar, Generic

from fastapi.responses import StreamingResponse
from starlette.status import HTTP_200_OK

from fastapi_views.models import AnyServerSentEvent
from fastapi_views.types import ServerSentEventType

from .api import APIView, Endpoint, P
from .functools import serialize_sse, sse_data_annotation, sse_openapi_content


class ServerSentEventsAPIView(APIView, Generic[P]):
    """API view streaming Server-Sent Events yielded by the `events` action."""

    sse_headers: ClassVar[dict[str, str]] = {
        "Cache-Control": "no-store",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("events", HTTP_200_OK)
        event_model = cls.get_response_schema("events") or AnyServerSentEvent
        yield cls.get_api_action(
            prefix=prefix,
            endpoint=cls.get_events_endpoint(status_code),
            methods=["GET"],
            action="events",
            status_code=status_code,
            response_model=None,
            response_class=StreamingResponse,
            responses={
                status_code: {"content": sse_openapi_content(event_model)},
            },
        )
        yield from super().get_api_actions(prefix)

    @classmethod
    def get_events_endpoint(cls, status_code: int = HTTP_200_OK) -> Endpoint:
        action = cls.events.__name__

        async def endpoint(
            self: ServerSentEventsAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> StreamingResponse:
            self._authorize(action)
            return StreamingResponse(
                self._serialized_events(*args, **kwargs),
                status_code=status_code,
                headers=self.sse_headers,
                media_type="text/event-stream",
            )

        cls._patch_endpoint_signature(endpoint, cls.events)
        return endpoint

    async def _serialized_events(
        self,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> AsyncIterator[str]:
        event_schema = self.get_response_schema("events") or AnyServerSentEvent
        serializer = self.get_serializer(sse_data_annotation(event_schema))

        async for sse in self.events(*args, **kwargs):
            data = serializer.dump_json(sse.data, **self.serializer_options).decode(
                "utf-8"
            )
            yield serialize_sse(sse.id, sse.event, data, sse.retry)

    @abstractmethod
    def events(
        self, *args: P.args, **kwargs: P.kwargs
    ) -> AsyncIterator[ServerSentEventType]:
        raise NotImplementedError
