"""Unit tests for the bulk-export query builders (pure, no I/O) + the
EXPORTS_ENABLED gate."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from app.modules.reporting import service as reporting


def test_get_report_unknown():
    assert reporting.get_report("nope") is None
    assert reporting.get_report("air_reconciliation") is not None


def test_export_query_without_dates_is_unfiltered():
    source, sql, params = reporting.export_query("air_reconciliation")
    assert source == "clickhouse"
    assert params == {}
    assert "WHERE reconciliation_status != 'MATCHED'" in sql
    assert "LIMIT" not in sql.upper()


def test_export_query_clickhouse_date_filter():
    d0, d1 = dt.date(2026, 1, 1), dt.date(2026, 2, 1)
    source, sql, params = reporting.export_query(
        "air_reconciliation", date_from=d0, date_to=d1
    )
    assert source == "clickhouse"
    assert params == {"date_from": d0, "date_to": d1}
    # wrapped in a subquery + ClickHouse param + Date typing
    assert "AS _e WHERE" in sql
    assert "toDate(_e.created_time) >= {date_from:Date}" in sql
    assert "toDate(_e.created_time) < {date_to:Date}" in sql


def test_export_query_bi_pg_date_filter():
    d0, d1 = dt.date(2026, 1, 1), dt.date(2026, 2, 1)
    source, sql, params = reporting.export_query(
        "file_sequence_check", date_from=d0, date_to=d1
    )
    assert source == "bi_pg"
    assert params == {"date_from": d0, "date_to": d1}
    assert "_e.date::date >= :date_from" in sql
    assert "_e.date::date < :date_to" in sql


def test_count_and_kpi_wrap_the_export_select():
    d0, d1 = dt.date(2026, 1, 1), dt.date(2026, 2, 1)
    _, csql, _ = reporting.count_query("air_reconciliation", date_from=d0, date_to=d1)
    assert csql.startswith("SELECT count(*) AS n FROM (")
    _, ksql, _ = reporting.kpi_query("air_reconciliation", date_from=d0, date_to=d1)
    assert "countIf(reconciliation_status = 'AMOUNT_MISMATCH')" in ksql
    assert "FROM (" in ksql and ") AS _k" in ksql


@pytest.mark.asyncio
async def test_exports_routes_503_when_disabled(monkeypatch):
    """With EXPORTS_ENABLED=false the whole /exports module returns 503."""
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "exports_enabled", False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/exports")
        created = await client.post("/api/exports", json={})
    for resp in (listed, created):
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "exports_disabled"
