from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from ..config import vault_path
from ..vault import SKIP_PARTS
from .wiki import build_wiki

_task: asyncio.Task | None = None
_state: dict[str, Any] = {
    "enabled": True,
    "watching": False,
    "last_sync_at": "",
    "last_error": "",
    "pages": 0,
    "notes": 0,
}


def _signature() -> tuple[tuple[str, int, int], ...]:
    root = vault_path()
    rows = []
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append((rel.as_posix(), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(rows))


def status() -> dict[str, Any]:
    return dict(_state)


async def _loop() -> None:
    _state["watching"] = True
    try:
        signature = _signature()
        _state["notes"] = len(signature)
        while True:
            await asyncio.sleep(5)
            current = _signature()
            if current == signature:
                continue
            # Debounce editor saves and multi-file operations.
            await asyncio.sleep(1.5)
            settled = _signature()
            if settled != current:
                signature = settled
                continue
            try:
                result = await asyncio.to_thread(build_wiki)
                signature = settled
                _state.update(
                    {
                        "last_sync_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "last_error": "",
                        "pages": result.get("pages", 0),
                        "notes": len(settled),
                    }
                )
            except Exception as exc:
                signature = settled
                _state["last_error"] = str(exc)[:400]
    except asyncio.CancelledError:
        raise
    finally:
        _state["watching"] = False


def start() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="pkm-wiki-watch")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
