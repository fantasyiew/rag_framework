import httpx
import pytest

from rag_framework.api.main import app


@pytest.mark.asyncio
async def test_console_assets_and_api_routes_coexist():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert "RAG Lab" in page.text
        for path, content_type in [("/app.js", "javascript"), ("/style.css", "text/css")]:
            response = await client.get(path)
            assert response.status_code == 200
            assert content_type in response.headers["content-type"]
        schema = await client.get("/openapi.json")
        assert "/v1/evaluations/rag" in schema.json()["paths"]
        missing = await client.get("/v1/evaluations/not-found")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Evaluation report not found"
