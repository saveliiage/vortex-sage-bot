"""Access control, plans, quotas, and usage events for Vortex.

This is intentionally framework-free so Telegram handlers can use it and tests can
exercise real SQLite behavior without bot tokens or network calls.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

VALID_PLANS = {"owner", "free", "pro", "creator", "blocked"}


class QuotaExceeded(Exception):
    """Raised when a non-owner user exceeds an action quota."""

    def __init__(self, *, plan: str, action: str, limit: int, used: int) -> None:
        self.plan = plan
        self.action = action
        self.limit = limit
        self.used = used
        super().__init__(f"quota exceeded: plan={plan} action={action} used={used}/{limit}")


@dataclass(frozen=True)
class QuotaWindow:
    start: str | None
    end: str | None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat() if dt else None


def _parse_duration(duration: str | None, *, now: datetime | None = None) -> str | None:
    if not duration:
        return None
    duration = duration.strip().lower()
    if duration in {"forever", "permanent", "none", "0"}:
        return None
    if duration.endswith("d") and duration[:-1].isdigit():
        base = now or _utcnow()
        return _iso(base + timedelta(days=int(duration[:-1])))
    if duration.endswith("h") and duration[:-1].isdigit():
        base = now or _utcnow()
        return _iso(base + timedelta(hours=int(duration[:-1])))
    raise ValueError("duration must be like 30d, 12h, forever, or omitted")


def _rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class AccessStore:
    """SQLite-backed users/plans/quotas store."""

    def __init__(self, db_path: str | Path, *, owner_ids: Iterable[int] = ()) -> None:
        self.db_path = Path(db_path)
        self.owner_ids = {int(x) for x in owner_ids if int(x)}
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists users (
                    telegram_id integer primary key,
                    username text,
                    plan text not null default 'free',
                    plan_expires_at text,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists quotas (
                    plan text not null,
                    action text not null,
                    period text not null,
                    limit_count integer not null,
                    primary key (plan, action)
                );

                create table if not exists usage_events (
                    id integer primary key autoincrement,
                    telegram_id integer not null,
                    action text not null,
                    plan text not null,
                    created_at text not null
                );

                create table if not exists admin_audit (
                    id integer primary key autoincrement,
                    actor_id integer not null,
                    target_telegram_id integer not null,
                    old_plan text,
                    new_plan text not null,
                    duration text,
                    created_at text not null
                );
                """
            )
            # Conservative defaults for first public-core implementation.
            defaults = [
                ("free", "llm_summary", "daily", 3),
                ("free", "media_download", "daily", 10),
                ("free", "media_convert", "daily", 5),
                ("free", "apify", "daily", 0),
                ("pro", "llm_summary", "daily", 30),
                ("pro", "media_download", "daily", 100),
                ("pro", "media_convert", "daily", 50),
                ("pro", "apify", "daily", 10),
                ("creator", "llm_summary", "daily", 100),
                ("creator", "media_download", "daily", 300),
                ("creator", "media_convert", "daily", 150),
                ("creator", "apify", "daily", 50),
            ]
            conn.executemany(
                "insert or ignore into quotas(plan, action, period, limit_count) values (?, ?, ?, ?)",
                defaults,
            )

    def ensure_user(self, *, telegram_id: int, username: str | None = None) -> dict[str, Any]:
        plan = "owner" if int(telegram_id) in self.owner_ids else "free"
        now = _iso(_utcnow())
        with self.connect() as conn:
            conn.execute(
                """
                insert into users(telegram_id, username, plan, created_at, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(telegram_id) do update set
                    username=coalesce(excluded.username, users.username),
                    plan=case when excluded.plan='owner' then 'owner' else users.plan end,
                    updated_at=excluded.updated_at
                """,
                (int(telegram_id), username, plan, now, now),
            )
            return _rowdict(conn.execute("select * from users where telegram_id=?", (int(telegram_id),)).fetchone())  # type: ignore[return-value]

    def get_user(self, telegram_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            return _rowdict(conn.execute("select * from users where telegram_id=?", (int(telegram_id),)).fetchone())

    def set_plan(self, *, telegram_id: int, plan: str, duration: str | None = None, actor_id: int) -> dict[str, Any]:
        if plan not in VALID_PLANS:
            raise ValueError(f"invalid plan: {plan}")
        now = _iso(_utcnow())
        expires = _parse_duration(duration)
        with self.connect() as conn:
            before = _rowdict(conn.execute("select * from users where telegram_id=?", (int(telegram_id),)).fetchone())
            if before is None:
                conn.execute(
                    "insert into users(telegram_id, plan, plan_expires_at, created_at, updated_at) values (?, ?, ?, ?, ?)",
                    (int(telegram_id), plan, expires, now, now),
                )
                old_plan = None
            else:
                old_plan = before["plan"]
                conn.execute(
                    "update users set plan=?, plan_expires_at=?, updated_at=? where telegram_id=?",
                    (plan, expires, now, int(telegram_id)),
                )
            conn.execute(
                "insert into admin_audit(actor_id, target_telegram_id, old_plan, new_plan, duration, created_at) values (?, ?, ?, ?, ?, ?)",
                (int(actor_id), int(telegram_id), old_plan, plan, duration, now),
            )
            return _rowdict(conn.execute("select * from users where telegram_id=?", (int(telegram_id),)).fetchone())  # type: ignore[return-value]

    def set_quota(self, plan: str, action: str, *, period: str, limit: int) -> None:
        if plan not in VALID_PLANS:
            raise ValueError(f"invalid plan: {plan}")
        if period != "daily":
            raise ValueError("only daily quotas are implemented in Phase 0")
        with self.connect() as conn:
            conn.execute(
                "insert or replace into quotas(plan, action, period, limit_count) values (?, ?, ?, ?)",
                (plan, action, period, int(limit)),
            )

    def _daily_window(self, now: datetime | None = None) -> QuotaWindow:
        current = now or _utcnow()
        start = current.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return QuotaWindow(start=_iso(start), end=_iso(end))

    def check_and_record(self, telegram_id: int, action: str) -> dict[str, Any]:
        user = self.get_user(telegram_id) or self.ensure_user(telegram_id=telegram_id)
        plan = user["plan"]
        if plan == "blocked":
            raise QuotaExceeded(plan=plan, action=action, limit=0, used=0)
        now = _iso(_utcnow())
        with self.connect() as conn:
            if plan == "owner":
                conn.execute(
                    "insert into usage_events(telegram_id, action, plan, created_at) values (?, ?, ?, ?)",
                    (int(telegram_id), action, plan, now),
                )
                return {"allowed": True, "plan": plan, "limit": None, "used": None, "remaining": None}

            quota = conn.execute(
                "select * from quotas where plan=? and action=?",
                (plan, action),
            ).fetchone()
            if quota is None:
                raise QuotaExceeded(plan=plan, action=action, limit=0, used=0)
            window = self._daily_window()
            used = conn.execute(
                """
                select count(*) from usage_events
                where telegram_id=? and action=? and created_at>=? and created_at<?
                """,
                (int(telegram_id), action, window.start, window.end),
            ).fetchone()[0]
            limit = int(quota["limit_count"])
            if used >= limit:
                raise QuotaExceeded(plan=plan, action=action, limit=limit, used=used)
            conn.execute(
                "insert into usage_events(telegram_id, action, plan, created_at) values (?, ?, ?, ?)",
                (int(telegram_id), action, plan, now),
            )
            used_after = used + 1
            return {
                "allowed": True,
                "plan": plan,
                "limit": limit,
                "used": used_after,
                "remaining": limit - used_after,
            }
