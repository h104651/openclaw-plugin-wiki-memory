"""Deterministic Markdown wiki integrity checks. No LLM or network calls."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from .chunker import parse_frontmatter

_LINK = re.compile(r"\[\[([^\]\n]+)\]\]")
_FENCE = re.compile(r"^\s*(?:~{3,}|\x60{3,})")
_INLINE = re.compile(r"\x60+[^\x60]*\x60+")
_SHA = re.compile(r"^[a-fA-F0-9]{7,40}$")
_SKIP_DIRS = {".git", "node_modules", ".obsidian", ".venv", "__pycache__"}


def _visible_prose(text: str) -> str:
    """Ignore fenced and inline code when counting Wiki links."""
    lines = []
    fenced = False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced and not line.startswith("    "):
            lines.append(_INLINE.sub("", line))
    return "\n".join(lines)


def _target(raw_link: str) -> str:
    """Strip Wiki display labels and heading fragments."""
    return raw_link.split("|", 1)[0].split("#", 1)[0].strip().replace("\\", "/")


def lint_wiki(wiki_root: Path) -> dict[str, object]:
    wiki_root = Path(wiki_root).expanduser().resolve()
    empty = {
        "wiki_root": str(wiki_root), "total_files": 0, "broken_links": [],
        "ambiguous_links": [], "orphan_topics": [], "supersession_errors": [],
        "provenance_warnings": [], "errors": [], "ok": False,
    }
    if not wiki_root.is_dir():
        empty["errors"].append(f"Wiki root not found or not a directory: {wiki_root}")
        return empty

    files = sorted(
        p for p in wiki_root.rglob("*.md")
        if not (_SKIP_DIRS & set(p.relative_to(wiki_root).parts))
    )
    by_stem = defaultdict(list)
    by_path = {}
    by_id = defaultdict(list)
    pages = {}
    errors = []
    for path in files:
        relative = path.relative_to(wiki_root).as_posix()
        by_stem[path.stem.casefold()].append(path)
        by_path[relative.casefold()] = path
        try:
            raw = path.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(raw)
            pages[path] = (metadata, body)
            by_id[str(metadata.get("memory_id") or path.stem)].append(path)
        except (OSError, UnicodeError) as exc:
            errors.append(f"Unreadable file {relative}: {exc}")

    broken = []
    ambiguous = []
    incoming = defaultdict(int)
    provenance_warnings = []
    supersession_errors = []
    for source, (meta, body) in pages.items():
        rel = source.relative_to(wiki_root).as_posix()
        for match in _LINK.finditer(_visible_prose(body)):
            raw_target = _target(match.group(1))
            if not raw_target:
                continue  # [[#heading]] links within the same page.
            name = raw_target.removesuffix(".md")
            targets = []
            if "/" in name:
                relative_path = (source.parent / (name + ".md")).resolve()
                if relative_path in pages:
                    targets = [relative_path]
                else:
                    direct = by_path.get((name + ".md").casefold())
                    if direct:
                        targets = [direct]
            else:
                local = (source.parent / (name + ".md")).resolve()
                if local in pages:
                    targets = [local]
                else:
                    targets = by_stem.get(name.casefold(), [])
            if not targets:
                broken.append({"source_file": rel, "target_link": raw_target})
            elif len(targets) > 1:
                ambiguous.append({
                    "source_file": rel, "target_link": raw_target,
                    "candidates": [p.relative_to(wiki_root).as_posix() for p in targets],
                })
            elif targets[0] != source:
                incoming[targets[0]] += 1

        commit = str(meta.get("commit") or "")
        source_repo = str(meta.get("source_repo") or "")
        if commit and not _SHA.fullmatch(commit):
            provenance_warnings.append({"file": rel, "reason": "invalid_commit_sha"})
        if commit and not source_repo:
            provenance_warnings.append({"file": rel, "reason": "missing_source_repo"})
        memory_id = str(meta.get("memory_id") or source.stem)
        next_id = str(meta.get("superseded_by") or "")
        previous_id = str(meta.get("supersedes") or "")
        status = str(meta.get("status") or "active")
        if status == "superseded" and not next_id:
            supersession_errors.append({"file": rel, "reason": "superseded_without_successor"})
        if status == "active" and next_id:
            supersession_errors.append({"file": rel, "reason": "active_with_successor"})
        if next_id:
            matches = by_id.get(next_id, [])
            if len(matches) != 1:
                supersession_errors.append({"file": rel, "reason": "missing_or_ambiguous_successor", "target": next_id})
            else:
                target_meta = pages.get(matches[0], ({}, ""))[0]
                if target_meta.get("supersedes") and str(target_meta["supersedes"]) != memory_id:
                    supersession_errors.append({"file": rel, "reason": "successor_reverse_link_mismatch", "target": next_id})
        if previous_id:
            matches = by_id.get(previous_id, [])
            if len(matches) != 1:
                supersession_errors.append({"file": rel, "reason": "missing_or_ambiguous_predecessor", "target": previous_id})
            elif matches[0] == source:
                supersession_errors.append({"file": rel, "reason": "self_supersession"})
        if len(by_id[memory_id]) > 1:
            supersession_errors.append({"file": rel, "reason": "duplicate_memory_id", "id": memory_id})

    # Detect cycles across explicit successor pointers.
    pointers = {
        str(meta.get("memory_id") or path.stem): str(meta.get("superseded_by"))
        for path, (meta, _) in pages.items() if meta.get("superseded_by")
    }
    visited = set()
    for origin in pointers:
        if origin in visited:
            continue
        seen = set()
        cur = origin
        while cur in pointers and cur not in visited:
            if cur in seen:
                supersession_errors.append({"file": origin, "reason": "supersession_cycle"})
                break
            seen.add(cur)
            cur = pointers[cur]
        visited.update(seen)

    orphans = [
        p.relative_to(wiki_root).as_posix()
        for p in pages
        if p.relative_to(wiki_root).parts[:2] == ("wiki", "topics") and incoming[p] == 0
    ]
    report = {
        "wiki_root": str(wiki_root),
        "total_files": len(files),
        "broken_links": broken,
        "ambiguous_links": ambiguous,
        "orphan_topics": sorted(orphans),
        "supersession_errors": supersession_errors,
        "provenance_warnings": provenance_warnings,
        "errors": errors,
    }
    report["ok"] = not (broken or ambiguous or supersession_errors or errors)
    return report
