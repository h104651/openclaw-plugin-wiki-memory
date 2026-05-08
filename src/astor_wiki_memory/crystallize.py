from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from .query_expansion import expand_query
from .text import normalize_text, slugify


def _has_section(body: str, heading: str) -> bool:
    return any(line.strip().lower() == f"## {heading}".lower() for line in body.splitlines())


def _recall_aliases(title: str, body: str, max_aliases: int = 10) -> list[str]:
    seed = f"{title}\n{body}"
    expanded = expand_query(seed, max_terms=max_aliases + 8).split()
    aliases: list[str] = []
    for term in expanded:
        clean = normalize_text(term).strip("、，,。.;；:：")
        if not clean or clean == title:
            continue
        if len(clean) < 2 and not ("\u4e00" <= clean <= "\u9fff"):
            continue
        if clean not in aliases:
            aliases.append(clean)
        if len(aliases) >= max_aliases:
            break
    return aliases


def _title_entities(title: str, body: str, max_entities: int = 8) -> list[str]:
    seed = f"{title}\n{body[:1200]}"
    candidates: list[str] = []

    def add(value: str) -> None:
        value = value.strip("`*_[](){}<>、，,。.;；:： ")
        if len(value) < 2 or value in candidates:
            return
        candidates.append(value)

    for item in re.findall(r"[A-Z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+|[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+", seed):
        add(item)
    for item in re.findall(r"[A-Z][A-Za-z0-9]{2,}", seed):
        add(item)
    for item in re.findall(r"[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 _-]{2,24}", title):
        add(item)

    return candidates[:max_entities]


def _status_line(body: str) -> str:
    for line in body.splitlines():
        clean = line.strip().lstrip("-*").strip()
        if not clean or clean.startswith("#"):
            continue
        if len(clean) > 140:
            clean = clean[:137].rstrip() + "…"
        return clean
    return "此頁記錄目前已沉澱的決策、狀態或修復經驗。"


def _ensure_recall_metadata(title: str, body: str) -> str:
    content = body.strip()
    additions: list[str] = []
    if not _has_section(content, "召回別名"):
        aliases = _recall_aliases(title, content)
        if aliases:
            additions.append("## 召回別名\n" + "、".join(aliases))
    if not _has_section(content, "召回實體"):
        entities = _title_entities(title, content)
        if entities:
            additions.append("## 召回實體\n" + "、".join(entities))
    if not _has_section(content, "狀態摘要"):
        additions.append("## 狀態摘要\n" + _status_line(content))
    if not _has_section(content, "自然語言入口"):
        additions.append(
            "## 自然語言入口\n"
            f"- {title} 是什麼？\n"
            f"- {title} 的狀態或結果如何？\n"
            f"- {title} 的根因、決策或修復方式是什麼？\n"
            f"- {title} 相關檔案或路徑在哪？"
        )
    if additions:
        content = content.rstrip() + "\n\n" + "\n\n".join(additions)
    return content


def write_topic(
    wiki_root: Path,
    title: str,
    body: str,
    tags: list[str] | None = None,
    topic_dir: str = "wiki/topics",
    recall_metadata: bool = True,
) -> Path:
    tags = tags or []
    today = date.today().isoformat()
    slug = slugify(title)
    path = wiki_root / topic_dir / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    tag_lines = "\n".join(f"  - {tag}" for tag in tags)
    frontmatter = (
        "---\n"
        f"title: {title}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "type: crystallized-memory\n"
        "tags:\n"
        f"{tag_lines if tag_lines else '  - memory'}\n"
        "---\n\n"
    )

    content = _ensure_recall_metadata(title, body) if recall_metadata else body.strip()
    if not content.startswith("#"):
        content = f"# {title}\n\n{content}"

    path.write_text(frontmatter + content + "\n", encoding="utf-8")
    return path


def append_log(wiki_root: Path, title: str, page_path: Path) -> None:
    log_path = wiki_root / "log.md"
    today = date.today().isoformat()
    link = page_path.stem
    entry = (
        f"\n## {today} crystallize | {title}\n\n"
        f"新增頁面：[[{link}]]\n"
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry)

