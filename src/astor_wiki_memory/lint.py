from __future__ import annotations

from pathlib import Path
import re


def lint_wiki(wiki_root: Path) -> dict[str, object]:
    """Scan all markdown files in wiki_root, checking for broken wikilinks and orphan topics."""
    wiki_root = Path(wiki_root).expanduser().resolve()
    if not wiki_root.exists():
        return {
            "wiki_root": str(wiki_root),
            "total_files": 0,
            "broken_links": [],
            "orphan_topics": [],
            "ok": True,
        }

    all_md_files = list(wiki_root.rglob("*.md"))
    available_stems: set[str] = {p.stem.lower() for p in all_md_files}

    wikilink_pattern = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]")

    broken_links: list[dict[str, str]] = []
    incoming_links: dict[str, int] = {p.stem.lower(): 0 for p in all_md_files}

    for md_file in all_md_files:
        rel_path = str(md_file.relative_to(wiki_root)).replace("\\", "/")
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for match in wikilink_pattern.finditer(content):
            raw_target = match.group(1).strip()
            target_slug = Path(raw_target).stem.lower()
            if target_slug not in available_stems:
                broken_links.append({
                    "source_file": rel_path,
                    "target_link": raw_target,
                })
            else:
                incoming_links[target_slug] = incoming_links.get(target_slug, 0) + 1

    orphan_topics: list[str] = []
    for md_file in all_md_files:
        rel_path = str(md_file.relative_to(wiki_root)).replace("\\", "/")
        if "topic" in rel_path.lower():
            if incoming_links.get(md_file.stem.lower(), 0) == 0:
                orphan_topics.append(rel_path)

    return {
        "wiki_root": str(wiki_root),
        "total_files": len(all_md_files),
        "broken_links": broken_links,
        "orphan_topics": sorted(orphan_topics),
        "ok": len(broken_links) == 0,
    }
