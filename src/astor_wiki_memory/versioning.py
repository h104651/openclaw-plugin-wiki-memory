"""Durable, non-destructive Wiki page revisions.

Markdown remains the source of truth. SQLite is a disposable lookup cache.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import json
import os
from pathlib import Path
import re
import tempfile
import time
from uuid import uuid4

from .chunker import parse_frontmatter
from .text import slugify


_SHA = re.compile(r"^[a-fA-F0-9]{7,40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MEMORY_ID = re.compile(r"^[\w.\-]+$", re.UNICODE)


def _scalar(value: str) -> str:
    """A JSON string is also a YAML 1.2 safe quoted scalar."""
    return json.dumps(value, ensure_ascii=False)


def _validate(commit: str | None, source_repo: str | None, observed_at: str | None) -> None:
    if commit and not _SHA.fullmatch(commit):
        raise ValueError("commit must be a hexadecimal Git SHA (7-40 characters)")
    if source_repo and not _REPO.fullmatch(source_repo):
        raise ValueError("source_repo must use owner/repository format")
    if observed_at:
        try:
            date.fromisoformat(observed_at)
        except ValueError as exc:
            raise ValueError("observed_at must be YYYY-MM-DD") from exc


@contextmanager
def _writer_lock(wiki_root: Path):
    """Inter-process lock; stale locks can be recovered after a crash."""
    wiki_root.mkdir(parents=True, exist_ok=True)
    lock_path = wiki_root / ".wiki-memory-writer.lock"
    deadline = time.monotonic() + 8
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 120:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError("Wiki memory writer lock is held")
            time.sleep(0.05)
    try:
        os.close(fd)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".wiki-revision-",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _find_revision(wiki_root: Path, memory_id: str) -> tuple[Path, dict, str]:
    if not _MEMORY_ID.fullmatch(memory_id):
        raise ValueError("Invalid supersedes memory ID")
    matches = []
    for path in (wiki_root / "wiki" / "topics").rglob("*.md"):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        if path.stem == memory_id or meta.get("memory_id") == memory_id:
            matches.append((path, meta, body))
    if len(matches) != 1:
        raise ValueError(f"supersedes must identify exactly one existing Wiki topic: {memory_id}")
    return matches[0]


def _upsert_frontmatter(raw: str, key: str, value: str) -> str:
    if raw.startswith("---\n"):
        match = re.search(r"(?m)^---\s*$", raw[4:])
        if match is None:
            raise ValueError("Invalid frontmatter in superseded page")
        end = match.end() + 4
        header, rest = raw[:end], raw[end:]
        pattern = re.compile(rf"(?m)^{re.escape(key)}:.*$")
        field = f"{key}: {value}"
        if pattern.search(header):
            header = pattern.sub(field, header, count=1)
        else:
            header = header.replace("---\n", f"---\n{field}\n", 1)
        return header + rest
    return f"---\n{key}: {value}\n---\n\n" + raw


def _mark_old_revision(raw: str, new_id: str) -> str:
    raw = _upsert_frontmatter(raw, "status", "superseded")
    raw = _upsert_frontmatter(raw, "superseded_by", new_id)
    if f"[[{new_id}]]" not in raw:
        banner = f"> ⚠️ 此頁面已被 [[{new_id}]] 取代；原始歷史內容保留。\n\n"
        front = re.match(r"^---\n.*?\n---\n", raw, re.S)
        if front:
            pos = front.end()
            raw = raw[:pos] + "\n" + banner + raw[pos:].lstrip("\n")
        else:
            raw = banner + raw
    return raw


def write_versioned_topic(
    wiki_root: Path, title: str, content: str, tags: list[str],
    topic_dir: str = "wiki/topics", commit: str | None = None,
    source_repo: str | None = None, observed_at: str | None = None,
    supersedes: str | None = None, superseded_by: str | None = None,
) -> Path:
    """Create a unique page; an update links its predecessor without erasing its claims."""
    _validate(commit, source_repo, observed_at)
    if supersedes and superseded_by:
        raise ValueError("Use either supersedes (new version) or superseded_by (legacy old version)")
    today = date.today().isoformat()
    slug = slugify(title)
    wiki_root = Path(wiki_root).expanduser()
    root_topics = (wiki_root / "wiki" / "topics").resolve()
    folder = (wiki_root / topic_dir).resolve()
    if folder != root_topics and root_topics not in folder.parents:
        raise ValueError("topic_dir must remain inside wiki/topics")

    with _writer_lock(wiki_root):
        prior_path = None
        old_raw = None
        topic_id = slug
        if supersedes:
            prior_path, meta, _ = _find_revision(wiki_root, supersedes)
            if str(meta.get("status", "active")) == "superseded" or meta.get("superseded_by"):
                raise ValueError("Cannot supersede a revision that was already superseded")
            old_raw = prior_path.read_text(encoding="utf-8")
            topic_id = str(meta.get("topic_id") or slugify(str(meta.get("title") or prior_path.stem)))
        memory_id = f"{slug}--{today.replace('-', '')}-{uuid4().hex[:12]}"
        path = folder / f"{memory_id}.md"
        while path.exists():
            memory_id = f"{slug}--{today.replace('-', '')}-{uuid4().hex[:12]}"
            path = folder / f"{memory_id}.md"

        fields = [
            ("schema_version", "2"),
            ("memory_id", memory_id),
            ("topic_id", _scalar(topic_id)),
            ("title", _scalar(title)),
            ("created", today),
            ("updated", today),
            ("recorded_at", today),
            ("observed_at", observed_at or today),
            ("status", "superseded" if superseded_by else "active"),
        ]
        if supersedes:
            fields.append(("supersedes", supersedes))
        if superseded_by:
            fields.append(("superseded_by", superseded_by))
        if commit:
            fields.append(("commit", commit.lower()))
        if source_repo:
            fields.append(("source_repo", source_repo))
        frontmatter = "---\n" + "".join(f"{key}: {value}\n" for key, value in fields)
        frontmatter += "type: crystallized-memory\ntags:\n"
        frontmatter += "".join(f"  - {_scalar(tag)}\n" for tag in (tags or ["memory"]))
        frontmatter += "---\n\n"

        if superseded_by:
            content = f"> ⚠️ 此頁面已被 [[{superseded_by}]] 取代。\n\n" + content
        _atomic_write(path, frontmatter + content.rstrip() + "\n")
        if prior_path is not None and old_raw is not None:
            try:
                _atomic_write(prior_path, _mark_old_revision(old_raw, memory_id))
            except Exception:
                path.unlink(missing_ok=True)
                raise
    return path
