"""Versioned Wiki memory regression tests."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
import tempfile
import unittest

from astor_wiki_memory.chunker import parse_frontmatter, chunk_markdown_file, _tags_from
from astor_wiki_memory.cli import main
from astor_wiki_memory.crystallize import write_topic
from astor_wiki_memory.index_store import WikiMemoryIndex
from astor_wiki_memory.lint import lint_wiki


class MemoryHistoryTests(unittest.TestCase):
    def test_same_title_creates_distinct_files_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = write_topic(root, "Latency: tuning", "Original historical choice.", recall_metadata=False)
            before = first.read_text(encoding="utf-8")
            second = write_topic(root, "Latency: tuning", "Another independent observation.", recall_metadata=False)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_text(encoding="utf-8"), before)
            first_meta, _ = parse_frontmatter(before)
            second_meta, _ = parse_frontmatter(second.read_text(encoding="utf-8"))
            self.assertEqual(first_meta["topic_id"], second_meta["topic_id"])
            self.assertNotEqual(first_meta["memory_id"], second_meta["memory_id"])

    def test_supersession_preserves_old_claims_and_links_both_sides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = write_topic(
                root, "WebRTC latency", "Old baseline was 100 milliseconds.",
                commit="abc1234", source_repo="h104651/MirrorBridge",
                recall_metadata=False,
            )
            new = write_topic(
                root, "WebRTC latency", "New measured latency is 30 milliseconds.",
                commit="def5678", source_repo="h104651/MirrorBridge",
                supersedes=old.stem, recall_metadata=False,
            )
            old_meta, old_body = parse_frontmatter(old.read_text(encoding="utf-8"))
            new_meta, new_body = parse_frontmatter(new.read_text(encoding="utf-8"))
            self.assertEqual(old_meta["status"], "superseded")
            self.assertEqual(old_meta["superseded_by"], new.stem)
            self.assertEqual(new_meta["supersedes"], old.stem)
            self.assertEqual(new_meta["status"], "active")
            self.assertEqual(new_meta["topic_id"], old_meta["topic_id"])
            self.assertEqual(new_meta["source_repo"], "h104651/MirrorBridge")
            self.assertIn("Old baseline was 100 milliseconds.", old_body)
            self.assertIn("30 milliseconds.", new_body)
            self.assertTrue(lint_wiki(root)["ok"])

    def test_unknown_or_superseded_predecessor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                write_topic(root, "Latency", "New", supersedes="missing")
            old = write_topic(root, "Latency", "Original", recall_metadata=False)
            write_topic(root, "Latency", "Revised", supersedes=old.stem, recall_metadata=False)
            with self.assertRaises(ValueError):
                write_topic(root, "Latency", "Another", supersedes=old.stem)

    def test_invalid_commit_and_date_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                write_topic(root, "Bad SHA", "Content", commit="not-a-sha")
            with self.assertRaises(ValueError):
                write_topic(root, "Bad Date", "Content", observed_at="2026-13-40")
            with self.assertRaises(ValueError):
                write_topic(root, "Bad Repo", "Content", source_repo="../repo")

    def test_json_quoted_yaml_roundtrips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_topic(root, 'A: "quoted" title', "Content", recall_metadata=False)
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(meta["title"], 'A: "quoted" title')

    def test_current_search_ignores_superseded_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = write_topic(
                root, "WebRTC Playout latency", "WebRTC Playout latency previously measured 100 milliseconds.",
                recall_metadata=False,
            )
            latest = write_topic(
                root, "WebRTC Playout latency", "WebRTC Playout latency now measured 30 milliseconds.",
                supersedes=old.stem, recall_metadata=False,
            )
            index = WikiMemoryIndex(root / "index.db")
            try:
                index.rebuild(root, max_chars=1800, overlap_chars=160)
                current = index.recall("WebRTC Playout latency", limit=5)
                self.assertTrue(current)
                self.assertTrue(all(result.status != "superseded" for result in current))
                self.assertIn(latest.stem, {result.memory_id for result in current})
                historical = index.recall("WebRTC Playout latency", include_history=True, limit=10)
                self.assertIn(old.stem, {result.memory_id for result in historical})
                self.assertIn(latest.stem, {result.memory_id for result in historical})
            finally:
                index.close()

    def test_incremental_sync_adds_changed_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = write_topic(root, "Indexer check", "This original page includes enough text to index.", recall_metadata=False)
            index = WikiMemoryIndex(root / "index.sqlite")
            try:
                count_old = index.rebuild(root, max_chars=1800, overlap_chars=160)
                self.assertGreater(count_old, 0)
                newer = write_topic(
                    root, "Indexer check", "This newer page includes enough text to index.",
                    supersedes=old.stem, recall_metadata=False,
                )
                count_new = index.sync(root, max_chars=1800, overlap_chars=160)
                self.assertGreater(count_new, count_old)
                self.assertEqual(count_new, index.sync(root, 1800, 160))
                self.assertEqual(
                    index.conn.execute("SELECT status FROM chunks WHERE memory_id=? LIMIT 1", (old.stem,)).fetchone()["status"],
                    "superseded",
                )
                self.assertIsNotNone(index.conn.execute(
                    "SELECT id FROM chunks WHERE memory_id=? LIMIT 1", (newer.stem,)
                ).fetchone())
            finally:
                index.close()

    def test_migration_adds_columns_to_legacy_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.sqlite"
            conn = sqlite3.connect(path)
            try:
                conn.execute("""CREATE TABLE chunks (
                    id TEXT PRIMARY KEY, path TEXT, rel_path TEXT, title TEXT,
                    heading TEXT, ordinal INTEGER, text TEXT, summary TEXT,
                    scope TEXT, tags_json TEXT, updated_at TEXT, mtime REAL,
                    token_est INTEGER, embedding_json TEXT
                )""")
                conn.commit()
            finally:
                conn.close()
            index = WikiMemoryIndex(path)
            try:
                cols = {row["name"] for row in index.conn.execute("PRAGMA table_info(chunks)")}
                self.assertTrue({"memory_id", "topic_id", "status", "commit_sha", "superseded_by"} <= cols)
            finally:
                index.close()

    def test_missing_root_is_not_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = lint_wiki(Path(tmp) / "nonexistent")
            self.assertFalse(report["ok"])
            self.assertTrue(report["errors"])

    def test_lint_ignores_code_samples_and_handles_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            topic = root / "wiki" / "topics"
            topic.mkdir(parents=True)
            fence = chr(96) * 3
            (root / "index.md").write_text(
                "# Index\n[[wiki/topics/exists]]\n", encoding="utf-8"
            )
            (topic / "exists.md").write_text(
                f"# Exists\n{fence}md\n[[not-a-real-link]]\n{fence}\n"
                + "Inline " + chr(96) + "[[also-not-a-link]]" + chr(96) + "\n",
                encoding="utf-8",
            )
            report = lint_wiki(root)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["orphan_topics"], [])

    def test_lint_flags_ambiguous_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki" / "topics").mkdir(parents=True)
            (root / "wiki" / "entities").mkdir(parents=True)
            (root / "index.md").write_text("# Index\n[[same]]", encoding="utf-8")
            (root / "wiki" / "topics" / "same.md").write_text("# Topic", encoding="utf-8")
            (root / "wiki" / "entities" / "same.md").write_text("# Entity", encoding="utf-8")
            report = lint_wiki(root)
            self.assertFalse(report["ok"])
            self.assertEqual(len(report["ambiguous_links"]), 1)

    def test_cli_writes_revisions_and_gets_historical_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki" / "topics").mkdir(parents=True)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({
                "wiki_root": str(root),
                "index_db": str(root / "data.sqlite"),
            }), encoding="utf-8")
            body_path = root / "body.txt"
            body_path.write_text("WebRTC playout latency setup initially used 100 milliseconds.", encoding="utf-8")
            def call(*args: str):
                output = io.StringIO()
                with redirect_stdout(output):
                    rc = main(["--config", str(config_path), *args])
                return rc, json.loads(output.getvalue())
            rc, old = call("crystallize", "--title", "WebRTC setup",
                           "--body-file", str(body_path))
            self.assertEqual(rc, 0)
            body_path.write_text("WebRTC playout latency setup improved to 30 milliseconds.", encoding="utf-8")
            rc, newest = call("crystallize", "--title", "WebRTC setup",
                              "--body-file", str(body_path),
                              "--supersedes", old["memory_id"])
            self.assertEqual(rc, 0)
            self.assertNotEqual(old["memory_id"], newest["memory_id"])
            self.assertEqual(call("index")[0], 0)
            rc, search = call("recall", "WebRTC setup latency", "--json")
            self.assertEqual(rc, 0)
            self.assertTrue(search["results"])
            self.assertTrue(all(item["status"] == "active" for item in search["results"]))
            rc, history = call("recall", "WebRTC setup latency", "--include-history", "--json")
            self.assertEqual(rc, 0)
            self.assertIn("superseded", {item["status"] for item in history["results"]})

    def test_lint_detects_crash_before_reverse_link_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = write_topic(root, "Crash check", "Original content", recall_metadata=False)
            new = write_topic(root, "Crash check", "Revised content", supersedes=old.stem, recall_metadata=False)
            old_file = old.read_text(encoding="utf-8")
            old_file = old_file.replace("status: superseded", "status: active")
            old_file = old_file.replace(f"superseded_by: {new.stem}", "")
            old.write_text(old_file, encoding="utf-8")
            report = lint_wiki(root)
            self.assertFalse(report["ok"])
            self.assertIn("predecessor_missing_reverse_link", {
                item["reason"] for item in report["supersession_errors"]
            })

    def test_lint_warns_if_multiple_active_revisions_share_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_topic(root, "Repeated title", "First observation", recall_metadata=False)
            write_topic(root, "Repeated title", "Second independent observation", recall_metadata=False)
            report = lint_wiki(root)
            self.assertTrue(report["ok"], report)
            self.assertEqual(len(report["active_topic_conflicts"]), 1)

    def test_yaml_tags_list_survives_crystallize_chunking_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = ["auth", "security", "中文 標籤", "tag:with-colon"]
            path = write_topic(
                root,
                "Auth tags memory",
                "## Scope\\n\\nJWT authentication tags must remain searchable after indexing.",
                tags=expected,
                recall_metadata=False,
            )
            metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["tags"], expected)
            chunks = chunk_markdown_file(path, root, max_chars=1800, overlap_chars=160)
            self.assertTrue(chunks)
            self.assertEqual(chunks[0].tags, expected)
            index = WikiMemoryIndex(root / "tags.sqlite")
            try:
                index.rebuild(root, max_chars=1800, overlap_chars=160)
                row = index.conn.execute(
                    "SELECT tags_json FROM chunks WHERE memory_id=? LIMIT 1", (path.stem,)
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(json.loads(row["tags_json"]), expected)
            finally:
                index.close()

    def test_yaml_tags_csv_style_backwards_compatible(self) -> None:
        metadata, body = parse_frontmatter(
            '---\\ntitle: Example\\ntags: alpha, beta\\nstatus: active\\n---\\n\\n# Example\\n'
        )
        self.assertEqual(metadata["tags"], "alpha, beta")
        self.assertEqual(metadata["status"], "active")
        self.assertEqual(_tags_from(metadata), ["alpha", "beta"])
        self.assertIn("# Example", body)


if __name__ == "__main__":
    unittest.main()
