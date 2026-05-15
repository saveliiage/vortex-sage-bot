"""initial: users quota_limits usage_counters usage_events admin_audit

Revision ID: 0001_initial
Create Date: 2026-05-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("plan", sa.String(50), nullable=False, server_default=sa.text("'free'")),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "plan IN ('owner', 'free', 'pro', 'creator', 'blocked')",
            name="ck_users_plan_valid",
        ),
        sa.PrimaryKeyConstraint("telegram_id"),
    )

    # ── quota_limits ─────────────────────────────────────────────────────────
    op.create_table(
        "quota_limits",
        sa.Column("plan", sa.String(50), nullable=False),
        sa.Column("cost_class", sa.String(100), nullable=False),
        sa.Column("period", sa.String(20), nullable=False, server_default=sa.text("'daily'")),
        sa.Column("limit_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "plan IN ('owner', 'free', 'pro', 'creator', 'blocked')",
            name="ck_quota_limits_plan_valid",
        ),
        sa.CheckConstraint(
            "period = 'daily'",
            name="ck_quota_limits_period_daily",
        ),
        sa.PrimaryKeyConstraint("plan", "cost_class"),
    )

    # ── usage_counters ───────────────────────────────────────────────────────
    op.create_table(
        "usage_counters",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("cost_class", sa.String(100), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("user_id", "cost_class", "window_start"),
    )

    # ── usage_events ─────────────────────────────────────────────────────────
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("cost_class", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("platform", sa.String(50), nullable=True),
        sa.Column("source_url_hash", sa.String(128), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"])

    # ── admin_audit ──────────────────────────────────────────────────────────
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("target_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("old_plan", sa.String(50), nullable=True),
        sa.Column("new_plan", sa.String(50), nullable=False),
        sa.Column("duration", sa.String(50), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_audit_actor_telegram_id", "admin_audit", ["actor_telegram_id"])
    op.create_index("ix_admin_audit_target_telegram_id", "admin_audit", ["target_telegram_id"])

    # ── default quotas (from CONTRACT) ───────────────────────────────────────
    defaults = [
        # free plan
        ("free", "cheap_metadata", "daily", 10),
        ("free", "llm_summary", "daily", 3),
        ("free", "llm_repurpose", "daily", 0),
        ("free", "media_download", "daily", 3),
        ("free", "media_convert", "daily", 3),
        ("free", "apify", "daily", 0),
        ("free", "export", "daily", 3),
        # pro plan
        ("pro", "cheap_metadata", "daily", 50),
        ("pro", "llm_summary", "daily", 15),
        ("pro", "llm_repurpose", "daily", 5),
        ("pro", "media_download", "daily", 20),
        ("pro", "media_convert", "daily", 10),
        ("pro", "apify", "daily", 5),
        ("pro", "export", "daily", 20),
        # creator plan
        ("creator", "cheap_metadata", "daily", 200),
        ("creator", "llm_summary", "daily", 50),
        ("creator", "llm_repurpose", "daily", 30),
        ("creator", "media_download", "daily", 50),
        ("creator", "media_convert", "daily", 30),
        ("creator", "apify", "daily", 30),
        ("creator", "export", "daily", 50),
    ]
    quota_limits = sa.sql.table(
        "quota_limits",
        sa.sql.column("plan"),
        sa.sql.column("cost_class"),
        sa.sql.column("period"),
        sa.sql.column("limit_count"),
    )
    op.bulk_insert(quota_limits, [
        {"plan": p, "cost_class": c, "period": d, "limit_count": n}
        for p, c, d, n in defaults
    ])


def downgrade() -> None:
    op.drop_table("admin_audit")
    op.drop_table("usage_events")
    op.drop_table("usage_counters")
    op.drop_table("quota_limits")
    op.drop_table("users")
