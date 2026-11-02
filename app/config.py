from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _app_root() -> Path:
    override = os.environ.get("PKM_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_ROOT = _app_root()

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "kind": "official",
        "api_key": "",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    },
    "anthropic": {
        "kind": "official",
        "api_key": "",
        "model": "claude-3-5-haiku-latest",
        "base_url": "https://api.anthropic.com/v1",
    },
    "gemini": {
        "kind": "official",
        "api_key": "",
        "model": "gemini-1.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
    },
    "deepseek": {
        "kind": "official",
        "api_key": "",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
    },
}

DEFAULT_CONFIG: dict[str, Any] = {
    "vault_path": str(APP_ROOT / "vault"),
    "active_provider": "openai",
    "providers": copy.deepcopy(PROVIDER_DEFAULTS),
    "embedding": {
        "provider": "local",
        "model": "local-ngram",
        "base_url": "",
        "api_key": "",
    },
    "github_token": "",
    "model_health": {},
    "usage_accounts": [],
    "language": "zh-CN",
    "profile": {
        "target_role": "",
        "level": "",
        "is_technical": False,
        "languages": [],
        "skills": [],
        "learning_goals": [],
        "weekly_hours": 5,
    },
    "feed_window_days": 3,
    "auto_summarize_limit": 3,
    "feed_filter_skills": [],
    "feed_filter_interests": [],
    "feed_filter_goals": [],
    "feed_filter_sources": [],
    "query_expansion_enabled": True,
    "auto_refresh_enabled": True,
    "schedule_mode": "daily",
    "daily_time": "06:00",
    "refresh_interval_minutes": 120,
    "auto_refresh_github": True,
    "rss_sources": [],
    "scheduler_last_run": "",
    "auto_review_enabled": False,
    "review_interval_days": 7,
    "last_review_at": "",
}


@dataclass
class Settings:
    data_dir: Path
    config_path: Path
    default_vault: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pkm.db"

    @property
    def wiki_dir(self) -> Path:
        return self.data_dir / "wiki"

    @property
    def static_dir(self) -> Path:
        return Path(__file__).resolve().parent / "static"

    @property
    def templates_dir(self) -> Path:
        return Path(__file__).resolve().parent / "templates"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.default_vault.mkdir(parents=True, exist_ok=True)
        self.wiki_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        # The portable application keeps both directories next to the exe.
        # PKM_DATA_DIR / PKM_VAULT_DIR are reserved for development and tests.
        data_dir = Path(os.environ.get("PKM_DATA_DIR", APP_ROOT / "data")).expanduser()
        default_vault = Path(
            os.environ.get("PKM_VAULT_DIR", APP_ROOT / "vault")
        ).expanduser()
        return cls(
            data_dir=data_dir,
            config_path=data_dir / "config.json",
            default_vault=default_vault,
        )


settings = Settings.from_env()


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    settings.ensure()
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["vault_path"] = str(settings.default_vault)
    if settings.config_path.exists():
        try:
            raw = json.loads(settings.config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                config = _deep_merge(config, raw)
        except (OSError, json.JSONDecodeError):
            pass
    # Vault location is fixed next to the application; old custom paths in
    # config.json are ignored intentionally.
    config["vault_path"] = str(Path(settings.default_vault).expanduser().resolve())
    profile = config.setdefault("profile", {})
    legacy_interests = profile.pop("interests", None) or []
    goals = list(profile.get("learning_goals") or [])
    for item in legacy_interests:
        if item not in goals:
            goals.append(item)
    profile["learning_goals"] = goals
    profile.setdefault("languages", [])
    profile.setdefault("is_technical", bool(profile["languages"]))
    # The new feed flow fetches by source and time only; profile words are
    # used for relevance analysis after ingestion, not for acquisition.
    for key in (
        "feed_filter_skills",
        "feed_filter_interests",
        "feed_filter_goals",
        "feed_filter_sources",
    ):
        config[key] = []
    if not settings.config_path.exists():
        save_config(config)
    return config


def save_config(config: dict[str, Any]) -> None:
    settings.ensure()
    tmp = settings.config_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, settings.config_path)


def vault_path(config: dict[str, Any] | None = None) -> Path:
    config = config or load_config()
    return Path(config["vault_path"]).expanduser().resolve()


def provider_config(config: dict[str, Any], name: str | None = None) -> tuple[str, dict[str, str]]:
    name = name or config.get("active_provider") or "openai"
    providers = config.get("providers", {})
    return name, dict(providers.get(name, PROVIDER_DEFAULTS.get(name, {})))


def has_any_key(config: dict[str, Any]) -> bool:
    return any(
        bool((item or {}).get("api_key"))
        for item in config.get("providers", {}).values()
    )


def masked_config(config: dict[str, Any]) -> dict[str, Any]:
    ready = has_any_key(config)
    result = copy.deepcopy(config)
    providers = {}
    for name, item in result.get("providers", {}).items():
        item = dict(item or {})
        item["has_key"] = bool(item.get("api_key"))
        item["api_key"] = ""
        providers[name] = item
    result["providers"] = providers
    embedding = dict(result.get("embedding") or {})
    embedding["has_key"] = bool(embedding.get("api_key"))
    embedding["api_key"] = ""
    result["embedding"] = embedding
    result["github_token_set"] = bool(result.get("github_token"))
    result["github_token"] = ""
    accounts = []
    for item in result.get("usage_accounts") or []:
        item = dict(item or {})
        item["has_access_token"] = bool(item.get("access_token"))
        item["has_api_key"] = bool(item.get("api_key"))
        item["has_platform_token"] = bool(item.get("platform_token"))
        item["access_token"] = ""
        item["api_key"] = ""
        item["platform_token"] = ""
        accounts.append(item)
    result["usage_accounts"] = accounts
    result["ready"] = ready
    return result
