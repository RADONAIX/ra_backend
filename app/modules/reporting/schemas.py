"""Pydantic schemas for the reporting module (RA report catalog)."""

from __future__ import annotations

from pydantic import BaseModel


class ReportDetail(BaseModel):
    """A report's drill-down as a generic table (heterogeneous reports).

    ``rows`` is capped at 100 by the service; ``count`` is the true total."""

    key: str
    title: str
    count: int | None = None
    columns: list[str]
    rows: list[list]
