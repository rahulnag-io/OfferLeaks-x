"""Scam pattern library (M6: "the architectural shift that gets AI out of
being the entire detection engine" -- Revised_ARCHITECTURE.md M6).

A `ScamPattern` is a deterministic, human-authored rule: if any of its
`keywords` appears in a document's extracted text, the pattern is
considered matched. This runs in `services/rules_engine.py`, *alongside*
the AI call, never instead of it -- the AI verdict and the rules engine
are two independent signals that both feed the final `Verdict` row.

Deliberately simple (substring/keyword matching, not a rules DSL or a
separate regex engine) for the same reason architecture.md §0.1 gives for
avoiding early over-engineering: this is a v1 that a solo/small team can
read, extend, and reason about by adding rows, not a new subsystem to
maintain. `keywords` is a JSON list rather than a single regex column so
non-technical pattern authoring (e.g. via a future admin UI, V8) doesn't
require regex literacy.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base


class ScamPatternSeverity(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScamPattern(Base):
    __tablename__ = "scam_patterns"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )

    # Stable machine identifier (e.g. "upfront_processing_fee"), never
    # shown to the end user -- `title` is. Used as the join key wherever
    # a matched pattern is referenced (`Verdict.matched_patterns`,
    # entitlement/analytics keys later), so patterns can be edited or
    # retitled without breaking historical verdicts that reference them.
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)

    severity: Mapped[ScamPatternSeverity] = mapped_column(
        Enum(
            ScamPatternSeverity,
            name="scam_pattern_severity",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    # Case-insensitive substrings; a match on any one triggers this
    # pattern. list[str], JSON on Postgres via the generic JSON type
    # (same convention as `Verdict.red_flags`).
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # Inactive patterns are kept (not deleted) so historical verdicts
    # that reference them by `key` stay meaningful, but `RulesEngine`
    # never matches against them going forward.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
