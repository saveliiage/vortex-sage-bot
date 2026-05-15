from __future__ import annotations

import pytest

from handlers.admin import parse_admin_plan_args


def test_parse_admin_plan_with_duration() -> None:
    parsed = parse_admin_plan_args(["1001", "pro", "30d"])
    assert parsed == {"telegram_id": 1001, "plan": "pro", "duration": "30d"}


def test_parse_admin_plan_without_duration() -> None:
    parsed = parse_admin_plan_args(["1001", "blocked"])
    assert parsed == {"telegram_id": 1001, "plan": "blocked", "duration": None}


def test_parse_admin_plan_rejects_bad_plan() -> None:
    with pytest.raises(ValueError, match="plan"):
        parse_admin_plan_args(["1001", "vip"])


def test_parse_admin_plan_rejects_bad_telegram_id() -> None:
    with pytest.raises(ValueError, match="telegram_id"):
        parse_admin_plan_args(["abc", "pro"])
