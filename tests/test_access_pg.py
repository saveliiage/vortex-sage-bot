"""test_access_pg — TDD: Postgres-backed AccessStore before implementation.

These tests MUST fail initially because the new AccessStore doesn't exist yet.
Run: pytest tests/test_access_pg.py -v
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sqlalchemy import create_engine

from core.access_pg import AccessStore, QuotaExceeded
from core.models import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── helpers ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine(tmp_path: Path):
    """File-based SQLite engine — works for single-thread and concurrent tests.

    In-memory SQLite (:memory:) is NOT shared across connections/threads, so
    we use a temp file for thread-safe test behavior.
    """
    db_path = tmp_path / "test.db"
    eng = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def store(engine):
    return AccessStore(engine=engine, owner_ids={42})


# ── RED: tests must fail until AccessStore is implemented ─────────────────────

class TestOwnerBypass:
    def test_owner_user_bypasses_quota_unlimited(self, store):
        user = store.ensure_user(telegram_id=42, username="sava")
        assert user["plan"] == "owner"

        allowed = [store.check_and_record(42, "llm_summary") for _ in range(50)]

        assert all(item["allowed"] for item in allowed)
        assert allowed[-1]["remaining"] is None  # owner = unlimited


class TestFreePlanQuotas:
    def test_free_user_gets_daily_quota_with_exact_counters(self, store):
        store.set_quota("free", "llm_summary", period="daily", limit=2)

        user = store.ensure_user(telegram_id=1001, username="alpha")
        assert user["plan"] == "free"

        first = store.check_and_record(1001, "llm_summary")
        second = store.check_and_record(1001, "llm_summary")

        assert first == {"allowed": True, "plan": "free", "limit": 2, "used": 1, "remaining": 1}
        assert second == {"allowed": True, "plan": "free", "limit": 2, "used": 2, "remaining": 0}

        with pytest.raises(QuotaExceeded) as excinfo:
            store.check_and_record(1001, "llm_summary")
        assert excinfo.value.plan == "free"
        assert excinfo.value.action == "llm_summary"
        assert excinfo.value.limit == 2
        assert excinfo.value.used == 2

    def test_zero_quota_action_always_rejects(self, store):
        store.set_quota("free", "apify", period="daily", limit=0)

        store.ensure_user(telegram_id=2001)
        with pytest.raises(QuotaExceeded):
            store.check_and_record(2001, "apify")


class TestBlockedPlan:
    def test_blocked_user_rejects_all_actions(self, store):
        store.ensure_user(telegram_id=3001)
        store.set_plan(telegram_id=3001, plan="blocked", actor_id=42)

        with pytest.raises(QuotaExceeded) as excinfo:
            store.check_and_record(3001, "llm_summary")
        assert excinfo.value.plan == "blocked"
        assert excinfo.value.limit == 0


class TestAdminPlanAndAudit:
    def test_admin_plan_sets_expiry_and_writes_audit(self, store):
        store.ensure_user(telegram_id=1001, username="alpha")
        updated = store.set_plan(telegram_id=1001, plan="pro", duration="30d", actor_id=42)
        reloaded = store.get_user(1001)

        assert updated["plan"] == "pro"
        assert reloaded["plan"] == "pro"
        assert reloaded["plan_expires_at"] is not None

        # Verify audit record exists
        from sqlalchemy.orm import Session
        from core.models import AdminAudit
        with Session(store.engine) as session:
            audit = session.query(AdminAudit).filter_by(target_telegram_id=1001).all()
            assert len(audit) == 1
            assert audit[0].actor_telegram_id == 42
            assert audit[0].new_plan == "pro"

    def test_admin_plan_rejects_invalid_plan(self, store):
        with pytest.raises(ValueError, match="plan"):
            store.set_plan(telegram_id=1001, plan="vip", actor_id=42)

    def test_set_quota_rejects_invalid_plan(self, store):
        with pytest.raises(ValueError, match="plan"):
            store.set_quota("vip", "llm_summary", period="daily", limit=10)


class TestConcurrencyQuota:
    """Transactional quota: 100 parallel attempts → exactly 3 succeed.

    Uses the same file-based SQLite engine (tmp_path). The AccessStore
    serializes via per (user_id, action) thread locks for SQLite since
    SQLite doesn't support row-level SELECT ... FOR UPDATE.
    """

    def test_concurrent_quota_exactly_limit_succeed(self, engine):
        store = AccessStore(engine=engine, owner_ids={42})
        store.ensure_user(telegram_id=5001)
        store.set_quota("free", "llm_summary", period="daily", limit=3)

        successes = []
        failures = []
        lock = threading.Lock()

        def attempt():
            try:
                result = store.check_and_record(5001, "llm_summary")
                with lock:
                    successes.append(result)
            except QuotaExceeded:
                with lock:
                    failures.append(1)
            except Exception:
                with lock:
                    failures.append(1)

        threads = [threading.Thread(target=attempt) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 3, f"Expected 3 successes, got {len(successes)} (failures: {len(failures)})"
        assert len(failures) == 97

    def test_owner_unaffected_by_concurrent_quota(self, engine):
        store = AccessStore(engine=engine, owner_ids={42})
        store.ensure_user(telegram_id=42)
        store.set_quota("free", "llm_summary", period="daily", limit=1)

        successes = []
        lock = threading.Lock()

        def attempt():
            try:
                result = store.check_and_record(42, "llm_summary")
                with lock:
                    successes.append(result)
            except Exception:
                pass

        threads = [threading.Thread(target=attempt) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 50  # owner unlimited
        assert all(s["remaining"] is None for s in successes)


class TestQuotaWindow:
    def test_daily_window_affects_different_days(self, store):
        """Usage on day N should not count against day N+1."""
        store.ensure_user(telegram_id=6001)
        store.set_quota("free", "media_download", period="daily", limit=1)

        first = store.check_and_record(6001, "media_download")
        assert first["allowed"]

        # Same day — should fail
        with pytest.raises(QuotaExceeded):
            store.check_and_record(6001, "media_download")

        # Reset counter (simulate new day)
        from sqlalchemy.orm import Session
        from core.models import UsageCounter
        with Session(store.engine) as session:
            session.query(UsageCounter).filter_by(user_id=6001, cost_class="media_download").delete()
            session.commit()

        # Now should succeed again
        second_day = store.check_and_record(6001, "media_download")
        assert second_day["allowed"]
