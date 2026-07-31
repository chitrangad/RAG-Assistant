"""Tests for health and readiness endpoints."""

import pytest


@pytest.mark.asyncio
async def test_root_endpoint(client):
    """Test the root endpoint returns the query interface."""
    response = await client.get("/")
    assert response.status_code == 200
    # Root now returns an HTML query page
    content_type = response.headers.get("content-type", "")
    assert "text/html" in content_type
    assert "RAG Knowledge Assistant" in response.text


@pytest.mark.asyncio
async def test_api_info_endpoint(client):
    """Test the /api/info endpoint returns app info as JSON."""
    response = await client.get("/api/info")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "RAG Knowledge Assistant"
    assert "version" in data
    assert data["docs"] == "/docs"


@pytest.mark.asyncio
async def test_health_check(client):
    """Test the health endpoint returns OK."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "RAG Knowledge Assistant"


@pytest.mark.asyncio
async def test_readiness_check(client):
    """Test the readiness endpoint checks database."""
    response = await client.get("/api/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert "checks" in data
    assert "database" in data["checks"]


@pytest.mark.asyncio
async def test_request_id_header(client):
    """Test that the request ID middleware adds the X-Request-ID header."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


@pytest.mark.asyncio
async def test_404_handling(client):
    """Test that unknown routes return 404."""
    response = await client.get("/api/nonexistent")
    assert response.status_code == 404
