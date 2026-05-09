from pydantic import Field

from fastapi_views.models import BaseSchema

from .scopes import ValidatedScopes


class User(BaseSchema):
    id: str = Field(validation_alias="sub")
    scopes: ValidatedScopes = Field(validation_alias="scope")
