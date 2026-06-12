"""Smoke tests for the FastAPI app that don't require external services."""

from __future__ import annotations

import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_health_ok():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_root_and_metrics():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        metrics = await client.get("/metrics")
    assert root.status_code == 200
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text


@pytest.mark.asyncio
async def test_protected_route_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/pipelines/kpis")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
