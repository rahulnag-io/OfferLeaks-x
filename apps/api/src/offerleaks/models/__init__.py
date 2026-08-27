"""ORM models.

Importing every model here registers it on `Base.metadata`, which is what
Alembic's `env.py` imports to drive autogenerate. Models are the only
layer that should import from `offerleaks.core.db` directly among the
service/repository/router layers -- see architecture.md §0.3.
"""

from offerleaks.models.analysis import Analysis, AnalysisStatus, Verdict
from offerleaks.models.company import (
    Company,
    CompanySignal,
    CompanyVerificationStatus,
    ProviderCheckOutcome,
)
from offerleaks.models.credit import CreditBalance, CreditTransaction, CreditTransactionType
from offerleaks.models.plan import Plan, PlanEntitlement
from offerleaks.models.report import (
    Report,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)
from offerleaks.models.scam_pattern import ScamPattern, ScamPatternSeverity
from offerleaks.models.subscription import Subscription, SubscriptionStatus
from offerleaks.models.usage_ledger import UsageLedgerEntry
from offerleaks.models.user import OAuthProvider, Role, User
from offerleaks.models.webhook_event import WebhookEvent

__all__ = [
    "Analysis",
    "AnalysisStatus",
    "Company",
    "CompanySignal",
    "CompanyVerificationStatus",
    "ProviderCheckOutcome",
    "CreditBalance",
    "CreditTransaction",
    "CreditTransactionType",
    "OAuthProvider",
    "Plan",
    "PlanEntitlement",
    "Report",
    "ReportReason",
    "ReportStatus",
    "ReportTargetType",
    "Role",
    "ScamPattern",
    "ScamPatternSeverity",
    "Subscription",
    "SubscriptionStatus",
    "UsageLedgerEntry",
    "User",
    "Verdict",
    "WebhookEvent",
]
