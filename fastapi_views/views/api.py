from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Concatenate,
    Generic,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from fastapi import Request, Response
from fastapi.utils import is_body_allowed_for_status_code
from pydantic.type_adapter import TypeAdapter
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from typing_extensions import ParamSpec

from fastapi_views.exceptions import (
    APIError,
    BadRequest,
    Conflict,
    Forbidden,
    NotFound,
    Unauthorized,
)
from fastapi_views.permissions.abc import (
    BasePermission,
    app_auth_security,
    get_app_auth_or_none,
    permission_denied,
)
from fastapi_views.permissions.builtin import AllowAny
from fastapi_views.types import (
    Action,
    AnyTypeAdapter,
    Endpoint,
    SerializerOptions,
    TypeAdapterMap,
)

from .functools import VIEWSET_ROUTE_FLAG, errors
from .mixins import DependencyMixin, DetailViewMixin, ErrorHandlerMixin

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping, Sequence

    from fastapi import params

    from fastapi_views.models import ResponseHeaders

P = ParamSpec("P")
T = TypeVar("T")


def _contains_response_type(annotation: Any) -> bool:
    """Whether ``annotation`` is or contains a ``Response`` subclass.

    Recurses through unions, ``Annotated`` and other generics — pydantic cannot
    build a response field from any annotation embedding a ``Response``.
    """
    if get_origin(annotation) is None and isinstance(annotation, type):
        return issubclass(annotation, Response)
    return any(_contains_response_type(arg) for arg in get_args(annotation))


_BODY_KEYS = ("model", "content")


def _merge_response_entry(
    generated: dict[str, Any],
    explicit: dict[str, Any],
) -> dict[str, Any]:
    """Merge one status-code entry, letting ``explicit`` win key by key.

    A body declared by ``explicit`` (``model`` or ``content``) replaces the
    generated one instead of documenting both, while ``headers`` maps are
    combined. Both inputs are left untouched — a per-status dict may be the
    very object stored on a decorated method, shared across registrations.
    """
    merged = {**generated, **explicit}
    if any(key in explicit for key in _BODY_KEYS):
        for key in _BODY_KEYS:
            if key not in explicit:
                merged.pop(key, None)
    headers = {**generated.get("headers", {}), **explicit.get("headers", {})}
    if headers:
        merged["headers"] = headers
    return merged


def _merge_responses(
    generated: dict[int | str, Any],
    explicit: dict[int | str, Any],
) -> dict[int | str, Any]:
    """Merge two OpenAPI ``responses`` maps, preferring ``explicit``.

    Status codes only ``generated`` documents survive, so an explicitly
    declared response never erases the errors the route can really return.
    """
    merged: dict[int | str, Any] = dict(generated)
    for status, response in explicit.items():
        current = merged.get(status)
        if isinstance(current, dict) and isinstance(response, dict):
            merged[status] = _merge_response_entry(current, response)
        else:
            merged[status] = response
    return merged


class View(DependencyMixin, ABC):
    """Base View Class"""

    api_component_name: str
    errors: tuple[type[APIError], ...] = ()
    from_attributes: bool | None = None
    validate_response: bool = True
    _serializers: ClassVar[TypeAdapterMap] = {}
    #: Current action name, set by the endpoint wrapper before checks run.
    action: str | None = None

    def __init__(self, request: Request, response: Response) -> None:
        self.request = request
        self.response = response
        scope = getattr(request, "scope", None)
        self.principal: Any = scope.get("principal") if scope is not None else None

    def check_permissions(self) -> None:
        """No-op on the base ``View``; :class:`APIView` enforces permissions."""

    def check_object_permissions(self, obj: Any) -> None:
        """No-op on the base ``View``; :class:`APIView` enforces permissions."""

    def _authorize(self, action: str | None) -> None:
        """Set the current action and run view-level permission checks."""
        self.action = action
        self.check_permissions()

    def _set_default_media_type(self, media_type: str) -> None:
        if self.response.media_type is None:
            self.response.media_type = media_type

    @classmethod
    def get_name(cls) -> str:
        return getattr(cls, "api_component_name", cls.__name__)

    @classmethod
    def get_slug_name(cls) -> str:
        return f"{cls.get_name().lower().replace(' ', '_')}"

    def get_response(
        self,
        content: Any,
        *,
        status_code: int = HTTP_200_OK,
        schema: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        if isinstance(content, Response):
            return self.finalize_response(content)

        self.response.status_code = status_code

        if content is not None and not isinstance(content, (str, bytes)):
            serializer = self.get_serializer(schema)
            content = self.get_json_content(content=content, serializer=serializer)
            self._set_default_media_type("application/json")

        if isinstance(content, str):
            content = content.encode(self.response.charset)
            self._set_default_media_type("text/plain")
        if isinstance(content, bytes):
            self.response.body = content

        # Headers may already be set on the response (e.g. inside the view).
        # ``init_headers`` rebuilds ``raw_headers`` from ``headers`` alone, so
        # preserve the pre-existing ones it does not regenerate.
        preset = list(self.response.raw_headers)
        self.response.init_headers(headers)
        generated = {key for key, _ in self.response.raw_headers}
        self.response.raw_headers[:0] = [
            item for item in preset if item[0] not in generated
        ]
        # ``init_headers`` swapped in a fresh ``raw_headers`` list. FastAPI cached
        # a ``MutableHeaders`` over the *previous* list when it built the response
        # (``del response.headers["content-length"]``), so drop that stale cache
        # to keep ``response.headers`` in sync with what is actually sent.
        self.response.__dict__.pop("_headers", None)
        return self.finalize_response(self.response)

    def finalize_response(self, response: Response) -> Response:
        """Hook to post-process the built response before it is returned.

        Returns it unchanged by default; mixins such as
        :class:`~fastapi_views.views.mixins.ConditionalMixin` override this to
        attach validators and downgrade to ``304``.
        """
        return response

    def get_serializer(self, schema: Any | None) -> TypeAdapter[Any]:
        if schema is None:
            return AnyTypeAdapter
        if schema not in self._serializers:
            self._serializers[schema] = TypeAdapter(schema)
        return self._serializers[schema]

    def get_json_content(self, content: Any, serializer: TypeAdapter[Any]) -> Any:
        if self.validate_response:
            content = serializer.validate_python(
                content,
                from_attributes=self.from_attributes,
            )
        return serializer.dump_json(content)

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], Any, None]:
        yield from cls.get_custom_api_actions(prefix)

    @classmethod
    def get_custom_endpoint(
        cls,
        func: Callable[Concatenate[View, P], Any],
    ) -> Callable[Concatenate[View, P], Any]:
        options = getattr(func, "kwargs", {})
        status_code = options.get("status_code", HTTP_200_OK)
        schema = options.get("response_model", get_type_hints(func).get("return"))

        async def _async_endpoint(
            self: View,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(func.__name__)
            res = await func(self, *args, **kwargs)
            return self.get_response(res, status_code=status_code, schema=schema)

        def _sync_endpoint(self: View, *args: P.args, **kwargs: P.kwargs) -> Response:
            self._authorize(func.__name__)
            res = func(self, *args, **kwargs)
            return self.get_response(res, status_code=status_code, schema=schema)

        endpoint = (
            _async_endpoint if inspect.iscoroutinefunction(func) else _sync_endpoint
        )

        cls._patch_endpoint_signature(endpoint, func)
        return endpoint

    @classmethod
    def _is_endpoint(cls, member: Any) -> bool:
        return callable(member) and hasattr(member, VIEWSET_ROUTE_FLAG)

    @staticmethod
    def _is_response_model(annotation: Any) -> bool:
        """Whether a return annotation is usable as an OpenAPI response model."""
        if annotation is None or annotation is type(None):
            return False
        return not _contains_response_type(annotation)

    @classmethod
    def get_custom_api_actions(
        cls,
        prefix: str = "",
    ) -> Generator[dict[str, Any], None, None]:
        for _, route_endpoint in inspect.getmembers(cls, cls._is_endpoint):
            endpoint = cls.get_custom_endpoint(route_endpoint)
            options = getattr(route_endpoint, "kwargs", {})
            route_prefix = prefix
            if options.get("detail"):
                route_prefix += cls.get_action_detail_route()
            extra: dict[str, Any] = {}
            # Document what the endpoint actually serializes: the runtime
            # serializer falls back to the return annotation, so OpenAPI must
            # prefer it too (before the view-level response_schema default).
            if "response_model" not in options:
                return_annotation = get_type_hints(route_endpoint).get("return")
                if cls._is_response_model(return_annotation):
                    extra["response_model"] = return_annotation
            yield cls.get_api_action(
                endpoint,
                prefix=route_prefix,
                name=f"{endpoint.__name__} {cls.get_name()}",
                action=cast("Action", endpoint.__name__),
                **extra,
            )

    @classmethod
    def get_action_detail_route(cls) -> str:
        """Detail-route prefix for ``@action(detail=True)`` endpoints."""
        return getattr(cls, "detail_route", "/{id}")

    @classmethod
    def get_api_action(
        cls,
        endpoint: Callable,
        prefix: str = "",
        path: str = "",
        action: Action | None = None,  # noqa: ARG003
        **kwargs: Any,
    ) -> dict[str, Any]:
        kw = getattr(endpoint, "kwargs", {})
        generated_responses = kwargs.get("responses") or {}
        kwargs.update(kw)
        path = kwargs.get("path", path)
        kwargs["endpoint"] = endpoint
        kwargs["path"] = prefix + path
        kwargs.setdefault("name", endpoint.__name__)
        endpoint_name = kwargs["name"]
        kwargs.setdefault("methods", ["GET"])
        kwargs.setdefault("operation_id", f"{cls.get_slug_name()}_{endpoint_name}")
        kwargs["responses"] = _merge_responses(
            {e.get_status(): {"model": e.model} for e in cls.errors},
            _merge_responses(generated_responses, kw.get("responses") or {}),
        )
        status_code = kwargs.get("status_code")
        if status_code and not is_body_allowed_for_status_code(status_code):
            kwargs["response_model"] = None
        # ``detail`` (an ``@action`` marker applied to the path in
        # ``get_custom_api_actions``) and ``response_headers`` are not FastAPI
        # route arguments — consume them here so they never reach add_api_route.
        kwargs.pop("detail", None)
        response_headers = kwargs.pop("response_headers", None)
        if response_headers is not None:
            success = kwargs.get("status_code") or HTTP_200_OK
            responses = kwargs["responses"]
            # Copy before mutating: the per-status dict may be the very object
            # stored on the decorated method, shared across registrations.
            entry = {**responses.get(success, {})}
            entry["headers"] = {
                **entry.get("headers", {}),
                **response_headers.get_openapi_headers(),
            }
            responses[success] = entry
        return kwargs


class APIView(View, ErrorHandlerMixin, Generic[T]):
    """View with build-in json serialization via
    `serializer` and error handling
    """

    response_schema: T | None = None
    #: Auth this view enforces; ``None`` falls back to the app-wide one.
    auth: ClassVar[Any] = None
    #: Extra route-level dependencies applied per action, e.g. auth scopes.
    action_dependencies: ClassVar[Mapping[Action, Sequence[params.Depends]]] = {}
    #: Permissions enforced for every action via :meth:`check_permissions` /
    #: :meth:`check_object_permissions`. Override :meth:`get_permissions` to
    #: branch on ``self.action``.
    permission_classes: ClassVar[Sequence[type[BasePermission] | BasePermission]] = ()
    #: Per-action permissions; when present for an action they replace
    #: :attr:`permission_classes` for that action only.
    action_permission_classes: ClassVar[Mapping[str, Sequence[Any]]] = {}
    default_serializer_options: ClassVar[SerializerOptions] = {
        "by_alias": True,
    }
    default_errors: tuple[type[APIError], ...] = (BadRequest,)
    #: Permission instances resolved once per (view class, action).
    _resolved_permissions: ClassVar[
        dict[tuple[type, str | None], list[BasePermission]]
    ] = {}

    def __init__(self, request: Request, response: Response) -> None:
        self.validation_context = None
        self.serializer_options = self.default_serializer_options.copy()
        super().__init__(request, response)

    @classmethod
    def _permission_classes_for(cls, action: str | None) -> Sequence[Any]:
        if action is not None and action in cls.action_permission_classes:
            return cls.action_permission_classes[action]
        return cls.permission_classes

    @classmethod
    def _has_dynamic_permissions(cls) -> bool:
        """Whether :meth:`get_permissions` is overridden anywhere in the MRO.

        Such a view decides its permissions per request, so registration cannot
        tell whether the route is public. It is treated as protected: the
        alternative is a route documented as public whose ``principal`` is
        always ``None``, so every credential is rejected.
        """
        return cls.get_permissions is not APIView.get_permissions

    @classmethod
    def _requires_auth(cls, action: str | None) -> bool:
        """Whether ``action`` needs the auth dependency wired (non-public)."""
        if cls._has_dynamic_permissions():
            return True
        classes = cls._permission_classes_for(action)
        if not classes:
            return False
        return not all(isinstance(BasePermission.resolve(p), AllowAny) for p in classes)

    @classmethod
    def _resolve_permissions(cls, action: str | None) -> list[BasePermission]:
        """Permission instances for ``action``, resolved on first use.

        :attr:`permission_classes` / :attr:`action_permission_classes` are
        ``ClassVar``s fixed at class definition, so the instances are built once
        per view class and action instead of on every check.
        """
        key = (cls, action)
        resolved = cls._resolved_permissions.get(key)
        if resolved is None:
            resolved = [
                BasePermission.resolve(p) for p in cls._permission_classes_for(action)
            ]
            cls._resolved_permissions[key] = resolved
        return resolved

    def get_permissions(self) -> list[BasePermission]:
        """Resolved permission instances for the current action."""
        return self._resolve_permissions(self.action)

    def check_permissions(self) -> None:
        """Run ``has_permission`` for each configured permission (view-level)."""
        for perm in self.get_permissions():
            if not perm.has_permission(self.principal, self):
                raise permission_denied(self.principal, self.request)

    def check_object_permissions(self, obj: Any) -> None:
        """Run ``has_object_permission`` for each configured permission."""
        for perm in self.get_permissions():
            if not perm.has_object_permission(self.principal, self, obj):
                raise permission_denied(self.principal, self.request)

    def _authorize_object(self, obj: Any) -> None:
        """Run object-level checks unless there is nothing to authorize.

        A view returning ``None`` (a miss tolerated by ``raise_on_none=False``)
        or a ``Response`` (a short-circuit such as ``304 Not Modified``) yields
        no object to own, so the checks are skipped rather than denied.
        """
        if obj is None or isinstance(obj, Response):
            return
        self.check_object_permissions(obj)

    @classmethod
    def get_required_scopes(cls, action: str | None = None) -> list[str]:
        """Scopes the OpenAPI bridge advertises for ``action``."""
        return [
            scope
            for perm in cls._permission_classes_for(action)
            for scope in BasePermission.resolve(perm).required_scopes
        ]

    @classmethod
    def get_default_errors(
        cls, action: str | None = None
    ) -> tuple[type[APIError], ...]:
        """``default_errors`` plus ``Unauthorized``/``Forbidden`` when auth applies."""
        errors_ = cls.default_errors
        if cls._requires_auth(action):
            return (*errors_, Unauthorized, Forbidden)
        return errors_

    @classmethod
    def get_auth(cls) -> Any:
        """The auth to enforce with: :attr:`auth`, else the process-wide one.

        ``None`` means neither is set, so the dependency defers to whichever auth
        ``configure_app(app, auth=auth)`` binds to the app serving the request.
        """
        if cls.auth is not None:
            return cls.auth
        return get_app_auth_or_none()

    @classmethod
    def get_dependencies(cls, action: Action | None = None) -> list[params.Depends]:
        """Route-level dependencies for ``action``'s endpoint.

        Wires the OpenAPI security bridge — ``Security(auth.resolve_dependency,
        scopes)`` — for any non-public action, plus :attr:`action_dependencies`.
        Override for fully dynamic per-action dependencies.
        """
        if action is None:
            return []
        dependencies: list[params.Depends] = []
        if cls._requires_auth(action):
            dependencies.append(
                app_auth_security(cls.get_auth(), cls.get_required_scopes(action)),
            )
        dependencies.extend(cls.action_dependencies.get(action, ()))
        return dependencies

    @classmethod
    def get_response_headers(
        cls,
        action: Action | None = None,  # noqa: ARG003
    ) -> type[ResponseHeaders] | None:
        """Response headers to document in OpenAPI for the given ``action``.

        Override to declare headers (a :class:`~fastapi_views.models.ResponseHeaders`
        subclass) attached to the success response. Returns ``None`` by default.
        """
        return None

    @classmethod
    def get_conditional_responses(
        cls,
        *,
        action: Action | None = None,  # noqa: ARG003
        status_code: int | None = None,  # noqa: ARG003
        methods: Sequence[str] | None = None,  # noqa: ARG003
    ) -> dict[int | str, dict[str, Any]]:
        """Extra status-code responses contributed by mixins (e.g. ``304``).

        Returns an empty mapping by default; mixins such as
        :class:`~fastapi_views.views.mixins.ConditionalMixin` override this to
        document validator-driven responses.
        """
        return {}

    @classmethod
    def get_extra_responses(
        cls,
        *,
        action: Action | None = None,
        status_code: int | None = None,
        methods: Sequence[str] | None = None,
    ) -> dict[int | str, dict[str, Any]]:
        """Build the OpenAPI ``responses`` contributed by the view itself.

        Documents :meth:`get_response_headers` on the success status code and
        merges in any :meth:`get_conditional_responses`, combining the header
        maps when both target the same status code.
        """
        responses: dict[int | str, dict[str, Any]] = {}
        response_headers = cls.get_response_headers(action)
        if response_headers is not None and status_code is not None:
            responses[status_code] = {"headers": response_headers.get_openapi_headers()}
        conditional = cls.get_conditional_responses(
            action=action, status_code=status_code, methods=methods
        )
        for status, response in conditional.items():
            target = responses.setdefault(status, {})
            for key, value in response.items():
                if key == "headers" and "headers" in target:
                    target["headers"] = {**target["headers"], **value}
                else:
                    target[key] = value
        return responses

    @classmethod
    def get_api_action(
        cls,
        endpoint: Callable,
        prefix: str = "",
        path: str = "",
        action: Action | None = None,
        extra_errors: tuple[type[APIError], ...] = (),
        **kwargs: Any,
    ) -> dict[str, Any]:
        if action:
            kwargs.setdefault("name", f"{action.title()} {cls.get_name()}")
            kwargs.setdefault("operation_id", f"{action}_{cls.get_slug_name()}")

        kwargs.setdefault("response_model", cls.get_response_schema(action))

        dependencies = [
            *cls.get_dependencies(action),
            *(kwargs.get("dependencies") or ()),
        ]
        if dependencies:
            kwargs["dependencies"] = dependencies

        # A custom route's ``status_code`` / ``methods`` live on the decorated
        # method and only reach ``kwargs`` further down the MRO, so read them
        # from there too, or nothing gets documented for ``@action`` routes.
        route_options = getattr(endpoint, "kwargs", {})
        status_code = route_options.get("status_code") or kwargs.get("status_code")
        methods = route_options.get("methods") or kwargs.get("methods")
        extra_responses = cls.get_extra_responses(
            action=action,
            status_code=status_code or HTTP_200_OK,
            methods=methods or ["GET"],
        )
        kwargs["responses"] = _merge_responses(
            _merge_responses(
                errors(*extra_errors, *cls.get_default_errors(action)),
                extra_responses,
            ),
            kwargs.get("responses") or {},
        )
        return super().get_api_action(endpoint, prefix=prefix, path=path, **kwargs)

    @classmethod
    def get_status_code(cls, endpoint: str, default: int = HTTP_200_OK) -> int:
        method = getattr(cls, endpoint, None)
        return getattr(method, "kwargs", {}).get("status_code", default)

    @classmethod
    def get_response_schema(cls, action: Action | None = None) -> T | None:  # noqa: ARG003
        return cls.response_schema

    def get_json_content(self, content: Any, serializer: TypeAdapter[Any]) -> bytes:
        if self.validate_response:
            content = serializer.validate_python(
                content,
                from_attributes=self.from_attributes,
                context=self.validation_context,
            )
            return serializer.dump_json(content, **self.serializer_options)
        return serializer.dump_json(content, warnings=False, **self.serializer_options)


class BaseListAPIView(APIView):
    response_schema_as_list: bool = True

    @classmethod
    def get_response_schema(
        cls: type[BaseListAPIView],
        action: Action | None = None,
    ) -> Any:
        if action == "list" and cls.response_schema_as_list:
            return list[cls.response_schema]  # type: ignore[name-defined]
        return cls.response_schema

    @classmethod
    @abstractmethod
    def get_list_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("list")
        yield cls.get_api_action(
            prefix=prefix,
            endpoint=cls.get_list_endpoint(status_code),
            methods=["GET"],
            status_code=status_code,
            action="list",
        )
        yield from super().get_api_actions(prefix)


class AsyncListAPIView(BaseListAPIView, ABC, Generic[P]):
    """Async list api view"""

    @classmethod
    def get_list_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="list")
        action = cls.list.__name__

        async def endpoint(
            self: AsyncListAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            objects = await self.list(*args, **kwargs)
            return self.get_response(objects, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.list)
        return endpoint

    @abstractmethod
    async def list(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class ListAPIView(BaseListAPIView, ABC, Generic[P]):
    """Sync list api view"""

    @classmethod
    def get_list_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="list")
        action = cls.list.__name__

        def endpoint(self: ListAPIView, *args: P.args, **kwargs: P.kwargs) -> Response:
            self._authorize(action)
            objects = self.list(*args, **kwargs)
            return self.get_response(objects, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.list)
        return endpoint

    @abstractmethod
    def list(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseRetrieveAPIView(APIView, DetailViewMixin):
    @classmethod
    @abstractmethod
    def get_retrieve_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("retrieve")
        yield cls.get_api_action(
            prefix=prefix,
            endpoint=cls.get_retrieve_endpoint(status_code),
            path=cls.get_detail_route(action="retrieve"),
            methods=["GET"],
            status_code=status_code,
            action="retrieve",
            extra_errors=(NotFound,),
        )
        yield from super().get_api_actions(prefix)


class RetrieveAPIView(BaseRetrieveAPIView, Generic[P]):
    """Sync retrieve api view"""

    @classmethod
    def get_retrieve_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="retrieve")
        action = cls.retrieve.__name__

        def endpoint(
            self: RetrieveAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            obj = self.retrieve(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            self._authorize_object(obj)
            return self.get_response(obj, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.retrieve)
        return endpoint

    @abstractmethod
    def retrieve(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncRetrieveAPIView(BaseRetrieveAPIView, Generic[P]):
    """Async retrieve api view"""

    @classmethod
    def get_retrieve_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="retrieve")
        action = cls.retrieve.__name__

        async def endpoint(
            self: AsyncRetrieveAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            obj = await self.retrieve(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            self._authorize_object(obj)
            return self.get_response(obj, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.retrieve)
        return endpoint

    @abstractmethod
    async def retrieve(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseCreateAPIView(APIView):
    return_on_create: bool = True

    @classmethod
    @abstractmethod
    def get_create_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError

    def get_location(self, _obj: Any) -> str | None:
        return None

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("create", HTTP_201_CREATED)
        yield cls.get_api_action(
            prefix=prefix,
            endpoint=cls.get_create_endpoint(status_code),
            methods=["POST"],
            status_code=status_code,
            action="create",
            extra_errors=(Conflict,),
        )
        yield from super().get_api_actions(prefix)


class CreateAPIView(BaseCreateAPIView, Generic[P]):
    """Sync create api view"""

    @classmethod
    def get_create_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="create")
        action = cls.create.__name__

        def endpoint(
            self: CreateAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            obj = self.create(*args, **kwargs)
            location = self.get_location(obj)
            if not self.return_on_create:
                obj = None
            return self.get_response(
                obj,
                status_code=status_code,
                schema=schema,
                headers={"location": location} if location else None,
            )

        cls._patch_endpoint_signature(endpoint, cls.create)
        return endpoint

    @abstractmethod
    def create(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncCreateAPIView(BaseCreateAPIView, Generic[P]):
    """Async create api view"""

    @classmethod
    def get_create_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="create")
        action = cls.create.__name__

        async def endpoint(
            self: AsyncCreateAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            obj = await self.create(*args, **kwargs)
            location = self.get_location(obj)
            if not self.return_on_create:
                obj = None
            return self.get_response(
                obj,
                status_code=status_code,
                schema=schema,
                headers={"location": location} if location else None,
            )

        cls._patch_endpoint_signature(endpoint, cls.create)
        return endpoint

    @abstractmethod
    async def create(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseUpdateAPIView(APIView, DetailViewMixin):
    return_on_update: bool = True

    @classmethod
    @abstractmethod
    def get_update_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("update")
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.get_detail_route(action="update"),
            endpoint=cls.get_update_endpoint(status_code),
            methods=["PUT"],
            status_code=status_code,
            action="update",
            extra_errors=(NotFound,),
        )
        yield from super().get_api_actions(prefix)


class UpdateAPIView(BaseUpdateAPIView, Generic[P]):
    """Sync update api view"""

    @classmethod
    def get_update_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="update")
        action = cls.update.__name__

        def endpoint(
            self: UpdateAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            obj = self.update(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            if not self.return_on_update:
                obj = None
            return self.get_response(obj, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.update)
        return endpoint

    @abstractmethod
    def update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncUpdateAPIView(BaseUpdateAPIView, Generic[P]):
    """Async update api view"""

    @classmethod
    def get_update_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="update")
        action = cls.update.__name__

        async def endpoint(
            self: AsyncUpdateAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            obj = await self.update(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            if not self.return_on_update:
                obj = None
            return self.get_response(obj, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.update)
        return endpoint

    @abstractmethod
    async def update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BasePartialUpdateAPIView(APIView, DetailViewMixin):
    return_on_update: bool = True

    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("partial_update")
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.get_detail_route(action="partial_update"),
            endpoint=cls.get_partial_update_endpoint(status_code),
            methods=["PATCH"],
            status_code=status_code,
            action="partial_update",
            extra_errors=(NotFound,),
        )

        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_partial_update_endpoint(cls, status_code: int) -> Endpoint:
        raise NotImplementedError


class PartialUpdateAPIView(BasePartialUpdateAPIView, Generic[P]):
    """Sync partial update api view"""

    @classmethod
    def get_partial_update_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="partial_update")
        action = cls.partial_update.__name__

        def endpoint(
            self: PartialUpdateAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            obj = self.partial_update(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            if not self.return_on_update:
                obj = None
            return self.get_response(obj, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.partial_update)
        return endpoint

    @abstractmethod
    def partial_update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class AsyncPartialUpdateAPIView(BasePartialUpdateAPIView, Generic[P]):
    """Async partial update api view"""

    @classmethod
    def get_partial_update_endpoint(cls, status_code: int) -> Endpoint:
        schema = cls.get_response_schema(action="partial_update")
        action = cls.partial_update.__name__

        async def endpoint(
            self: AsyncPartialUpdateAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            obj = await self.partial_update(*args, **kwargs)
            if obj is None and self.raise_on_none:
                self.raise_not_found_error()
            if not self.return_on_update:
                obj = None
            return self.get_response(obj, status_code=status_code, schema=schema)

        cls._patch_endpoint_signature(endpoint, cls.partial_update)
        return endpoint

    @abstractmethod
    async def partial_update(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        raise NotImplementedError


class BaseDestroyAPIView(APIView, DetailViewMixin):
    @classmethod
    def get_api_actions(cls, prefix: str = "") -> Generator[dict[str, Any], None, None]:
        status_code = cls.get_status_code("destroy", HTTP_204_NO_CONTENT)
        yield cls.get_api_action(
            prefix=prefix,
            path=cls.get_detail_route(action="destroy"),
            endpoint=cls.get_destroy_endpoint(status_code),
            methods=["DELETE"],
            status_code=status_code,
            response_class=Response,
            action="destroy",
            responses=errors(*cls.default_errors),
        )
        yield from super().get_api_actions(prefix)

    @classmethod
    @abstractmethod
    def get_destroy_endpoint(cls, status_code: int) -> Any:
        raise NotImplementedError


class DestroyAPIView(BaseDestroyAPIView, Generic[P]):
    """Sync destroy api view"""

    @classmethod
    def get_destroy_endpoint(cls, status_code: int) -> Endpoint:
        action = cls.destroy.__name__

        def endpoint(
            self: DestroyAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            self.destroy(*args, **kwargs)
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.destroy)
        return endpoint

    @abstractmethod
    def destroy(self, *args: P.args, **kwargs: P.kwargs) -> None:
        raise NotImplementedError


class AsyncDestroyAPIView(BaseDestroyAPIView, Generic[P]):
    """Async destroy api view"""

    @classmethod
    def get_destroy_endpoint(cls, status_code: int) -> Endpoint:
        action = cls.destroy.__name__

        async def endpoint(
            self: AsyncDestroyAPIView,
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> Response:
            self._authorize(action)
            await self.destroy(*args, **kwargs)
            return Response(status_code=status_code)

        cls._patch_endpoint_signature(endpoint, cls.destroy)
        return endpoint

    @abstractmethod
    async def destroy(self, *args: P.args, **kwargs: P.kwargs) -> None:
        raise NotImplementedError
