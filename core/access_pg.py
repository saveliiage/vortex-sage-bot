"""Postgres-ready access control, plans, quotas, and usage events for Vortex.

Replaces SQLite prototype (core/access.py) with SQLAlchemy ORM — engine-agnostic
(Postgres in production, SQLite for local tests).  Follows CONTRACT — Phase 0
Postgres Docker implementation exactly.

Key behaviors:
  - owner bypass (unlimited, tracked as events but never rejected)
  - plans: owner, free, pro, creator, blocked
  - daily quotas per cost_class via transactional usage_counters
  - blocked plan rejects all actions
  - /admin_plan with duration and audit trail
  - concurrency-safe: SELECT ... FOR UPDATE / BEGIN IMMEDIATE (SQLite)
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from core.models import AdminAudit, Base, QuotaLimit, UsageCounter, UsageEvent, User

VALID_PLANS = {"owner", "free", "pro", "creator", "blocked"}


class QuotaExceeded(Exception):
    """Raised when a non-owner user exceeds an action quota."""

    def __init__(self, *, plan: str, action: str, limit: int, used: int) -> None:
        self.plan = plan
        self.action = action
        self.limit = limit
        self.used = used
        super().__init__(f"quota exceeded: plan={plan} action={action} used={used}/{limit}")


# ── helpers ──────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today_start(now: datetime | None = None) -> datetime:
    current = now or _utcnow()
    return current.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_duration(duration: str | None, *, now: datetime | None = None) -> datetime | None:
    """Parse a duration string like '30d', '12h', '2w', '3m', '1y' into expiry datetime."""
    if not duration:
        return None
    duration = duration.strip().lower()
    if duration in {"forever", "permanent", "none", "0"}:
        return None
    base = now or _utcnow()

    unit_map = {"d": "days", "w": "weeks", "m": "months", "y": "years", "h": "hours"}
    for suffix, kwarg in unit_map.items():
        if duration.endswith(suffix) and duration[:-1].isdigit():
            value = int(duration[:-1])
            if kwarg == "months":
                # Approximate: 1 month = 30 days for simplicity
                return base + timedelta(days=value * 30)
            if kwarg == "years":
                return base + timedelta(days=value * 365)
            return base + timedelta(**{kwarg: value})

    raise ValueError("duration must be like 30d, 12h, 2w, 3m, 1y, or omitted")


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:64]


# ── AccessStore ──────────────────────────────────────────────────────────────


class AccessStore:
    """SQLAlchemy-backed access control for plans, quotas, and usage events.

    Engine-agnostic: works with SQLite (local dev/test) and PostgreSQL (production).
    """

    def __init__(self, engine: Engine, *, owner_ids: Iterable[int] = ()) -> None:
        self.engine = engine
        self.owner_ids = {int(x) for x in owner_ids if int(x)}
        # Thread-local lock dict for SQLite serialization (Postgres uses row-level locks)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    def _get_lock(self, key: str) -> threading.Lock:
        with self._locks_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    # ── users ────────────────────────────────────────────────────────────────

    def ensure_user(self, *, telegram_id: int, username: str | None = None) -> dict[str, Any]:
        plan = "owner" if int(telegram_id) in self.owner_ids else "free"
        now = _utcnow()
        with Session(self.engine) as session:
            user = session.get(User, int(telegram_id))
            if user is None:
                user = User(
                    telegram_id=int(telegram_id),
                    username=username,
                    plan=plan,
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
            else:
                if username is not None:
                    user.username = username
                # Owner IDs always get owner plan on ensure
                if plan == "owner":
                    user.plan = "owner"
                user.updated_at = now
            session.commit()
            return _user_dict(user)

    def get_user(self, telegram_id: int) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            user = session.get(User, int(telegram_id))
            return _user_dict(user) if user else None

    # ── plans ────────────────────────────────────────────────────────────────

    def set_plan(
        self, *, telegram_id: int, plan: str, duration: str | None = None, actor_id: int,
    ) -> dict[str, Any]:
        if plan not in VALID_PLANS:
            raise ValueError(f"invalid plan: {plan}")
        now = _utcnow()
        expires = _parse_duration(duration, now=now)

        with Session(self.engine) as session:
            user = session.get(User, int(telegram_id))
            old_plan = user.plan if user else None

            if user is None:
                user = User(
                    telegram_id=int(telegram_id),
                    plan=plan,
                    plan_expires_at=expires,
                    created_at=now,
                    updated_at=now,
                )
                session.add(user)
            else:
                user.plan = plan
                user.plan_expires_at = expires
                user.updated_at = now

            audit = AdminAudit(
                actor_telegram_id=int(actor_id),
                target_telegram_id=int(telegram_id),
                old_plan=old_plan,
                new_plan=plan,
                duration=duration,
                expires_at=expires,
                created_at=now,
            )
            session.add(audit)
            session.commit()
            return _user_dict(user)

    # ── quotas ───────────────────────────────────────────────────────────────

    def set_quota(self, plan: str, action: str, *, period: str, limit: int) -> None:
        if plan not in VALID_PLANS:
            raise ValueError(f"invalid plan: {plan}")
        if period != "daily":
            raise ValueError("only daily quotas are implemented in Phase 0")

        with Session(self.engine) as session:
            ql = session.query(QuotaLimit).filter_by(plan=plan, cost_class=action).first()
            if ql is None:
                ql = QuotaLimit(plan=plan, cost_class=action, period=period, limit_count=int(limit))
                session.add(ql)
            else:
                ql.limit_count = int(limit)
            session.commit()

    # ── quota check + record (transactional) ─────────────────────────────────

    def check_and_record(
        self, telegram_id: int, action: str,
        *, platform: str | None = None, source_url: str | None = None, job_id: str | None = None,
    ) -> dict[str, Any]:
        user = self.get_user(telegram_id) or self.ensure_user(telegram_id=telegram_id)
        plan = user["plan"]

        if plan == "blocked":
            raise QuotaExceeded(plan=plan, action=action, limit=0, used=0)

        now = _utcnow()
        window_start = _today_start(now)
        url_hash = _url_hash(source_url) if source_url else None

        if plan == "owner":
            # Owner: record event without quota check (unlimited)
            with Session(self.engine) as session:
                event = UsageEvent(
                    user_id=int(telegram_id),
                    cost_class=action,
                    action=action,
                    platform=platform,
                    source_url_hash=url_hash,
                    job_id=job_id,
                    created_at=now,
                )
                session.add(event)
                session.commit()
            return {"allowed": True, "plan": plan, "limit": None, "used": None, "remaining": None}

        # Non-owner: transactional quota check
        return self._transactional_quota_check(
            telegram_id=int(telegram_id),
            plan=plan,
            action=action,
            window_start=window_start,
            now=now,
            platform=platform,
            url_hash=url_hash,
            job_id=job_id,
        )

    def _transactional_quota_check(
        self,
        telegram_id: int,
        plan: str,
        action: str,
        window_start: datetime,
        now: datetime,
        platform: str | None = None,
        url_hash: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Perform quota check + increment in a single transaction with row-level locking.

        For SQLite: uses thread-level lock + BEGIN IMMEDIATE to serialize.
        For Postgres: uses SELECT ... FOR UPDATE for true row-level locking.
        """
        is_sqlite = str(self.engine.url).startswith("sqlite")

        if is_sqlite:
            # SQLite: global lock per (telegram_id, action) pair
            lock_key = f"{telegram_id}:{action}"
            lock = self._get_lock(lock_key)
            with lock:
                return self._do_quota_tx(
                    telegram_id, plan, action, window_start, now,
                    platform, url_hash, job_id,
                )
        else:
            # Postgres: rely on SELECT ... FOR UPDATE
            return self._do_quota_tx(
                telegram_id, plan, action, window_start, now,
                platform, url_hash, job_id,
            )

    def _do_quota_tx(
        self,
        telegram_id: int,
        plan: str,
        action: str,
        window_start: datetime,
        now: datetime,
        platform: str | None,
        url_hash: str | None,
        job_id: str | None,
    ) -> dict[str, Any]:
        """The actual transactional quota check — always inside a lock/session."""
        is_sqlite = str(self.engine.url).startswith("sqlite")

        with Session(self.engine) as session:
            if is_sqlite:
                session.execute(text("BEGIN IMMEDIATE"))

            # 1. Look up quota limit for this plan/action
            ql = (
                session.query(QuotaLimit)
                .filter_by(plan=plan, cost_class=action)
                .first()
            )
            if ql is None:
                session.rollback()
                raise QuotaExceeded(plan=plan, action=action, limit=0, used=0)

            limit = ql.limit_count
            if limit == 0:
                session.rollback()
                raise QuotaExceeded(plan=plan, action=action, limit=0, used=0)

            # 2. Lock or upsert counter
            if is_sqlite:
                # SQLite doesn't do SELECT ... FOR UPDATE well — covered by thread lock
                counter = (
                    session.query(UsageCounter)
                    .filter_by(user_id=telegram_id, cost_class=action, window_start=window_start)
                    .first()
                )
            else:
                counter = (
                    session.query(UsageCounter)
                    .with_for_update()
                    .filter_by(user_id=telegram_id, cost_class=action, window_start=window_start)
                    .first()
                )

            if counter is None:
                counter = UsageCounter(
                    user_id=telegram_id,
                    cost_class=action,
                    window_start=window_start,
                    used_count=0,
                )
                session.add(counter)
                session.flush()

            # 3. Check quota
            if counter.used_count >= limit:
                session.rollback()
                raise QuotaExceeded(
                    plan=plan, action=action, limit=limit, used=counter.used_count,
                )

            # 4. Increment + record event
            counter.used_count += 1
            counter.last_used_at = now

            event = UsageEvent(
                user_id=telegram_id,
                cost_class=action,
                action=action,
                units=1,
                platform=platform,
                source_url_hash=url_hash,
                job_id=job_id,
                created_at=now,
            )
            session.add(event)
            session.commit()

            used_after = counter.used_count
            return {
                "allowed": True,
                "plan": plan,
                "limit": limit,
                "used": used_after,
                "remaining": limit - used_after,
            }


# ── serialization helper ────────────────────────────────────────────────────


def _user_dict(user: User) -> dict[str, Any]:
    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "plan": user.plan,
        "plan_expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }
