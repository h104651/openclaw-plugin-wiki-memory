from pathlib import Path
import tempfile
import unittest

from astor_wiki_memory.chunker import chunk_wiki
from astor_wiki_memory.crystallize import write_topic
from astor_wiki_memory.index_store import WikiMemoryIndex
from astor_wiki_memory.query_expansion import expand_query


class CoreTests(unittest.TestCase):
    def test_chunk_and_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki" / "topics").mkdir(parents=True)
            (root / "wiki" / "topics" / "openclaw-memory.md").write_text(
                """---
title: OpenClaw Memory Fix
tags:
  - openclaw
---

# OpenClaw Memory Fix

## Root Cause

Gemini embedding returned 3072 dimensions while the old LanceDB Pro schema expected 768 dimensions.

## Fix

Use the LLM Wiki as source of truth and rebuild a hybrid semantic index.
""",
                encoding="utf-8",
            )

            chunks = chunk_wiki(root)
            self.assertGreaterEqual(len(chunks), 2)

            db = root / "index.sqlite3"
            index = WikiMemoryIndex(db)
            try:
                count = index.rebuild(root, max_chars=1800, overlap_chars=160)
                self.assertEqual(count, len(chunks))
                results = index.recall("LanceDB Pro 768 3072 Gemini", limit=3)
                self.assertTrue(results)
                self.assertIn("OpenClaw", results[0].title)
            finally:
                index.close()

    def test_recall_expands_astor_natural_language_for_5m_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki" / "topics").mkdir(parents=True)
            (root / "wiki" / "topics" / "polymarket-clob-v2-upgrade.md").write_text(
                """---
title: Polymarket CLOB V2 升級紀錄
tags:
  - polymarket
---

# Polymarket CLOB V2 升級紀錄

## 研究版 v0.4：5m Shadow Only

SHADOW_5M_ENABLED=true. The oracle-lag-sniper shadow-only collector records 5m market candidates to shadow_5m_signals.jsonl and shadow_5m_resolutions.jsonl. It never submits trades.
""",
                encoding="utf-8",
            )

            index = WikiMemoryIndex(root / "index.sqlite3")
            try:
                index.rebuild(root, max_chars=1800, overlap_chars=160)
                results = index.recall("Oracle 五分鐘市場有沒有符合的交易", limit=3)
                self.assertTrue(results)
                self.assertIn("Polymarket CLOB", results[0].title)
            finally:
                index.close()

    def test_expand_query_stays_compact(self) -> None:
        expanded = expand_query("Oracle 五分鐘市場結果")
        self.assertIn("5m", expanded)
        self.assertIn("oracle-lag-sniper", expanded)
        self.assertLessEqual(len(expanded.split()), 18)

    def test_crystallize_adds_lightweight_recall_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_topic(root, "Oracle Lag Sniper 5分鐘市場 Shadow Research", "主要記錄 shadow_5m signals 與 resolutions。")
            text = path.read_text(encoding="utf-8")
            self.assertIn("## 召回別名", text)
            self.assertIn("## 自然語言入口", text)

    def test_sensitive_lines_are_redacted_before_indexing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki" / "entities").mkdir(parents=True)
            (root / "wiki" / "entities" / "bot.md").write_text(
                """# Bot Notes

## Credentials

Bot 私鑰已紀錄於 Hermes Memory
Normal operational note remains searchable.
""",
                encoding="utf-8",
            )

            chunks = chunk_wiki(root)
            joined = "\n".join(chunk.text for chunk in chunks)
            self.assertNotIn("私鑰", joined)
            self.assertIn("[REDACTED sensitive line]", joined)
            self.assertIn("Normal operational note", joined)

    def test_query_expansion_adds_intent_terms(self) -> None:
        expanded = expand_query("記憶功能目前狀態跟修復路徑")
        self.assertIn("status", expanded)
        self.assertIn("fix", expanded)
        self.assertIn("path", expanded)

    def test_crystallize_adds_entity_and_status_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_topic(root, "Astor Wiki Memory Recall Rerank", "完成 recall rerank 與 metadata 優化。")
            text = path.read_text(encoding="utf-8")
            self.assertIn("## 召回實體", text)
            self.assertIn("Astor Wiki Memory Recall Rerank", text)
            self.assertIn("## 狀態摘要", text)
            self.assertIn("相關檔案或路徑在哪", text)

    def test_title_heading_rerank_beats_body_only_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki" / "topics").mkdir(parents=True)
            (root / "wiki" / "topics" / "target.md").write_text(
                """# MiniMax CN Provider Fix

## 401 Endpoint Root Cause

Use China-region minimaxi endpoint and verify gateway restart.
""",
                encoding="utf-8",
            )
            (root / "wiki" / "topics" / "noise.md").write_text(
                """# Long Incident Archive

## Notes

This archive mentions MiniMax CN Provider Fix 401 Endpoint Root Cause once, but the page is mostly unrelated operational noise.
""",
                encoding="utf-8",
            )
            index = WikiMemoryIndex(root / "index.sqlite3")
            try:
                index.rebuild(root, max_chars=1800, overlap_chars=160)
                results = index.recall("MiniMax CN 401 endpoint root cause", limit=2)
                self.assertTrue(results)
                self.assertEqual(results[0].title, "MiniMax CN Provider Fix")
            finally:
                index.close()


if __name__ == "__main__":
    unittest.main()
