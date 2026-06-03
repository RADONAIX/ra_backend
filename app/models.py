"""Aggregate import of all ORM models.

Importing this module ensures every table is registered on ``Base.metadata``
so Alembic autogenerate and ``create_all`` see the full schema.
"""

from app.core.database import Base
from app.modules.assurance.models import Case, CaseComment, SavedQuery
from app.modules.identity.models import AuditLog, Role, User, UserSession
from app.modules.operations.models import Decoder, PipelineAlert, SystemConfig
from app.modules.reporting.models import Report
from app.modules.rules.models import Rule, RuleRun

__all__ = [
    "Base",
    "Role",
    "User",
    "UserSession",
    "AuditLog",
    "Case",
    "CaseComment",
    "SavedQuery",
    "Decoder",
    "SystemConfig",
    "PipelineAlert",
    "Report",
    "Rule",
    "RuleRun",
]
