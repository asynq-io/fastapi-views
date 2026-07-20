from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        use_enum_values=True,
        populate_by_name=True,
        from_attributes=True,
    )


class OpenAPIBase(BaseSchema):
    """Schema which can render itself as an OpenAPI schema.

    `__content_type__` declares the media type under which the schema
    is documented (and served). Nested models are referenced via
    `#/components/schemas/` and shipped in the `$defs` key, which
    `custom_openapi` merges into the application components.
    """

    __content_type__: ClassVar[str] = "application/json"

    @classmethod
    def get_openapi_schema(cls, title: str | None = None) -> dict[str, Any]:
        schema_dump = cls.model_json_schema(
            ref_template="#/components/schemas/{model}",
            mode="serialization",
        )
        if title:
            schema_dump["title"] = title
        return schema_dump

    @classmethod
    def get_openapi_content(cls, title: str | None = None) -> dict[str, Any]:
        """Render the schema as OpenAPI response content keyed by `__content_type__`."""
        return {cls.__content_type__: {"schema": cls.get_openapi_schema(title)}}
