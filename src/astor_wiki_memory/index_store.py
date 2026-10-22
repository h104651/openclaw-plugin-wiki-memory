from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import replace
from pathlib import Path

from .chunker import chunk_wiki, chunk_markdown_file, discover_markdown_files
from .embeddings import cosine, create_embedder
from .models import Chunk, RecallResult
from .query_expansion import expand_query, should_expand_recall
from .text import estimate_tokens, tokenize


HISTORY_COLUMNS = {
    "memory_id": "TEXT NOT NULL DEFAULT ''",
    "topic_id": "TEXT NOT NULL DEFAULT ''",
    "status": "TEXT NOT NULL DEFAULT 'active'",
    "supersedes": "TEXT",
    "superseded_by": "TEXT",
    "source_repo": "TEXT",
    "commit_sha": "TEXT",
    "observed_at": "TEXT",
}


def looks_historical(query: str) -> bool:
    return bool(re.search(
        r"曾經|以前|當時|過去|歷史|舊版|之前|原本|as of|historical|previous|old version",
        query, re.I,
    ))


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  rel_path TEXT NOT NULL,
  title TEXT NOT NULL,
  heading TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  summary TEXT NOT NULL,
  scope TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  updated_at TEXT,
  mtime REAL NOT NULL,
  token_est INTEGER NOT NULL,
  embedding_json TEXT NOT NULL,
  memory_id TEXT NOT NULL DEFAULT '',
  topic_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  supersedes TEXT,
  superseded_by TEXT,
  source_repo TEXT,
  commit_sha TEXT,
  observed_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
USING fts5(id UNINDEXED, title, heading, summary, text);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class WikiMemoryIndex:
    def __init__(self, db_path: Path, embedding_backend: str = "hashing", dimensions: int = 384):
        self.db_path = db_path
        self.embedding_backend = embedding_backend
        self.dimensions = dimensions
        self.embedder = create_embedder(embedding_backend, dimensions)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate_history_columns()

    def _migrate_history_columns(self) -> None:
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(chunks)")}
        with self.conn:
            for name, ddl in HISTORY_COLUMNS.items():
                if name not in existing:
                    self.conn.execute(f"ALTER TABLE chunks ADD COLUMN {name} {ddl}")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_topic_state ON chunks(topic_id, status)"
            )

    def close(self) -> None:
        self.conn.close()

    def rebuild(self, wiki_root: Path, max_chars: int, overlap_chars: int) -> int:
        chunks = chunk_wiki(wiki_root, max_chars=max_chars, overlap_chars=overlap_chars)
        with self.conn:
            self.conn.execute("DELETE FROM chunks")
            self.conn.execute("DELETE FROM chunks_fts")
            for chunk in chunks:
                self.upsert_chunk(chunk)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                ("wiki_root", str(wiki_root)),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                ("embedding", json.dumps({"backend": self.embedding_backend, "dimensions": self.dimensions})),
            )
        return len(chunks)

    def sync(self, wiki_root: Path, max_chars: int, overlap_chars: int) -> int:
        """Only rechunk changed files; preserve all unchanged FTS and vectors."""
        wiki_root = Path(wiki_root).expanduser().resolve()
        new_embedding = json.dumps(
            {"backend": self.embedding_backend, "dimensions": self.dimensions}
        )
        root_row = self.conn.execute(
            "SELECT value FROM meta WHERE key='wiki_root'"
        ).fetchone()
        embedding_row = self.conn.execute(
            "SELECT value FROM meta WHERE key='embedding'"
        ).fetchone()
        if ((root_row and root_row["value"] != str(wiki_root))
                or (embedding_row and embedding_row["value"] != new_embedding)):
            return self.rebuild(wiki_root, max_chars, overlap_chars)
        current_files = discover_markdown_files(wiki_root)
        incoming = {str(p) for p in current_files}
        existing = {
            row["path"]: row["mtime"]
            for row in self.conn.execute(
                "SELECT path, MAX(mtime) AS mtime FROM chunks GROUP BY path"
            )
        }
        removed = set(existing) - incoming
        changed = [
            path for path in current_files
            if str(path) not in existing or path.stat().st_mtime != existing[str(path)]
        ]
        with self.conn:
            for path in sorted(removed):
                ids = self.conn.execute(
                    "SELECT id FROM chunks WHERE path=?", (path,)
                ).fetchall()
                for row in ids:
                    self.conn.execute("DELETE FROM chunks_fts WHERE id=?", (row["id"],))
                self.conn.execute("DELETE FROM chunks WHERE path=?", (path,))
            for path in changed:
                ids = self.conn.execute(
                    "SELECT id FROM chunks WHERE path=?", (str(path),)
                ).fetchall()
                for row in ids:
                    self.conn.execute("DELETE FROM chunks_fts WHERE id=?", (row["id"],))
                self.conn.execute("DELETE FROM chunks WHERE path=?", (str(path),))
                for chunk in chunk_markdown_file(path, wiki_root, max_chars, overlap_chars):
                    self.upsert_chunk(chunk)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('wiki_root',?)",
                (str(wiki_root),)
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('embedding',?)",
                (new_embedding,)
            )
        return int(self.conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"])

    def upsert_chunk(self, chunk: Chunk) -> None:
        embedding = self.embedder.embed("\n".join([chunk.title, chunk.heading, chunk.text]))
        self.conn.execute(
            """
            INSERT OR REPLACE INTO chunks
            (id, path, rel_path, title, heading, ordinal, text, summary, scope, tags_json,
             updated_at, mtime, token_est, embedding_json, memory_id, topic_id, status,
             supersedes, superseded_by, source_repo, commit_sha, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.id,
                str(chunk.path),
                chunk.rel_path,
                chunk.title,
                chunk.heading,
                chunk.ordinal,
                chunk.text,
                chunk.summary,
                chunk.scope,
                json.dumps(chunk.tags, ensure_ascii=False),
                chunk.updated_at,
                chunk.mtime,
                chunk.token_est,
                json.dumps(embedding),
                chunk.memory_id,
                chunk.topic_id,
                chunk.status,
                chunk.supersedes,
                chunk.superseded_by,
                chunk.source_repo,
                chunk.commit,
                chunk.observed_at,
            ),
        )
        self.conn.execute("DELETE FROM chunks_fts WHERE id = ?", (chunk.id,))
        self.conn.execute(
            "INSERT INTO chunks_fts(id, title, heading, summary, text) VALUES (?, ?, ?, ?, ?)",
            (chunk.id, chunk.title, chunk.heading, chunk.summary, chunk.text),
        )

    def stats(self) -> dict[str, object]:
        total = self.conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
        scopes = {
            row["scope"]: row["c"]
            for row in self.conn.execute("SELECT scope, COUNT(*) AS c FROM chunks GROUP BY scope ORDER BY c DESC")
        }
        return {"db_path": str(self.db_path), "total_chunks": total, "scopes": scopes}

    def get(self, chunk_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()

    def recall(
        self,
        query: str,
        limit: int = 5,
        max_tokens: int = 1200,
        scope: str | None = None,
        min_score: float = 0.05,
        include_history: bool = False,
    ) -> list[RecallResult]:
        include_history = include_history or looks_historical(query)
        first_pass = self._recall_once(
            query,
            limit=limit,
            max_tokens=max_tokens,
            scope=scope,
            min_score=min_score,
            include_history=include_history,
        )
        best_score = first_pass[0].score if first_pass else 0.0
        if not should_expand_recall(len(first_pass), best_score):
            return first_pass

        expanded_query = expand_query(query)
        if expanded_query == query:
            return first_pass

        expanded_pass = self._recall_once(
            expanded_query,
            limit=max(limit * 2, limit + 3),
            max_tokens=max_tokens * 2,
            scope=scope,
            min_score=min_score,
            include_history=include_history,
        )
        return self._merge_recall_results(
            first_pass,
            expanded_pass,
            limit=limit,
            max_tokens=max_tokens,
        )

    def _recall_once(
        self,
        query: str,
        limit: int,
        max_tokens: int,
        scope: str | None,
        min_score: float,
        include_history: bool,
    ) -> list[RecallResult]:
        fts = self._fts_scores(query, limit=max(limit * 4, 20), scope=scope)
        vector = self._vector_scores(query, limit=max(limit * 6, 30), scope=scope)
        ids = set(fts) | set(vector)
        if not ids:
            return []

        max_fts = max(fts.values(), default=0.0) or 1.0
        rows = self._rows_by_ids(ids)
        # A current-state question must not surface an outdated revision.
        # If an old revision matched, proactively include its active successor,
        # even when the successor was outside the initial top-N candidates.
        successor_ids: set[str] = set()
        if not include_history:
            for row in rows:
                if row["status"] == "superseded" or row["superseded_by"]:
                    successors = self.conn.execute(
                        "SELECT id FROM chunks WHERE topic_id=? AND status='active' LIMIT 12",
                        (row["topic_id"],),
                    ).fetchall()
                    successor_ids.update(item["id"] for item in successors)
            rows.extend(self._rows_by_ids(successor_ids - ids))
        ranked: list[RecallResult] = []
        query_vector = None
        for row in rows:
            if not include_history and (row["status"] == "superseded" or row["superseded_by"]):
                continue
            chunk_id = row["id"]
            fts_score = fts.get(chunk_id, 0.0) / max_fts
            vector_score = vector.get(chunk_id, 0.0)
            if chunk_id in successor_ids and chunk_id not in vector:
                if query_vector is None:
                    query_vector = self.embedder.embed(query)
                try:
                    vector_score = max(0.0, cosine(query_vector, json.loads(row["embedding_json"])))
                except (ValueError, TypeError):
                    vector_score = 0.0
            field_score = self._field_match_score(query, row)
            score = (0.50 * vector_score) + (0.38 * fts_score) + (0.12 * field_score)
            if score < min_score:
                continue
            ranked.append(
                RecallResult(
                    id=chunk_id,
                    score=round(float(score), 4),
                    fts_score=round(float(fts_score), 4),
                    vector_score=round(float(vector_score), 4),
                    title=row["title"],
                    summary=row["summary"],
                    path=row["path"],
                    rel_path=row["rel_path"],
                    heading=row["heading"],
                    scope=row["scope"],
                    token_est=estimate_tokens(row["summary"]),
                    memory_id=row["memory_id"] or Path(row["rel_path"]).stem,
                    topic_id=row["topic_id"],
                    status=row["status"],
                    supersedes=row["supersedes"],
                    superseded_by=row["superseded_by"],
                    source_repo=row["source_repo"],
                    commit=row["commit_sha"],
                    observed_at=row["observed_at"] or "",
                )
            )
        ranked.sort(key=lambda r: r.score, reverse=True)
        return self._select_with_budget(ranked, limit=limit, max_tokens=max_tokens)

    def _select_with_budget(
        self,
        ranked: list[RecallResult],
        limit: int,
        max_tokens: int,
    ) -> list[RecallResult]:
        selected: list[RecallResult] = []
        used = 0
        for result in ranked:
            if len(selected) >= limit:
                break
            if used + result.token_est > max_tokens and selected:
                break
            selected.append(result)
            used += result.token_est
        return selected

    def _merge_recall_results(
        self,
        first_pass: list[RecallResult],
        expanded_pass: list[RecallResult],
        limit: int,
        max_tokens: int,
    ) -> list[RecallResult]:
        by_id: dict[str, RecallResult] = {}
        first_ids = {result.id for result in first_pass}
        for result in expanded_pass:
            if result.id not in first_ids:
                # Expanded matches are intentionally a second pass. Give them a
                # small recall boost so buried alias hits are not crowded out by
                # the noisy exact-query result set.
                result = replace(result, score=round(float(result.score + 0.08), 4))
            by_id[result.id] = result
        for result in first_pass:
            # Preserve exact-query winners when duplicated; exact wording should win ties.
            by_id[result.id] = result
        ranked = sorted(by_id.values(), key=lambda r: r.score, reverse=True)
        return self._select_with_budget(ranked, limit=limit, max_tokens=max_tokens)

    def _rows_by_ids(self, ids: set[str]) -> list[sqlite3.Row]:
        placeholders = ",".join("?" for _ in ids)
        return list(self.conn.execute(f"SELECT * FROM chunks WHERE id IN ({placeholders})", tuple(ids)))

    def _query_terms(self, query: str) -> list[str]:
        terms: list[str] = []

        def add(term: str) -> None:
            term = term.strip().lower()
            if term and term not in terms:
                terms.append(term)

        for latin in re.findall(r"[A-Za-z0-9_][A-Za-z0-9_\-]*", query):
            add(latin)
        for cjk in re.findall(r"[\u4e00-\u9fff]{2,}", query):
            add(cjk)
            if len(cjk) > 2:
                for i in range(len(cjk) - 1):
                    add(cjk[i : i + 2])
        for term in tokenize(query):
            if len(term) > 1 and not re.fullmatch(r"[\u4e00-\u9fff]", term):
                add(term)
        return terms[:32]

    def _field_match_score(self, query: str, row: sqlite3.Row) -> float:
        terms = self._query_terms(query)
        if not terms:
            return 0.0

        fields = (
            (str(row["title"] or "").lower(), 1.0),
            (str(row["heading"] or "").lower(), 0.9),
            (str(row["summary"] or "").lower(), 0.45),
            (str(row["rel_path"] or "").lower(), 0.35),
            (str(row["tags_json"] or "").lower(), 0.25),
        )
        weighted_hits = 0.0
        total_weight = 0.0
        for term in terms:
            term_weight = 1.0 if len(term) > 2 else 0.7
            total_weight += term_weight
            best = 0.0
            for haystack, field_weight in fields:
                if term in haystack:
                    best = max(best, field_weight)
            weighted_hits += best * term_weight
        if total_weight <= 0:
            return 0.0
        return max(0.0, min(1.0, weighted_hits / total_weight))

    def _fts_query(self, query: str) -> str:
        terms: list[str] = []

        def add(term: str) -> None:
            term = term.strip().lower()
            if term and term not in terms:
                terms.append(term)

        for latin in re.findall(r"[A-Za-z0-9_][A-Za-z0-9_\-]*", query):
            add(latin)
        for cjk in re.findall(r"[\u4e00-\u9fff]{2,}", query):
            add(cjk)
            if len(cjk) > 2:
                for i in range(len(cjk) - 1):
                    add(cjk[i : i + 2])

        # Fall back to the older tokenizer for unusual mixed strings, but avoid
        # single Chinese characters because they produce very noisy FTS matches.
        for term in tokenize(query):
            if len(term) > 1 and not re.fullmatch(r"[\u4e00-\u9fff]", term):
                add(term)
        if not terms:
            return ""
        return " OR ".join(f'"{t}"' for t in terms[:24])

    def _fts_scores(self, query: str, limit: int, scope: str | None) -> dict[str, float]:
        fts_query = self._fts_query(query)
        if not fts_query:
            return {}
        params: list[object] = [fts_query]
        scope_sql = ""
        if scope:
            scope_sql = "AND chunks.scope = ?"
            params.append(scope)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT chunks.id AS id, -bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks ON chunks.id = chunks_fts.id
            WHERE chunks_fts MATCH ? {scope_sql}
            ORDER BY bm25(chunks_fts)
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return {row["id"]: max(0.0, float(row["score"])) for row in rows}

    def _vector_scores(self, query: str, limit: int, scope: str | None) -> dict[str, float]:
        query_vec = self.embedder.embed(query)
        params: tuple[object, ...] = (scope,) if scope else ()
        where = "WHERE scope = ?" if scope else ""
        rows = self.conn.execute(f"SELECT id, embedding_json FROM chunks {where}", params).fetchall()
        scored: list[tuple[str, float]] = []
        for row in rows:
            try:
                vec = json.loads(row["embedding_json"])
            except json.JSONDecodeError:
                continue
            score = max(0.0, cosine(query_vec, vec))
            if score > 0:
                scored.append((row["id"], score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return dict(scored[:limit])

