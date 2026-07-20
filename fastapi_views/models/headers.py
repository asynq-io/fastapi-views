from typing import Any

from .base import OpenAPIBase

_IGNORED_HEADER_SCHEMA_KEYS = frozenset({"description", "title", "default"})


def _simplify_header_schema(prop: dict[str, Any]) -> dict[str, Any]:
    """Build a header ``schema`` from a property, collapsing nullable unions.

    A field typed as ``X | None`` yields ``anyOf: [X, null]``; response headers
    are never null, so the null branch is dropped and the remaining type merged.
    """
    schema = {
        key: value
        for key, value in prop.items()
        if key not in _IGNORED_HEADER_SCHEMA_KEYS
    }
    any_of = schema.get("anyOf")
    if any_of is None:
        return schema
    non_null = [option for option in any_of if option.get("type") != "null"]
    if len(non_null) == 1:
        del schema["anyOf"]
        return {**schema, **non_null[0]}
    if len(non_null) < len(any_of):
        schema["anyOf"] = non_null
    return schema


def _contains_refs(schema: Any) -> bool:
    if isinstance(schema, dict):
        return "$ref" in schema or any(_contains_refs(v) for v in schema.values())
    if isinstance(schema, list):
        return any(_contains_refs(v) for v in schema)
    return False


class ResponseHeaders(OpenAPIBase):
    """Class used to specify OpenAPI for response headers.

    `get_openapi_headers` renders each field as an OpenAPI `Header Object
    <https://spec.openapis.org/oas/v3.1.0#header-object>`_: ``description`` is
    lifted to the top level, the remaining JSON schema is nested under
    ``schema``, and required fields are flagged with ``required: true``.
    Referenced models travel in ``$defs``, relocated to the application
    components by ``custom_openapi``.
    """

    @classmethod
    def get_openapi_headers(cls) -> dict[str, Any]:
        base = cls.get_openapi_schema()
        defs = base.get("$defs", {})
        required = base.get("required", [])
        headers: dict[str, Any] = {}
        for name, prop in base.get("properties", {}).items():
            header: dict[str, Any] = {}
            description = prop.get("description")
            if description is not None:
                header["description"] = description
            if name in required:
                header["required"] = True
            schema = _simplify_header_schema(prop)
            if defs and _contains_refs(schema):
                schema["$defs"] = defs
            header["schema"] = schema
            headers[name] = header
        return headers
