"""SQLAlchemy ORM models for Vortex access/plans/quotas.

Schema per CONTRACT — Phase 0 Postgres Docker implementation:
  users, quota_limits, usage_counters, usage_events, admin_audit
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── users ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(
        String(50), nullable=False, default="free", server_default=text("'free'"),
    )
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()"),
    )

    __table_args__ = (
        CheckConstraint(
            "plan IN ('owner', 'free', 'pro', 'creator', 'blocked')",
            name="ck_users_plan_valid",
        ),
    )


# ── quota_limits ─────────────────────────────────────────────────────────────

class QuotaLimit(Base):
    __tablename__ = "quota_limits"

    plan: Mapped[str] = mapped_column(String(50), nullable=False)
    cost_class: Mapped[str] = mapped_column(String(100), nullable=False)
    period: Mapped[str] = mapped_column(
        String(20), nullable=False, default="daily", server_default=text("'daily'"),
    )
    limit_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("plan", "cost_class"),
        CheckConstraint(
            "plan IN ('owner', 'free', 'pro', 'creator', 'blocked')",
            name="ck_quota_limits_plan_valid",
        ),
        CheckConstraint("period = 'daily'", name="ck_quota_limits_period_daily"),
    )


# ── usage_counters (transactional quota bookkeeping) ─────────────────────────

class UsageCounter(Base):
    """Pre-aggregated counter per (user, cost_class, calendar-day window).

    The transactional quota check works as:
        BEGIN
        SELECT ... FOR UPDATE (locks the row for this user/cost_class/window)
        if used_count >= quota limit → ROLLBACK
        UPDATE used_count += 1
        COMMIT
    """

    __tablename__ = "usage_counters"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_class: Mapped[str] = mapped_column(String(100), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()"),
    )

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "cost_class", "window_start"),
    )


# ── usage_events (immutable event log) ───────────────────────────────────────

class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=False, index=True)
    cost_class: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    platform: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_url_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()"),
    )


# ── admin_audit (append-only admin action log) ───────────────────────────────

class AdminAudit(Base):
    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    target_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    old_plan: Mapped[str | None] = mapped_column(String(50), nullable=True)
    new_plan: Mapped[str] = mapped_column(String(50), nullable=False)
    duration: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("now()"),
    )
