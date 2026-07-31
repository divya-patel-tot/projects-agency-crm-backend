import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_liveness(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_graphql_status(client: AsyncClient):
    response = await client.post("/graphql", json={"query": "{ status }"})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ok"
