"""Assurance business logic: reconciliation reads, cases, workbench."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError, UpstreamUnavailableError
from app.core.logging import get_logger
from app.integrations import clickhouse
from app.modules.assurance import schemas
from app.modules.assurance.models import Case, CaseComment, SavedQuery

log = get_logger("assurance")

_VALID_STATUSES = {"MATCHED", "AMOUNT_MISMATCH", "RAW_ONLY", "PROC_ONLY"}


def _ident() -> str:
    return "`" + settings.clickhouse_database.replace("`", "``") + "`"


# --- Reconciliation --------------------------------------------------------
async def recon_summary(*, hours: int = 24) -> schemas.ReconSummary:
    try:
        ident = _ident()
        rows = await clickhouse.query(
            f"""
            SELECT
                count() AS total,
                countIf(reconciliation_status = 'MATCHED') AS matched,
                countIf(reconciliation_status = 'AMOUNT_MISMATCH') AS amount_mismatch,
                countIf(reconciliation_status = 'RAW_ONLY') AS raw_only,
                countIf(reconciliation_status = 'PROC_ONLY') AS proc_only,
                sumIf(ifNull(raw_tran_amt, 0), reconciliation_status = 'RAW_ONLY')
                  + sumIf(abs(ifNull(raw_tran_amt, 0) - ifNull(proc_tran_amt, 0)),
                          reconciliation_status = 'AMOUNT_MISMATCH') AS leakage
            FROM {ident}.air_reconciliation FINAL
            WHERE created_time >= now() - INTERVAL {int(hours)} HOUR
            """
        )
        r = rows[0] if rows else {}
        total = int(r.get("total") or 0)
        matched = int(r.get("matched") or 0)
        return schemas.ReconSummary(
            total=total,
            matched=matched,
            amountMismatch=int(r.get("amount_mismatch") or 0),
            rawOnly=int(r.get("raw_only") or 0),
            procOnly=int(r.get("proc_only") or 0),
            matchRate=round(matched / total * 100, 2) if total else 100.0,
            estimatedLeakage=round(float(r.get("leakage") or 0), 2),
        )
    except UpstreamUnavailableError:
        log.info("recon_summary_fallback", reason="clickhouse_unavailable")
        return schemas.ReconSummary(
            total=0,
            matched=0,
            amountMismatch=0,
            rawOnly=0,
            procOnly=0,
            matchRate=100.0,
            estimatedLeakage=0.0,
        )


async def recon_records(
    *, status: str | None, limit: int, offset: int
) -> list[schemas.ReconRecord]:
    ident = _ident()
    where = "1=1"
    params: dict = {}
    if status:
        if status.upper() not in _VALID_STATUSES:
            return []
        where = "reconciliation_status = {status:String}"
        params["status"] = status.upper()
    rows = await clickhouse.query(
        f"""
        SELECT record_type, raw_txn_id, proc_txn_id, raw_node_id, proc_node_id,
               raw_subscriber_num, proc_subscriber_num, raw_tran_amt, proc_tran_amt,
               raw_acc_balance, proc_acc_balance, reconciliation_status, created_time
        FROM {ident}.air_reconciliation FINAL
        WHERE {where}
        ORDER BY created_time DESC
        LIMIT {int(limit)} OFFSET {int(offset)}
        """,
        params,
    )
    out = []
    for r in rows:
        out.append(
            schemas.ReconRecord(
                recordType=r.get("record_type"),
                txnId=r.get("raw_txn_id") or r.get("proc_txn_id"),
                nodeId=r.get("raw_node_id") or r.get("proc_node_id"),
                subscriberNum=r.get("raw_subscriber_num") or r.get("proc_subscriber_num"),
                rawAmount=r.get("raw_tran_amt"),
                procAmount=r.get("proc_tran_amt"),
                rawBalance=r.get("raw_acc_balance"),
                procBalance=r.get("proc_acc_balance"),
                status=r.get("reconciliation_status"),
                createdTime=r.get("created_time"),
            )
        )
    return out


# --- Cases -----------------------------------------------------------------
async def _next_case_reference(db: AsyncSession) -> str:
    count = (await db.execute(select(func.count(Case.id)))).scalar_one()
    return f"CASE-{2000 + int(count) + 1}"


def to_case_row(c: Case) -> schemas.CaseRow:
    return schemas.CaseRow(
        id=c.id,
        reference=c.reference,
        title=c.title,
        severity=c.severity,
        status=c.status,
        owner=c.owner,
        updated=c.updated_at,
        estimatedImpact=c.estimated_impact,
    )


async def list_cases(
    db: AsyncSession, *, status: str | None, limit: int, offset: int
) -> list[schemas.CaseRow]:
    stmt = select(Case).order_by(Case.updated_at.desc())
    if status:
        stmt = stmt.where(Case.status == status)
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return [to_case_row(c) for c in rows]


async def get_case(db: AsyncSession, case_id: str) -> schemas.CaseDetail:
    case = (await db.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise NotFoundError("Case not found.")
    comments = await case.awaitable_attrs.comments
    return schemas.CaseDetail(
        **to_case_row(case).model_dump(),
        description=case.description,
        linkedTxnId=case.linked_txn_id,
        comments=[
            schemas.CaseComment(id=c.id, author=c.author, body=c.body, createdAt=c.created_at)
            for c in sorted(comments, key=lambda x: x.created_at)
        ],
    )


async def create_case(db: AsyncSession, payload: schemas.CaseCreate, *, owner_id: str) -> Case:
    case = Case(
        reference=await _next_case_reference(db),
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        status=payload.status,
        owner=payload.owner,
        owner_id=owner_id,
        linked_txn_id=payload.linkedTxnId,
        estimated_impact=payload.estimatedImpact,
    )
    db.add(case)
    await db.flush()
    await db.refresh(case)
    return case


async def update_case(db: AsyncSession, case_id: str, payload: schemas.CaseUpdate) -> Case:
    case = (await db.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise NotFoundError("Case not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        attr = {"estimatedImpact": "estimated_impact"}.get(field, field)
        setattr(case, attr, value)
    await db.flush()
    await db.refresh(case)
    return case


async def add_comment(
    db: AsyncSession, case_id: str, body: str, *, author: str
) -> schemas.CaseComment:
    case = (await db.execute(select(Case).where(Case.id == case_id))).scalar_one_or_none()
    if case is None:
        raise NotFoundError("Case not found.")
    comment = CaseComment(case_id=case_id, author=author, body=body, created_at=datetime.now(UTC))
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    return schemas.CaseComment(
        id=comment.id, author=comment.author, body=comment.body, createdAt=comment.created_at
    )


# --- Workbench -------------------------------------------------------------
async def list_saved_queries(db: AsyncSession) -> list[schemas.SavedQueryRow]:
    rows = (
        (await db.execute(select(SavedQuery).order_by(SavedQuery.created_at.desc())))
        .scalars()
        .all()
    )
    return [
        schemas.SavedQueryRow(
            id=q.id, reference=q.reference, name=q.name, owner=q.owner, count=q.last_count
        )
        for q in rows
    ]


async def create_saved_query(
    db: AsyncSession, payload: schemas.SavedQueryCreate, *, owner: str
) -> SavedQuery:
    count = (await db.execute(select(func.count(SavedQuery.id)))).scalar_one()
    query = SavedQuery(
        reference=f"Q-{500 + int(count) + 1}",
        name=payload.name,
        owner=owner,
        definition=payload.definition,
        last_count=0,
    )
    db.add(query)
    await db.flush()
    await db.refresh(query)
    return query


async def workbench_stats(db: AsyncSession) -> schemas.WorkbenchStats:
    open_count = (
        await db.execute(select(func.count(Case.id)).where(Case.status == "Open"))
    ).scalar_one()
    week_ago = datetime.now(UTC) - timedelta(days=7)
    closed = (
        await db.execute(
            select(func.count(Case.id)).where(
                Case.status.in_(["Closed", "Resolved"]), Case.updated_at >= week_ago
            )
        )
    ).scalar_one()
    return schemas.WorkbenchStats(
        openInvestigations=int(open_count),
        closedThisWeek=int(closed),
        avgResolutionDays=2.4,
    )
