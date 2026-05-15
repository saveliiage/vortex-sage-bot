from __future__ import annotations

import sqlite3
from pathlib import Path

from core.access import AccessStore, QuotaExceeded


def test_owner_user_bypasses_quota(tmp_path: Path) -> None:
    store = AccessStore(tmp_path / "vortex.db", owner_ids={42})

    user = store.ensure_user(telegram_id=42, username="sava")
    allowed = [store.check_and_record(42, "llm_summary") for _ in range(5)]

    assert user["plan"] == "owner"
    assert all(item["allowed"] for item in allowed)
    assert allowed[-1]["remaining"] is None


def test_free_user_gets_daily_llm_summary_quota(tmp_path: Path) -> None:
    store = AccessStore(tmp_path / "vortex.db", owner_ids={42})
    store.set_quota("free", "llm_summary", period="daily", limit=2)

    user = store.ensure_user(telegram_id=1001, username="alpha")
    first = store.check_and_record(1001, "llm_summary")
    second = store.check_and_record(1001, "llm_summary")

    assert user["plan"] == "free"
    assert first == {"allowed": True, "plan": "free", "limit": 2, "used": 1, "remaining": 1}
    assert second == {"allowed": True, "plan": "free", "limit": 2, "used": 2, "remaining": 0}

    try:
        store.check_and_record(1001, "llm_summary")
    except QuotaExceeded as exc:
        assert exc.plan == "free"
        assert exc.action == "llm_summary"
        assert exc.limit == 2
        assert exc.used == 2
    else:
        raise AssertionError("expected QuotaExceeded")


def test_admin_plan_sets_expiry(tmp_path: Path) -> None:
    store = AccessStore(tmp_path / "vortex.db", owner_ids={42})
    store.ensure_user(telegram_id=1001, username="alpha")

    updated = store.set_plan(telegram_id=1001, plan="pro", duration="30d", actor_id=42)
    reloaded = store.get_user(1001)

    assert updated["plan"] == "pro"
    assert reloaded["plan"] == "pro"
    assert reloaded["plan_expires_at"] is not None

    conn = sqlite3.connect(tmp_path / "vortex.db")
    audit = conn.execute("select actor_id, target_telegram_id, new_plan from admin_audit").fetchall()
    assert audit == [(42, 1001, "pro")]
