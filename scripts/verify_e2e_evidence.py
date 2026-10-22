#!/usr/bin/env python3
"""End-to-end evidence verification script for openclaw-plugin-wiki-memory PR #2.

Tests:
1. Environment and Commit SHA provenance
2. python -m unittest discover -s tests -v
3. node --test tests/test_plugin.mjs
4. Live E2E Scenario:
   - Write v1 memory
   - Verify v1 on disk
   - Write v2 replacing v1 (supersedes)
   - Verify non-destructive preservation of v1 & bidirectional linking
   - Incremental index sync
   - Standard Recall (asserts only v2 is returned, v1 is excluded)
   - Historical Recall (asserts v1 is retrievable when requested)
   - Wiki Lint validation
   - Lint error detection on intentional corrupted supersession
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from astor_wiki_memory.chunker import parse_frontmatter, chunk_markdown_file
from astor_wiki_memory.crystallize import write_topic
from astor_wiki_memory.index_store import WikiMemoryIndex
from astor_wiki_memory.lint import lint_wiki


def run_cmd(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


def banner(title: str) -> None:
    print(f"\n{'=' * 78}")
    print(f" {title}")
    print(f"{'=' * 78}")


def main() -> int:
    banner("1. Provenance & Execution Environment")
    code, sha, _ = run_cmd(["git", "rev-parse", "HEAD"])
    commit_sha = sha.strip() if code == 0 else "UNKNOWN"
    code, branch, _ = run_cmd(["git", "branch", "--show-current"])
    branch_name = branch.strip() if code == 0 else "UNKNOWN"

    print(f"Repository Root : {REPO_ROOT}")
    print(f"Git Commit SHA  : {commit_sha}")
    print(f"Git Branch      : {branch_name}")
    print(f"Platform / OS   : {platform.platform()}")
    print(f"Python Version  : {sys.version.split()[0]} ({sys.executable})")
    code, node_ver, _ = run_cmd(["node", "--version"])
    print(f"Node.js Version : {node_ver.strip()}")

    # -------------------------------------------------------------
    banner("2. Official Test Suite: Python Unittest (Native Windows)")
    print("Command: python -m unittest discover -s tests -v\n")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)
    py_pass = (proc.returncode == 0)
    print(f"Python Unittest Result: {'[PASS]' if py_pass else '[FAIL]'}")

    # -------------------------------------------------------------
    banner("3. Official Test Suite: Node.js Plugin TAP Tests")
    print("Command: node --test tests/test_plugin.mjs\n")
    code, node_out, node_err = run_cmd(["node", "--test", "tests/test_plugin.mjs"])
    print(node_out)
    if node_err:
        print(node_err)
    node_pass = (code == 0)
    print(f"Node.js Test Result: {'[PASS]' if node_pass else '[FAIL]'}")

    # -------------------------------------------------------------
    banner("4. Real Scenario E2E: Non-Destructive Revision & Recall Isolation")

    e2e_results: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        wiki_root = Path(tmp_dir)
        db_path = wiki_root / "index.sqlite"

        # Step 4.1: Write v1 memory
        print("\n[Step 4.1] Writing Memory v1 ('Auth Architecture' - Session Cookies)...")
        v1_body = (
            "## Architecture\n\n"
            "We use stateful Redis session cookies for user authentication.\n"
            "Tokens expire in 2 hours."
        )
        p1 = write_topic(
            wiki_root,
            "Auth Architecture",
            v1_body,
            tags=["auth", "security"],
            commit="5beb35b",
            source_repo="astor/backend",
            observed_at="2026-03-01",
            recall_metadata=False,
        )
        v1_meta, v1_text = parse_frontmatter(p1.read_text(encoding="utf-8"))
        step1_ok = (
            p1.exists()
            and v1_meta.get("status") == "active"
            and v1_meta.get("commit") == "5beb35b"
            and v1_meta.get("source_repo") == "astor/backend"
            and v1_meta.get("memory_id") == p1.stem
            and v1_meta.get("tags") == ["auth", "security"]
            and all(chunk.tags == ["auth", "security"] for chunk in chunk_markdown_file(p1, wiki_root, 1800, 160))
        )
        e2e_results.append((
            "4.1 Write v1 Memory with Provenance",
            step1_ok,
            f"File: {p1.name}, memory_id={v1_meta.get('memory_id')}, status={v1_meta.get('status')}",
        ))
        print(f"  -> Created file: {p1.name}")
        print(f"  -> File frontmatter: {json.dumps(v1_meta, indent=2, ensure_ascii=False)}")
        print(f"  -> Tags parsed correctly: {v1_meta.get('tags') == ['auth', 'security']}")

        # Step 4.2: Write v2 memory replacing v1
        print("\n[Step 4.2] Writing Memory v2 ('Auth Architecture' - Stateless Ed25519 JWT) superseding v1...")
        v2_body = (
            "## Architecture\n\n"
            "Migrated from session cookies to stateless asymmetric JWT tokens (Ed25519).\n"
            "Tokens are validated locally by microservices without Redis."
        )
        p2 = write_topic(
            wiki_root,
            "Auth Architecture",
            v2_body,
            tags=["auth", "security"],
            supersedes=p1.stem,
            commit="a1b2c3d",
            source_repo="astor/backend",
            observed_at="2026-04-01",
            recall_metadata=False,
        )
        v1_updated_meta, v1_updated_body = parse_frontmatter(p1.read_text(encoding="utf-8"))
        v2_meta, v2_body_read = parse_frontmatter(p2.read_text(encoding="utf-8"))

        step2_ok = (
            p2.exists()
            and p1.exists()                     # Non-destructive: v1 NOT deleted from disk!
            and p1 != p2                        # Distinct filenames preserved
            and v1_updated_meta.get("status") == "superseded"
            and v1_updated_meta.get("superseded_by") == p2.stem
            and v2_meta.get("status") == "active"
            and v2_meta.get("supersedes") == p1.stem
            and v2_meta.get("commit") == "a1b2c3d"
        )
        e2e_results.append((
            "4.2 Write v2 Superseding v1 (Non-destructive + Bidirectional Link)",
            step2_ok,
            f"v1({p1.name}) status={v1_updated_meta.get('status')} -> superseded_by={p2.stem}; v2({p2.name}) supersedes={p1.stem}",
        ))
        print(f"  -> Created v2: {p2.name}")
        print(f"  -> v1 on disk preserved: {p1.exists()}")
        print(f"  -> v1 updated metadata: status={v1_updated_meta.get('status')}, superseded_by={v1_updated_meta.get('superseded_by')}")
        print(f"  -> v2 metadata: status={v2_meta.get('status')}, supersedes={v2_meta.get('supersedes')}")

        # Step 4.3: Index synchronization (Incremental sync)
        print("\n[Step 4.3] Running Incremental Index Sync...")
        index = WikiMemoryIndex(db_path=db_path)
        try:
            chunks_synced = index.sync(wiki_root, max_chars=1800, overlap_chars=160)
            stats = index.stats()
            total_chunks = stats["total_chunks"]
            index_tag_rows = index.conn.execute(
                "SELECT DISTINCT tags_json FROM chunks WHERE memory_id IN (?, ?)",
                (p1.stem, p2.stem),
            ).fetchall()
            tags_in_index = bool(index_tag_rows) and all(
                json.loads(row["tags_json"]) == ["auth", "security"]
                for row in index_tag_rows
            )
            step3_ok = (chunks_synced >= 2 and total_chunks >= 2 and tags_in_index)
            e2e_results.append((
                "4.3 Incremental Index Sync",
                step3_ok,
                f"Chunks synced: {chunks_synced}, Total indexed chunks: {total_chunks}",
            ))
            print(f"  -> Synced chunks: {chunks_synced}, Index stats: {stats}")
            print(f"  -> Tags correctly indexed: {tags_in_index}")

            # Step 4.4: Standard Recall (History suppression check)
            print("\n[Step 4.4] Performing Standard Recall query='Auth Architecture' (include_history=False)...")
            std_results = index.recall("Auth Architecture", include_history=False, limit=5)
            std_ids = [r.memory_id for r in std_results]
            std_statuses = [r.status for r in std_results]

            # In standard recall: v1 (status=superseded) MUST be filtered out! Only v2 should be returned.
            has_v2_active = (p2.stem in std_ids)
            has_v1_superseded = (p1.stem in std_ids)
            step4_ok = (
                len(std_results) > 0
                and has_v2_active
                and not has_v1_superseded
                and all(r.status != "superseded" for r in std_results)
            )
            e2e_results.append((
                "4.4 Standard Recall Excludes Outdated Superseded Memories",
                step4_ok,
                f"Active v2 included: {has_v2_active}, Outdated v1 excluded: {not has_v1_superseded}, Count: {len(std_results)}",
            ))
            print(f"  -> Standard Recall Results ({len(std_results)} items returned):")
            for r in std_results:
                print(f"     * [{r.status}] memory_id={r.memory_id} commit={r.commit} summary={r.summary[:60]}...")

            # Step 4.5: Historical Recall (include_history=True)
            print("\n[Step 4.5] Performing Historical Recall query='Auth Architecture' (include_history=True)...")
            hist_results = index.recall("Auth Architecture", include_history=True, limit=10)
            hist_ids = [r.memory_id for r in hist_results]
            hist_has_v1 = (p1.stem in hist_ids)
            hist_has_v2 = (p2.stem in hist_ids)
            step5_ok = (hist_has_v1 and hist_has_v2)
            e2e_results.append((
                "4.5 Historical Recall Retrieves Both Active and Superseded Versions",
                step5_ok,
                f"Retrieved v1: {hist_has_v1}, Retrieved v2: {hist_has_v2}, Total: {len(hist_results)}",
            ))
            print(f"  -> Historical Recall Results ({len(hist_results)} items returned):")
            for r in hist_results:
                print(f"     * [{r.status}] memory_id={r.memory_id} commit={r.commit} supersedes={r.supersedes} superseded_by={r.superseded_by}")

        finally:
            index.close()

        # Step 4.6: Wiki Lint on valid wiki
        print("\n[Step 4.6] Executing Wiki Lint on Knowledge Base...")
        lint_report = lint_wiki(wiki_root)
        step6_ok = (
            lint_report["ok"] is True
            and len(lint_report["broken_links"]) == 0
            and len(lint_report["supersession_errors"]) == 0
            and len(lint_report["ambiguous_links"]) == 0
        )
        e2e_results.append((
            "4.6 Wiki Lint on Healthy Knowledge Base",
            step6_ok,
            f"ok={lint_report['ok']}, broken_links={len(lint_report['broken_links'])}, supersession_errors={len(lint_report['supersession_errors'])}",
        ))
        print(f"  -> Lint Report:\n{json.dumps(lint_report, indent=2, ensure_ascii=False)}")

        # Step 4.7: Corrupt supersession test (Assert Lint detects broken transaction)
        print("\n[Step 4.7] Testing Lint Fault Detection (Simulating Incomplete/Broken Transaction)...")
        # Inject a broken topic claiming to supersede a non-existent topic
        broken_file = wiki_root / "wiki" / "topics" / "broken-topic.md"
        broken_file.write_text(
            "---\n"
            "title: Broken Topic\n"
            "memory_id: broken-topic\n"
            "status: active\n"
            "supersedes: ghost-nonexistent-memory\n"
            "---\n\n"
            "# Broken Topic\n"
            "This claims to supersede a non-existent memory.\n",
            encoding="utf-8",
        )
        broken_report = lint_wiki(wiki_root)
        step7_ok = (
            broken_report["ok"] is False
            and len(broken_report["supersession_errors"]) > 0
        )
        e2e_results.append((
            "4.7 Wiki Lint Catches Broken/Incomplete Supersession Transactions",
            step7_ok,
            f"Detected supersession errors: {broken_report['supersession_errors']}",
        ))
        print(f"  -> Injected corrupted file: {broken_file.name}")
        print(f"  -> Lint detected errors: {broken_report['supersession_errors']}")
        print(f"  -> Lint ok={broken_report['ok']} (Correctly flagged as invalid!)")

    # -------------------------------------------------------------
    banner("5. Final Verification Summary")
    all_pass = py_pass and node_pass and all(r[1] for r in e2e_results)
    print(f"Commit Evaluated : {commit_sha}\n")
    print("Test Items:")
    print(f"  1. Python Unittest Suite : {'PASS' if py_pass else 'FAIL'}")
    print(f"  2. Node.js Plugin Tests   : {'PASS' if node_pass else 'FAIL'}")
    for name, status, detail in e2e_results:
        print(f"  {name} : {'PASS' if status else 'FAIL'} ({detail})")

    print(f"\nOVERALL VERDICT: {'ALL PASS [100% VERIFIED]' if all_pass else 'FAILURES DETECTED'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
