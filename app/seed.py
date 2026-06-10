"""Idempotent database seeding.

Creates the four RBAC roles (with permission matrices matching the UI),
the demo user accounts the UI ships with, the default decoders, the singleton
system config and a few representative pipeline alerts.

Run with:  python -m app.seed
Safe to run repeatedly — existing rows are left untouched.

Demo account passwords default to ``DEMO_PASSWORD`` env (fallback below);
change them in any real deployment.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionFactory
from app.core.logging import configure_logging, get_logger
from app.core.rbac import ROLE_LABELS, RoleSlug, default_permissions_for
from app.core.security import hash_password
from app.modules.identity.models import Role, User
from app.modules.operations.models import Decoder, PipelineAlert, SystemConfig

log = get_logger("seed")

DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "ChangeMe!123")


_ROLES = [
    (RoleSlug.ADMIN, "Full platform access including user and role management.", "Active"),
    (RoleSlug.RA_LEAD, "Oversees assurance operations, pipelines, reports and cases.", "Active"),
    (RoleSlug.ANALYST, "Investigates leakage cases and works the assurance workbench.", "Active"),
    (RoleSlug.VIEWER, "Read-only access to dashboards, reports and pipelines.", "Active"),
]

# Only the real admin account is seeded. Demo users were removed — do not
# re-add them (production runs with a single bootstrap admin).
_USERS = [
    (
        "Administrator",
        "admin@radonaix.io",
        "+1 415 555 0100",
        "Platform Ops",
        RoleSlug.ADMIN,
        "Active",
    ),
]

# Demo decoders / alerts removed — these tables stay empty until real rows are
# created at runtime (no hardcoded/dummy seed data).
_DECODERS: list[tuple[str, str, str, str, str]] = []

_ALERTS: list[tuple[str, str, str, str, str]] = []


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()


async def seed() -> None:
    async with SessionFactory() as db:
        # Roles
        for slug, desc, status in _ROLES:
            exists = (await db.execute(select(Role).where(Role.id == slug))).scalar_one_or_none()
            if exists is None:
                db.add(
                    Role(
                        id=slug,
                        name=ROLE_LABELS[slug],
                        description=desc,
                        status=status,
                        permissions=default_permissions_for(slug),
                        is_system=True,
                    )
                )
                log.info("seed_role", role=slug)
        await db.flush()

        # Users
        for full_name, email, phone, dept, role, status in _USERS:
            exists = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if exists is None:
                pwd = settings.bootstrap_admin_password if role == RoleSlug.ADMIN else DEMO_PASSWORD
                db.add(
                    User(
                        full_name=full_name,
                        email=email,
                        phone=phone,
                        department=dept,
                        role_id=role,
                        status=status,
                        avatar=_initials(full_name),
                        hashed_password=hash_password(pwd),
                    )
                )
                log.info("seed_user", email=email, role=role)

        # Decoders
        for did, name, version, status, throughput in _DECODERS:
            exists = (
                await db.execute(select(Decoder).where(Decoder.id == did))
            ).scalar_one_or_none()
            if exists is None:
                db.add(
                    Decoder(
                        id=did, name=name, version=version, status=status, throughput=throughput
                    )
                )

        # System config (singleton)
        cfg = (
            await db.execute(select(SystemConfig).where(SystemConfig.id == "system"))
        ).scalar_one_or_none()
        if cfg is None:
            db.add(
                SystemConfig(
                    id="system",
                    environment="production",
                    retention_days=365,
                    sla_minutes=15,
                    alert_email="ops-alerts@radonaix.io",
                    maintenance_mode=False,
                )
            )

        # Pipeline alerts
        for aid, severity, stage, message, status in _ALERTS:
            exists = (
                await db.execute(select(PipelineAlert).where(PipelineAlert.id == aid))
            ).scalar_one_or_none()
            if exists is None:
                db.add(
                    PipelineAlert(
                        id=aid,
                        severity=severity,
                        stage=stage,
                        message=message,
                        status=status,
                        created_at=datetime.now(UTC),
                    )
                )

        await db.commit()
    log.info("seed_complete")


def main() -> None:
    configure_logging(level=settings.log_level, json_logs=False)
    asyncio.run(seed())


if __name__ == "__main__":
    main()
