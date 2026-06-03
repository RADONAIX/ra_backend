"""Pydantic schemas for the assurance module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Allowed enums — kept in sync with the DB CHECK constraints on `cases`.
CaseSeverity = Literal["low", "medium", "high", "critical"]
CaseStatus = Literal["Open", "In Progress", "Resolved", "Closed", "Cancelled"]


# --- Reconciliation (read from ClickHouse) ---------------------------------
class ReconSummary(BaseModel):
    total: int
    matched: int
    amountMismatch: int
    rawOnly: int
    procOnly: int
    matchRate: float
    estimatedLeakage: float


class ReconRecord(BaseModel):
    recordType: str | None = None
    txnId: str | None = None
    nodeId: str | None = None
    subscriberNum: str | None = None
    rawAmount: float | None = None
    procAmount: float | None = None
    rawBalance: float | None = None
    procBalance: float | None = None
    status: str
    createdTime: datetime | None = None


# --- Cases -----------------------------------------------------------------
class CaseRow(BaseModel):
    id: str
    reference: str
    title: str
    severity: str
    status: str
    owner: str | None = None
    updated: datetime
    estimatedImpact: float | None = None


class CaseComment(BaseModel):
    id: str
    author: str
    body: str
    createdAt: datetime


class CaseDetail(CaseRow):
    description: str
    linkedTxnId: str | None = None
    comments: list[CaseComment]


class CaseCreate(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    severity: CaseSeverity = "medium"
    status: CaseStatus = "Open"
    owner: str | None = None
    linkedTxnId: str | None = None
    estimatedImpact: float | None = None


class CaseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    severity: CaseSeverity | None = None
    status: CaseStatus | None = None
    owner: str | None = None
    estimatedImpact: float | None = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)


# --- Workbench saved queries -----------------------------------------------
class SavedQueryRow(BaseModel):
    id: str
    reference: str
    name: str
    owner: str | None = None
    count: int


class SavedQueryCreate(BaseModel):
    name: str = Field(min_length=1)
    definition: dict = Field(default_factory=dict)


class WorkbenchStats(BaseModel):
    openInvestigations: int
    closedThisWeek: int
    avgResolutionDays: float
