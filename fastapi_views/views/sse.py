from abc import abstractmethod
from collections.abc import AsyncIterator, Generator
from typing import Any, ClassVar, Generic
from uuid import uuid4

from fastapi.responses import StreamingResponse
from starlette.status import HTTP_200_OK

from fastapi_views.models import ServerSentEvent

from .api import APIView, Endpoint, P
from .functools import errors, serialize_sse


class ServerSentEventsAPIView(APIView, Generic[P]):
    sse_headers: ClassVar[dict[str, str]] = {
        "Cache-Control": "no-store",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("events", HTTP_200_OK)
        response_schema_data = cls.get_response_schema() or Any
        sse_schema = ServerSentEvent[response_schema_data].get_openapi_schema()  # type: ignore[valid-type]
        yield cls.get_api_action(
            prefix=prefix,
            endpoint=cls.get_events_endpoint(status_code),
            methods=["GET"],
            action="events",
            status_code=status_code,
            response_class=StreamingResponse,
            responses={
                status_code: {"content": {"text/event-stream": {"schema": sse_schema}}},
            }
            | errors(*cls.default_errors),
        )
        yield from super().get_api_actions(prefix)

    @property
    def event_id(self) -> str:
        return str(uuid4())

    @property
    def retry(self) -> int | None:
        return None

    @classmethod
    def get_events_endpoint(cls, status_code: int = HTTP_200_OK) -> Endpoint:
        async def endpoint(
            self: ServerSentEventsAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> StreamingResponse:
            return StreamingResponse(
                self._serialized_events(*args, **kwargs),
                status_code=status_code,
                media_type="text/event-stream",
                headers=self.sse_headers,
            )

        cls._patch_endpoint_signature(endpoint, cls.events)
        return endpoint

    async def _serialized_events(
        self,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> AsyncIterator[str]:
        schema = self.get_response_schema("events")
        serializer = self.get_serializer(schema)

        async for event, data in self.events(*args, **kwargs):
            data = self.get_json_content(data, serializer).decode("utf-8")
            yield serialize_sse(self.event_id, event, data, self.retry)

    @abstractmethod
    def events(self, *args: P.args, **kwargs: P.kwargs) -> AsyncIterator[Any]:
        raise NotImplementedError
