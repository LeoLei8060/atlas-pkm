from __future__ import annotations

import pytest

from app.config import settings
from app.db import init_db
from app.vault import ensure_vault


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    vault = tmp_path / "vault"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "config_path", data_dir / "config.json")
    monkeypatch.setattr(settings, "default_vault", vault)
    settings.ensure()
    init_db()
    ensure_vault()
    yield tmp_path
