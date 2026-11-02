from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import (
    has_any_key,
    load_config,
    masked_config,
    save_config,
    settings,
    vault_path,
)
from .db import db, init_db, now_iso, stats
from .providers import PROVIDER_LABELS, ProviderError, build_provider, provider_from_config
from .services import (
    arxiv,
    devto,
    embeddings,
    enrichment,
    github_rankings,
    graph,
    learning,
    links,
    profile_learning,
    review,
    scheduler,
    scoring,
    wiki_watch,
)
from .services.agent import (
    answer_question,
    enrich_items,
    score_feed_item,
    summarize_feed_item,
    translate_feed_item,
)
from .services.demo import seed_demo
from .services.feeds import (
    FeedError,
    add_source,
    backfill_source_ids,
    count_feed,
    dedupe_sources,
    delete_feed,
    delete_source,
    favorite_github_item,
    get_source,
    ingest_github,
    ingest_rss,
    list_feed,
    list_sources,
    set_source_enabled,
    sync_config_sources,
    update_feed,
    update_source_config,
)
from .services.source_adapters import discover_source, fetch_source as fetch_configured_source
from .services.source_catalog import add_catalog_sources, list_catalog
from .services.notes import save_feed_as_source
from .services.patches import apply_patch, list_patches, make_answer_patch, reject_patch
from .services.search import rebuild_search_index, search
from .services.wiki import build_wiki, wiki_status
from .vault import ensure_vault, list_notes


class ProviderPatch(BaseModel):
    api_key: str | None = None
    clear_api_key: bool = False
    model: str | None = None
    base_url: str | None = None
    label: str | None = None
    protocol: Literal["openai-compatible", "anthropic-compatible"] | None = None


class CustomProviderCreate(BaseModel):
    id: str = Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=80)
    protocol: Literal["openai-compatible", "anthropic-compatible"] = "openai-compatible"
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    api_key: str = Field(default="", max_length=4000)
    user_agent: str = Field(default="", max_length=500)


class EmbeddingUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None


class ProfileUpdate(BaseModel):
    target_role: str | None = None
    level: str | None = None
    is_technical: bool | None = None
    languages: list[str] | None = None
    skills: list[str] | None = None
    learning_goals: list[str] | None = None
    interests: list[str] | None = None
    weekly_hours: int | None = Field(default=None, ge=1, le=60)


class SettingsUpdate(BaseModel):
    active_provider: str | None = None
    providers: dict[str, ProviderPatch] | None = None
    embedding: EmbeddingUpdate | None = None
    profile: ProfileUpdate | None = None
    github_token: str | None = None

    auto_summarize_limit: int | None = Field(default=None, ge=0, le=10)
    feed_window_days: Literal[1, 3, 7] | None = None
    feed_filter_skills: list[str] | None = None
    feed_filter_interests: list[str] | None = None
    feed_filter_goals: list[str] | None = None
    feed_filter_sources: list[str] | None = None
    query_expansion_enabled: bool | None = None
    auto_refresh_enabled: bool | None = None
    schedule_mode: Literal["daily", "interval"] | None = None
    daily_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    refresh_interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    auto_refresh_github: bool | None = None
    auto_review_enabled: bool | None = None
    review_interval_days: int | None = Field(default=None, ge=1, le=90)
    rss_sources: list[str] | None = None


class TestProviderRequest(BaseModel):
    provider: str | None = None


class ListModelsRequest(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    protocol: Literal["openai-compatible", "anthropic-compatible"] | None = None
    user_agent: str | None = None


class RefreshRequest(BaseModel):
    kind: Literal["rss", "github"] = "rss"
    url: str | None = None
    days: int = Field(default=7, ge=1, le=30)
    limit: int = Field(default=10, ge=1, le=30)


class FeedStatusRequest(BaseModel):
    status: Literal["unread", "read", "saved", "dismissed"]


class FeedbackRequest(BaseModel):
    value: int = Field(ge=-1, le=1)


class BulkFeedRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    action: Literal["unread", "read", "saved", "dismissed", "delete"]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    save_patch: bool = False
    limit: int = Field(default=6, ge=1, le=12)


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    mode: Literal["knowledge_doc", "interview"] = "knowledge_doc"
    difficulty: str = Field(default="中级", max_length=20)
    count: int = Field(default=5, ge=3, le=10)


class SaveGenerationRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    markdown: str = Field(min_length=1, max_length=200000)
    citations: list[dict[str, Any]] = Field(default_factory=list)


class AppendLearningRequest(SaveGenerationRequest):
    path: str = Field(min_length=1, max_length=500)


class ReviewRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=90)


class ArxivRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=10, ge=1, le=20)


class DevtoRequest(BaseModel):
    tag: str = Field(default="", max_length=80)
    limit: int = Field(default=10, ge=1, le=20)


class ProfileApplyRequest(BaseModel):
    suggestions: dict[str, Any]


class LinkSuggestRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class SourceCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    name: str = Field(default="", max_length=120)
    group: Literal["github", "other"] = "other"
    adapter: str = Field(default="rss", max_length=40)
    config: dict[str, Any] = Field(default_factory=dict)


class GitHubFavoriteRequest(BaseModel):
    item: dict[str, Any]


class CatalogAddRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, max_length=120)
    config: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure()
    init_db()
    ensure_vault()
    sync_config_sources(load_config())
    dedupe_sources()
    backfill_source_ids()
    rebuild_search_index()
    if not (settings.wiki_dir / "index.html").exists():
        build_wiki()
    config = load_config()
    enrichment.start_background(config)
    scoring.start_background(config)
    if embeddings.is_external(config) and (config.get("embedding") or {}).get("api_key"):
        embeddings.start_incremental(config)
    scheduler.start()
    wiki_watch.start()
    try:
        yield
    finally:
        await wiki_watch.stop()
        await scheduler.stop()


def create_app() -> FastAPI:
    settings.ensure()
    app = FastAPI(title="AI-PKM Agent", version=__version__, lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    app.mount("/wiki", StaticFiles(directory=settings.wiki_dir, html=True), name="wiki")

    @app.exception_handler(ProviderError)
    async def provider_error_handler(_, exc: ProviderError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(FeedError)
    async def feed_error_handler(_, exc: FeedError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(ValueError)
    async def value_error_handler(_, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/")
    async def index():
        return FileResponse(
            settings.static_dir / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/health")
    async def health():
        config = load_config()
        return {
            "ok": True,
            "version": __version__,
            "ready": has_any_key(config),
            "vault_path": str(vault_path(config)),
        }

    @app.get("/api/state")
    async def state():
        config = load_config()
        current = stats()
        return {
            "ready": has_any_key(config),
            "active_provider": config.get("active_provider", "openai"),
            "providers": {
                name: bool((item or {}).get("api_key"))
                for name, item in config.get("providers", {}).items()
            },
            "stats": current,
            "model_health": config.get("model_health") or {},
            "vault_path": str(vault_path(config)),
            "wiki": wiki_status(),
            "wiki_sync": wiki_watch.status(),
            "scheduler": scheduler.status(),
            "embedding": embeddings.status(config),
            "embedding_indexer": embeddings.incremental_status(),
            "feed_enrichment": enrichment.status(),
            "feed_scoring": scoring.status(),
            "version": __version__,
        }

    @app.get("/api/settings")
    async def get_settings():
        return masked_config(load_config())

    @app.post("/api/providers/custom")
    async def create_custom_provider(body: CustomProviderCreate):
        config = load_config()
        if body.id in PROVIDER_LABELS or body.id in config.get("providers", {}):
            raise HTTPException(409, "Provider ID 已存在")
        config.setdefault("providers", {})[body.id] = {
            "kind": "third_party",
            "label": body.label.strip(),
            "protocol": body.protocol,
            "base_url": body.base_url.rstrip("/"),
            "model": body.model.strip(),
            "api_key": body.api_key,
            "user_agent": body.user_agent.strip(),
        }
        save_config(config)
        return masked_config(config)

    @app.delete("/api/providers/custom/{provider_id}")
    async def delete_custom_provider(provider_id: str):
        config = load_config()
        item = config.get("providers", {}).get(provider_id)
        if not item or item.get("kind") != "third_party":
            raise HTTPException(404, "第三方 Provider 不存在")
        del config["providers"][provider_id]
        if config.get("active_provider") == provider_id:
            config["active_provider"] = "deepseek"
        save_config(config)
        return masked_config(config)

    @app.post("/api/profile/learn")
    async def profile_learn():
        try:
            return await profile_learning.suggest_profile()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/profile/apply")
    async def profile_apply(body: ProfileApplyRequest):
        profile = profile_learning.apply_profile_suggestions(body.suggestions)
        return {"profile": profile}

    @app.put("/api/settings")
    async def update_settings(body: SettingsUpdate):
        config = load_config()
        if body.active_provider:
            if body.active_provider not in config.get("providers", {}):
                raise HTTPException(400, "未知的 Provider")
            config["active_provider"] = body.active_provider
        if body.providers:
            for name, patch in body.providers.items():
                if name not in config.get("providers", {}):
                    continue
                target = config["providers"][name]
                if patch.label is not None and target.get("kind") == "third_party":
                    target["label"] = patch.label.strip()[:80]
                if patch.protocol is not None and target.get("kind") == "third_party":
                    target["protocol"] = patch.protocol
                if patch.model is not None and patch.model.strip():
                    target["model"] = patch.model.strip()
                if patch.base_url is not None and patch.base_url.strip():
                    target["base_url"] = patch.base_url.strip().rstrip("/")
                if patch.clear_api_key:
                    target["api_key"] = ""
                elif patch.api_key:
                    target["api_key"] = patch.api_key.strip()
                if (
                    config.get("active_provider") == name
                    and not target.get("api_key")
                ):
                    fallback = next(
                        (
                            other
                            for other, item in config.get("providers", {}).items()
                            if other != name and item.get("api_key") and item.get("model")
                        ),
                        "deepseek",
                    )
                    config["active_provider"] = fallback
        if body.embedding:
            target = config.setdefault("embedding", {})
            if body.embedding.provider:
                if body.embedding.provider not in {"local", "openai", "gemini", "ollama"}:
                    raise HTTPException(400, "未知的 embedding provider")
                target["provider"] = body.embedding.provider
            if body.embedding.model is not None and body.embedding.model.strip():
                target["model"] = body.embedding.model.strip()
            if body.embedding.base_url is not None and body.embedding.base_url.strip():
                target["base_url"] = body.embedding.base_url.strip().rstrip("/")
            if body.embedding.api_key:
                target["api_key"] = body.embedding.api_key.strip()
        if body.profile:
            profile = config.setdefault("profile", {})
            if body.profile.target_role is not None:
                profile["target_role"] = body.profile.target_role.strip()
            if body.profile.level is not None:
                profile["level"] = body.profile.level.strip()
            if body.profile.is_technical is not None:
                profile["is_technical"] = body.profile.is_technical
            for field in ("languages", "skills", "learning_goals"):
                value = getattr(body.profile, field)
                if value is not None:
                    profile[field] = [item.strip() for item in value if item.strip()][:30]
            if body.profile.interests is not None:
                goals = list(profile.get("learning_goals") or [])
                for item in body.profile.interests:
                    if item.strip() and item.strip() not in goals:
                        goals.append(item.strip())
                profile["learning_goals"] = goals[:30]
            if body.profile.weekly_hours is not None:
                profile["weekly_hours"] = body.profile.weekly_hours
        if body.providers is not None or body.active_provider is not None:
            config["model_health"] = {}
        if body.github_token:
            config["github_token"] = body.github_token.strip()
        if body.auto_summarize_limit is not None:
            config["auto_summarize_limit"] = body.auto_summarize_limit
        if body.feed_window_days is not None:
            config["feed_window_days"] = body.feed_window_days
        for key in (
            "feed_filter_skills",
            "feed_filter_interests",
            "feed_filter_goals",
            "feed_filter_sources",
        ):
            values = getattr(body, key)
            if values is not None:
                config[key] = list(dict.fromkeys(
                    str(value).strip() for value in values if str(value).strip()
                ))[:40]
        if body.query_expansion_enabled is not None:
            config["query_expansion_enabled"] = body.query_expansion_enabled
        if body.auto_refresh_enabled is not None:
            config["auto_refresh_enabled"] = body.auto_refresh_enabled
        if body.schedule_mode:
            config["schedule_mode"] = body.schedule_mode
        if body.daily_time:
            config["daily_time"] = body.daily_time
        if body.refresh_interval_minutes is not None:
            config["refresh_interval_minutes"] = body.refresh_interval_minutes
        if body.auto_refresh_github is not None:
            config["auto_refresh_github"] = body.auto_refresh_github
        if body.auto_review_enabled is not None:
            config["auto_review_enabled"] = body.auto_review_enabled
        if body.review_interval_days is not None:
            config["review_interval_days"] = body.review_interval_days
        if body.rss_sources is not None:
            cleaned = []
            for url in body.rss_sources:
                url = (url or "").strip()
                if url.startswith(("http://", "https://")) and url not in cleaned:
                    cleaned.append(url)
            config["rss_sources"] = cleaned[:20]

        save_config(config)
        ensure_vault(vault_path(config))
        return masked_config(config)

    @app.post("/api/providers/test")
    async def test_provider(body: TestProviderRequest):
        config = load_config()
        name = body.provider or config.get("active_provider")
        provider = provider_from_config(config, name)
        health = {
            "provider": name,
            "model": provider.model,
            "at": now_iso(),
        }
        try:
            text = await provider.ping()
        except Exception as exc:
            config["model_health"] = {**health, "ok": False, "error": str(exc)[:500]}
            save_config(config)
            raise HTTPException(502, f"{provider.name} 连接失败：{exc}") from exc
        config["model_health"] = {**health, "ok": True, "error": ""}
        save_config(config)
        return {"ok": True, "provider": provider.name, "model": provider.model, "reply": text}

    @app.post("/api/providers/models")
    async def provider_models(body: ListModelsRequest):
        config = load_config()
        if body.provider:
            target = (config.get("providers") or {}).get(body.provider)
            if target is None:
                raise HTTPException(404, "Provider 不存在")
            item = dict(target)
            name = body.provider
        else:
            item = {
                "base_url": body.base_url or "",
                "protocol": body.protocol or "openai-compatible",
                "model": "",
            }
            name = "custom"
        if body.api_key:
            item["api_key"] = body.api_key.strip()
        if body.base_url:
            item["base_url"] = body.base_url.strip().rstrip("/")
        if body.protocol:
            item["protocol"] = body.protocol
        if body.user_agent is not None:
            item["user_agent"] = body.user_agent.strip()
        if not item.get("base_url") and name == "custom":
            raise HTTPException(400, "第三方模型需要 Base URL")
        provider = build_provider(name, item)
        try:
            models = await provider.list_models()
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"无法连接模型接口：{exc}") from exc
        except Exception as exc:
            raise HTTPException(
                502,
                f"获取模型列表失败：{type(exc).__name__}: {exc}",
            ) from exc
        return {
            "provider": name,
            "base_url": provider.base_url,
            "models": models,
        }

    @app.get("/api/feed")
    async def feed(
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=200),
        sort: str = Query(default="recent"),
        q: str = Query(default="", max_length=200),
        source_type: str = Query(default="", max_length=40),
        source_id: str = Query(default="", max_length=120),
        tag: str = Query(default="", max_length=80),
        offset: int = Query(default=0, ge=0),
    ):
        items = list_feed(
            status=status,
            limit=limit,
            sort=sort,
            q=q,
            source_type=source_type,
            source_id=source_id,
            tag=tag,
            offset=offset,
        )
        total = count_feed(
            status,
            q=q,
            source_type=source_type,
            source_id=source_id,
            tag=tag,
        )
        return {
            "items": items,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(items) < total,
        }

    @app.post("/api/feed/refresh")
    async def refresh_feed(body: RefreshRequest):
        config = load_config()
        if not has_any_key(config):
            raise HTTPException(400, "请先在设置中配置模型 API Key")
        if body.kind == "rss":
            if not body.url:
                raise HTTPException(400, "RSS 需要提供 url")
            if not body.url.startswith(("http://", "https://")):
                raise HTTPException(400, "RSS URL 必须是 http(s)")
            result = await ingest_rss(body.url, name="RSS", client=None)
        else:
            result = await ingest_github(
                days=body.days,
                limit=body.limit,
                token=str(config.get("github_token") or ""),
            )
        enrichment: list[dict[str, Any]] = []
        if result["ids"]:
            enrichment = await enrich_items(result["ids"], config)
        return {**result, "enrichment": enrichment}

    @app.post("/api/arxiv/refresh")
    async def arxiv_refresh(body: ArxivRequest):
        try:
            result = await arxiv.ingest_arxiv(body.query, limit=body.limit)
        except FeedError as exc:
            raise HTTPException(502, str(exc)) from exc
        config = load_config()
        if result["ids"] and has_any_key(config):
            result["enrichment"] = await enrich_items(result["ids"], config)
        return result

    @app.post("/api/devto/refresh")
    async def devto_refresh(body: DevtoRequest):
        try:
            result = await devto.ingest_devto(body.tag, limit=body.limit)
        except FeedError as exc:
            raise HTTPException(502, str(exc)) from exc
        config = load_config()
        if result["ids"] and has_any_key(config):
            result["enrichment"] = await enrich_items(result["ids"], config)
        return result

    @app.post("/api/feed/enrich_all")
    async def enrich_all():
        config = load_config()
        if not has_any_key(config):
            raise HTTPException(400, "请先在设置中配置模型 API Key")
        enrichment.start_background(config)
        return enrichment.status()

    @app.post("/api/feed/score_all")
    async def score_all():
        config = load_config()
        if not has_any_key(config):
            raise HTTPException(400, "请先在设置中配置模型 API Key")
        scoring.start_background(config)
        return scoring.status()

    @app.post("/api/feed/{feed_id}/score")
    async def score_feed(feed_id: str):
        try:
            return await score_feed_item(feed_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/github/meta")
    async def github_meta():
        return github_rankings.meta()

    @app.get("/api/github/rankings")
    async def github_rankings_api(
        stack: str = Query(default="ai"),
        metric: str = Query(default="new_week"),
        limit: int = Query(default=10, ge=5, le=20),
        refresh: bool = Query(default=False),
    ):
        config = load_config()
        try:
            return await github_rankings.get_ranking(
                stack,
                metric,
                limit=limit,
                refresh=refresh,
                token=str(config.get("github_token") or ""),
            )
        except github_rankings.RankingError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/github/favorite")
    async def favorite_github(body: GitHubFavoriteRequest):
        try:
            return favorite_github_item(body.item)
        except FeedError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/feed/{feed_id}/summarize")
    async def summarize(feed_id: str):
        return await summarize_feed_item(feed_id)

    @app.post("/api/feed/{feed_id}/translate")
    async def translate(feed_id: str):
        return await translate_feed_item(feed_id)

    @app.post("/api/feed/{feed_id}/save")
    async def save_feed(feed_id: str):
        result = update_feed(feed_id, status="saved")
        if result is None:
            raise HTTPException(404, "内容不存在")
        return {"item": result}

    @app.post("/api/feed/{feed_id}/import")
    async def import_feed(feed_id: str):
        result = save_feed_as_source(feed_id)
        if result is None:
            raise HTTPException(404, "内容不存在")
        build_wiki()
        return result

    @app.delete("/api/feed/{feed_id}")
    async def delete_feed_item(feed_id: str):
        if not delete_feed(feed_id):
            raise HTTPException(404, "内容不存在")
        return {"deleted": True, "id": feed_id}

    @app.post("/api/feed/{feed_id}/status")
    async def set_feed_status(feed_id: str, body: FeedStatusRequest):
        updated = update_feed(feed_id, status=body.status)
        if updated is None:
            raise HTTPException(404, "内容不存在")
        return updated

    @app.post("/api/feed/{feed_id}/feedback")
    async def feed_feedback(feed_id: str, body: FeedbackRequest):
        updated = update_feed(feed_id, feedback=body.value)
        if updated is None:
            raise HTTPException(404, "内容不存在")
        return updated

    @app.post("/api/feed/bulk")
    async def bulk_feed_status(body: BulkFeedRequest):
        updated = 0
        for feed_id in dict.fromkeys(body.ids):
            if body.action == "delete":
                if delete_feed(feed_id):
                    updated += 1
            elif update_feed(feed_id, status=body.action) is not None:
                updated += 1
        return {"updated": updated, "action": body.action}

    @app.get("/api/collections")
    async def collections():
        return {"items": list_feed(status="saved", limit=200)}

    @app.get("/api/sources")
    async def sources(kind: str | None = None, group: str | None = None):
        return {"items": list_sources(kind=kind, source_group=group)}

    @app.get("/api/sources/catalog")
    async def source_catalog():
        return {"items": list_catalog()}

    @app.post("/api/sources/catalog")
    async def import_source_catalog(body: CatalogAddRequest):
        try:
            return {"items": add_catalog_sources(body.ids)}
        except FeedError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/sources")
    async def create_source(body: SourceCreate):
        try:
            return add_source(
                url=body.url,
                name=body.name,
                source_group=body.group,
                adapter=body.adapter,
                config=body.config,
            )
        except FeedError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/sources/discover")
    async def discover(body: SourceCreate):
        try:
            return await discover_source(body.url)
        except FeedError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.patch("/api/sources/{source_id}")
    async def update_source(source_id: str, body: SourceUpdate):
        source = update_source_config(
            source_id, name=body.name, config=body.config
        )
        if body.enabled is not None:
            source = set_source_enabled(source_id, body.enabled)
        if source is None:
            raise HTTPException(404, "来源不存在")
        return source

    @app.delete("/api/sources/{source_id}")
    async def remove_source(source_id: str):
        if not delete_source(source_id):
            raise HTTPException(404, "来源不存在")
        return {"ok": True}

    @app.post("/api/sources/{source_id}/fetch")
    async def fetch_source(source_id: str):
        source = get_source(source_id)
        if source is None:
            raise HTTPException(404, "来源不存在")
        config = load_config()
        try:
            result = await fetch_configured_source(source, config)
        except Exception as exc:
            from .services.feeds import touch_source

            touch_source(source_id, "error", str(exc))
            raise HTTPException(400, str(exc)) from exc
        if result.get("ids") and has_any_key(config):
            result["enrichment"] = await enrich_items(result["ids"], config)
        return result

    @app.get("/api/notes")
    async def notes():
        return {"items": list_notes()}

    @app.get("/api/search")
    async def search_api(q: str = Query(min_length=1), limit: int = Query(default=10, ge=1, le=30)):
        return {"items": search(q, limit=limit)}

    @app.post("/api/ask")
    async def ask(body: AskRequest):
        result = await answer_question(body.question, limit=body.limit)
        if body.save_patch:
            patch = make_answer_patch(
                question=body.question,
                answer=result["answer"],
                citations=result["citations"],
            )
            result["patch"] = patch
        return result

    @app.post("/api/learning/generate")
    async def learning_generate(body: GenerateRequest):
        try:
            return await learning.generate(
                body.topic,
                mode=body.mode,
                difficulty=body.difficulty,
                count=body.count,
                config=load_config(),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/learning/save")
    async def learning_save(body: SaveGenerationRequest):
        return learning.save_as_patch(
            body.topic,
            body.markdown,
            citations=body.citations,
        )

    @app.post("/api/learning/append")
    async def learning_append(body: AppendLearningRequest):
        try:
            return learning.append_to_note(
                body.path,
                body.topic,
                body.markdown,
                citations=body.citations,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/review/stats")
    async def review_stats(days: int = Query(default=7, ge=1, le=90)):
        return review.stats(days)

    @app.post("/api/review")
    async def review_generate(body: ReviewRequest):
        config = load_config()
        if not has_any_key(config):
            raise HTTPException(400, "请先在设置中配置模型 API Key")
        return await review.weekly_review(body.days, config)

    @app.get("/api/graph")
    async def knowledge_graph():
        return graph.build_graph()

    @app.post("/api/graph/suggest")
    async def graph_suggest(body: LinkSuggestRequest):
        try:
            return await links.suggest_links(body.path, limit=body.limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/graph/suggest_all")
    async def graph_suggest_all(max_notes: int = Query(default=8, ge=1, le=20)):
        return await links.suggest_all(max_notes=max_notes)

    @app.get("/api/patches")
    async def patches():
        return {"items": list_patches(limit=20)}

    @app.post("/api/patches/{patch_id}/apply")
    async def apply(patch_id: str):
        result = apply_patch(patch_id)
        if result is None:
            raise HTTPException(404, "Patch 不存在")
        build_wiki()
        return result

    @app.post("/api/patches/{patch_id}/reject")
    async def reject(patch_id: str):
        result = reject_patch(patch_id)
        if result is None:
            raise HTTPException(404, "Patch 不存在")
        return result

    @app.post("/api/wiki/build")
    async def rebuild_wiki():
        return build_wiki()

    @app.get("/api/wiki/status")
    async def wiki_status_api():
        return {**wiki_status(), "sync": wiki_watch.status()}

    @app.get("/api/scheduler")
    async def scheduler_status_api():
        return scheduler.status()

    @app.get("/api/embeddings/status")
    async def embedding_status_api():
        return embeddings.status()

    @app.post("/api/embeddings/test")
    async def embedding_test_api():
        config = load_config()
        vectors, model, dimension = await embeddings.embed_texts(["embedding test"], config)
        return {
            "ok": True,
            "provider": embeddings.provider_name(config),
            "model": model,
            "dimension": dimension,
            "count": len(vectors),
        }

    @app.post("/api/embeddings/rebuild")
    async def embedding_rebuild_api():
        result = await embeddings.rebuild_embeddings(load_config())
        return {**result, "status": embeddings.status()}

    @app.post("/api/embeddings/incremental")
    async def embedding_incremental_api(max_docs: int = Query(default=100, ge=1, le=500)):
        return embeddings.start_incremental(load_config(), max_docs=max_docs)

    @app.post("/api/scheduler/run")
    async def scheduler_run_api(replace: bool = Query(default=False)):
        result = await scheduler.run_once(force=True, replace=replace)
        return result

    @app.get("/api/runs")
    async def runs(limit: int = Query(default=30, ge=1, le=100)):
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    @app.post("/api/dev/seed")
    async def dev_seed():
        result = seed_demo()
        build_wiki()
        return result

    return app


app = create_app()
