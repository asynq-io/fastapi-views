from typing import Annotated, ClassVar
from uuid import UUID

from auth0_api_python import ApiClient, ApiClientOptions
from fastapi import FastAPI
from pydantic import BaseModel

from fastapi_views import ViewRouter, configure_app
from fastapi_views.auth import AutoScopesAuthView, Delete, Edit, Read
from fastapi_views.integrations.auth0 import Auth0
from fastapi_views.views.viewsets import AsyncAPIViewSet, AsyncReadOnlyAPIViewSet


class Principal(BaseModel):
    """Typed view over the claims Auth0 verified for the current request."""

    sub: str
    scope: str = ""


## Auth setup

api_client = ApiClient(
    ApiClientOptions(
        domain="your-tenant.auth0.com",
        audience="https://api.example.com",
    )
)
# scheme defaults to HTTP Bearer; use permission_key="permissions"
# when Auth0 RBAC puts permissions in the `permissions` claim.
# custom_class is applied to the verified claims, after scope validation.
auth = Auth0(api_client, custom_class=Principal.model_validate)


## Protecting a single route


app = FastAPI(title="My API")


@app.get("/me")
async def me(principal: Annotated[Principal, auth.authenticated()]):
    return {"sub": principal.sub}


## Per-action scopes on a viewset


class ItemSchema(BaseModel):
    id: UUID
    name: str
    price: int


class ItemViewSet(AsyncAPIViewSet):
    api_component_name = "Item"
    response_schema = ItemSchema
    items: ClassVar[dict[UUID, ItemSchema]] = {}

    action_dependencies: ClassVar = {
        "list": [auth.requires(f"{Read}:items")],
        "retrieve": [auth.requires(f"{Read}:items")],
        "create": [auth.requires(f"{Edit}:items")],
        "update": [auth.requires(f"{Edit}:items")],
        "destroy": [auth.requires(f"{Delete}:items")],
    }

    async def list(self) -> list[ItemSchema]:
        return list(self.items.values())

    async def create(self, item: ItemSchema) -> ItemSchema:
        self.items[item.id] = item
        return item

    async def retrieve(self, id: UUID) -> ItemSchema | None:
        return self.items.get(id)

    async def update(self, id: UUID, item: ItemSchema) -> ItemSchema:
        self.items[id] = item
        return item

    async def destroy(self, id: UUID) -> None:
        self.items.pop(id, None)


class ReportSchema(BaseModel):
    id: UUID
    title: str


class ReportViewSet(AutoScopesAuthView, AsyncReadOnlyAPIViewSet):
    auth = auth
    resource = "reports"
    api_component_name = "Report"
    response_schema = ReportSchema
    reports: ClassVar[dict[UUID, ReportSchema]] = {}

    async def list(self) -> list[ReportSchema]:
        return list(self.reports.values())

    async def retrieve(self, id: UUID) -> ReportSchema | None:
        return self.reports.get(id)


router = ViewRouter(prefix="/items")
router.register_view(ItemViewSet)

reports_router = ViewRouter(prefix="/reports")
reports_router.register_view(ReportViewSet)

app.include_router(router)
app.include_router(reports_router)
configure_app(app)
