import pytest
from httpx import Response


def validate_response_meta(response: Response, status_code: int = 200):
    assert response.status_code == status_code
    assert response.headers["Content-Type"] == "application/json"
    assert "Content-Length" in response.headers


@pytest.mark.usefixtures("list_view")
async def test_list_api_view(client, dummy_data):
    response = await client.get("/test")
    assert response.json() == [dummy_data]
    validate_response_meta(response)


@pytest.mark.usefixtures("retrieve_view")
async def test_retrieve_api_view(client, dummy_data):
    response = await client.get("/test")
    assert response.json() == dummy_data
    validate_response_meta(response)


@pytest.mark.usefixtures("create_view")
async def test_create_api_view(client, dummy_data):
    response = await client.post("/test")
    assert response.json() == dummy_data
    validate_response_meta(response, 201)


@pytest.mark.usefixtures("destroy_view")
async def test_destroy_api_view(client):
    response = await client.delete("/test")
    assert response.status_code == 204
