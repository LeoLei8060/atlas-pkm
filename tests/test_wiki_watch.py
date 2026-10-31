from __future__ import annotations

from app.config import settings
from app.services import wiki_watch
from app.services.wiki import build_wiki
from app.vault import atomic_write, dump_note, target_path


def test_wiki_rebuild_removes_stale_pages(isolated):
    build_wiki()
    before = {path.name for path in settings.wiki_dir.glob("*.html")}
    atomic_write(
        target_path("02-Knowledge/Concepts/Stale-Test.md"),
        dump_note({"title": "Stale Test"}, "# Stale Test\n\nbody\n"),
    )
    build_wiki()
    with_stale = {path.name for path in settings.wiki_dir.glob("*.html")}
    assert len(with_stale) == len(before) + 1
    target_path("02-Knowledge/Concepts/Stale-Test.md").unlink()
    build_wiki()
    assert {path.name for path in settings.wiki_dir.glob("*.html")} == before


def test_wiki_signature_tracks_vault_changes(isolated):
    before = wiki_watch._signature()
    atomic_write(
        target_path("02-Knowledge/Concepts/Watch-Test.md"),
        dump_note({"title": "Watch Test"}, "# Watch Test\n\nbody\n"),
    )
    after = wiki_watch._signature()
    assert len(after) == len(before) + 1
    assert any(path.endswith("Watch-Test.md") for path, _, _ in after)
    assert after != before
