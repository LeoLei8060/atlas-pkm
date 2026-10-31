from __future__ import annotations

from datetime import datetime

from app.services import scheduler


def _config(**overrides):
    config = {
        "active_provider": "deepseek",
        "providers": {"deepseek": {"api_key": "test", "model": "test"}},
        "auto_refresh_enabled": True,
        "schedule_mode": "daily",
        "daily_time": "06:00",
        "refresh_interval_minutes": 120,
    }
    config.update(overrides)
    return config


def test_daily_schedule_runs_at_time_and_catches_up():
    scheduler._last_run_ts = 0
    config = _config()
    assert not scheduler._schedule_due(config, datetime(2026, 10, 29, 5, 59))
    assert scheduler._schedule_due(config, datetime(2026, 10, 29, 6, 0))

    scheduler._last_run_ts = datetime(2026, 10, 29, 6, 5).timestamp()
    assert not scheduler._schedule_due(config, datetime(2026, 10, 29, 18, 0))
    assert scheduler._schedule_due(config, datetime(2026, 10, 30, 6, 0))


def test_interval_schedule_uses_last_run():
    config = _config(schedule_mode="interval", refresh_interval_minutes=60)
    now = datetime(2026, 10, 29, 12, 0)
    scheduler._last_run_ts = datetime(2026, 10, 29, 11, 1).timestamp()
    assert not scheduler._schedule_due(config, now)
    scheduler._last_run_ts = datetime(2026, 10, 29, 10, 59).timestamp()
    assert scheduler._schedule_due(config, now)
