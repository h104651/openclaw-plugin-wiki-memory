from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import Chunk
from .text import estimate_tokens, normalize_text, redact_sensitive_text, slugify, summarize


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def parse_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    meta: dict[str, str | list[str]] = {}
    lines = match.group(1).splitlines()
    current_key: str | None = None
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key:
            existing = meta.setdefault(current_key, [])
            if isinstance(existing, list):
                existing.append(line[4:].strip())
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip().strip('"')
            meta[current_key] = value
    return meta, text[match.end() :]


def discover_markdown_files(wiki_root: Path) -> list[Path]:
    ignored_parts = {".git", "node_modules", ".obsidian"}
    ignored_names = {".wiki-schema.md", "log.md", "index.md", "overview.md"}
    files: list[Path] = []
    for path in wiki_root.rglob("*.md"):
        if any(part in ignored_parts for part in path.parts):
            continue
        if path.name in ignored_names:
            continue
        files.append(path)
    return sorted(files)


def _scope_from_rel_path(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if not parts:
        return "wiki"
    if parts[0] == "wiki" and len(parts) > 1:
        return f"wiki:{parts[1]}" if len(parts) > 2 else "wiki"
    if parts[0] == "raw":
        return "raw"
    return "wiki"


def _title_from(meta: dict[str, str | list[str]], body: str, fallback: str) -> str:
    title = meta.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            return match.group(2).strip()
    return fallback


def _tags_from(meta: dict[str, str | list[str]]) -> list[str]:
    tags = meta.get("tags")
    if isinstance(tags, list):
        return [t for t in tags if t]
    if isinstance(tags, str) and tags:
        return [t.strip() for t in tags.split(",") if t.strip()]
    return []


def _split_sections(body: str, title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_heading = title
    current_lines: list[str] = []

    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = match.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, current_lines))

    return [(heading, "\n".join(lines).strip()) for heading, lines in sections if "\n".join(lines).strip()]


def _split_large_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    clean = text.strip()
    if len(clean) <= max_chars:
        return [clean]

    paragraphs = re.split(r"\n\s*\n", clean)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap_chars:] if overlap_chars > 0 else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
        else:
            for start in range(0, len(paragraph), max_chars - overlap_chars):
                chunks.append(paragraph[start : start + max_chars].strip())
            current = ""
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def make_chunk_id(rel_path: str, heading: str, ordinal: int) -> str:
    seed = f"{rel_path}::{slugify(heading)}::{ordinal}".encode("utf-8")
    return hashlib.sha1(seed).hexdigest()[:16]


def chunk_markdown_file(path: Path, wiki_root: Path, max_chars: int, overlap_chars: int) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(raw)
    body = redact_sensitive_text(body)
    rel_path = path.relative_to(wiki_root).as_posix()
    title = _title_from(meta, body, path.stem)
    tags = _tags_from(meta)
    updated_at = str(meta.get("updated") or meta.get("created") or "")
    scope = _scope_from_rel_path(rel_path)
    stat = path.stat()

    chunks: list[Chunk] = []
    ordinal = 0
    for heading, section_text in _split_sections(body, title):
        for piece in _split_large_text(section_text, max_chars=max_chars, overlap_chars=overlap_chars):
            normalized = normalize_text(piece)
            if len(normalized) < 20:
                continue
            chunk_id = make_chunk_id(rel_path, heading, ordinal)
            chunks.append(
                Chunk(
                    id=chunk_id,
                    path=path,
                    rel_path=rel_path,
                    title=title,
                    heading=heading,
                    ordinal=ordinal,
                    text=piece,
                    summary=summarize(piece),
                    scope=scope,
                    tags=tags,
                    updated_at=updated_at,
                    mtime=stat.st_mtime,
                    token_est=estimate_tokens(piece),
                )
            )
            ordinal += 1
    return chunks


def chunk_wiki(wiki_root: Path, max_chars: int = 1800, overlap_chars: int = 160) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in discover_markdown_files(wiki_root):
        chunks.extend(chunk_markdown_file(path, wiki_root, max_chars=max_chars, overlap_chars=overlap_chars))
    return chunks
