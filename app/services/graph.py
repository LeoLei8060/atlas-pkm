from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..vault import scan_notes

WIKILINK = re.compile(r"\[\[([^\]|#]+)")
SEMANTIC_TAGS = {"rust", "python", "c++", "c", "go", "ai", "typescript", "网络", "系统设计", "数据库"}


def build_graph() -> dict[str, Any]:
    notes = scan_notes()
    nodes = []
    by_title: dict[str, str] = {}
    by_path: dict[str, str] = {}
    by_stem: dict[str, str] = {}
    for note in notes:
        path = note["path"]
        title = note["title"]
        by_title[title.lower()] = path
        by_path[path.lower()] = path
        by_path[path.rsplit("/", 1)[-1].lower()] = path
        by_stem[path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()] = path
        nodes.append(
            {
                "id": path,
                "label": title,
                "type": note["meta"].get("type", "note"),
                "tags": note["meta"].get("tags", []),
            }
        )

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(source: str, target: str, kind: str, weight: float = 1.0) -> None:
        if source == target:
            return
        key = (source, target, kind)
        if key in seen:
            return
        seen.add(key)
        edges.append({"source": source, "target": target, "kind": kind, "weight": weight})

    for note in notes:
        for raw in WIKILINK.findall(note["body"]):
            target = raw.strip().lower()
            resolved = by_title.get(target) or by_path.get(target) or by_stem.get(target)
            if resolved:
                add_edge(note["path"], resolved, "wiki", 1.0)

    tag_members: dict[str, list[str]] = defaultdict(list)
    for note in notes:
        for tag in note["meta"].get("tags", []) or []:
            tag_members[str(tag).lower()].append(note["path"])
    for tag, paths in tag_members.items():
        if len(paths) < 2 or len(paths) > 8:
            continue
        for index, source in enumerate(paths):
            for target in paths[index + 1 :]:
                add_edge(source, target, "tag", 0.5 if tag not in SEMANTIC_TAGS else 0.8)

    degrees = defaultdict(int)
    for edge in edges:
        degrees[edge["source"]] += 1
        degrees[edge["target"]] += 1
    for node in nodes:
        node["degree"] = degrees[node["id"]]
    nodes.sort(key=lambda node: (-node["degree"], node["label"]))
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "notes": len(nodes),
            "links": len(edges),
            "isolated": sum(1 for node in nodes if node["degree"] == 0),
        },
    }
