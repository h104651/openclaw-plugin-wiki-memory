from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .crystallize import append_log, write_topic
from .index_store import WikiMemoryIndex
from .lint import lint_wiki
from .text import estimate_tokens


def _open_index(args: argparse.Namespace) -> tuple[object, WikiMemoryIndex]:
    config = load_config(args.config)
    db_path = Path(args.db).expanduser() if args.db else config.index_db
    index = WikiMemoryIndex(
        db_path=db_path,
        embedding_backend=config.embedding.backend,
        dimensions=config.embedding.dimensions,
    )
    return config, index


def cmd_index(args: argparse.Namespace) -> int:
    config, index = _open_index(args)
    try:
        if args.rebuild and index.db_path.exists():
            index.close()
            index.db_path.unlink()
            index = WikiMemoryIndex(
                db_path=index.db_path,
                embedding_backend=config.embedding.backend,
                dimensions=config.embedding.dimensions,
            )
        count = index.rebuild(
            wiki_root=Path(args.wiki).expanduser() if args.wiki else config.wiki_root,
            max_chars=config.chunk.max_chars,
            overlap_chars=config.chunk.overlap_chars,
        )
        print(json.dumps({"indexed_chunks": count, "db": str(index.db_path)}, ensure_ascii=False, indent=2))
        return 0
    finally:
        index.close()


def cmd_recall(args: argparse.Namespace) -> int:
    config, index = _open_index(args)
    try:
        results = index.recall(
            args.query,
            limit=args.limit or config.recall.limit,
            max_tokens=args.max_tokens or config.recall.max_tokens,
            scope=args.scope,
            min_score=args.min_score if args.min_score is not None else config.recall.min_score,
            include_history=args.include_history,
        )
        payload = {
            "query": args.query,
            "count": len(results),
            "estimated_tokens": sum(r.token_est for r in results),
            "results": [r.to_json() for r in results],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for i, result in enumerate(results, start=1):
                print(f"{i}. [{result.score:.3f}] {result.title} :: {result.heading}")
                print(f"   id={result.id} scope={result.scope} path={result.rel_path}")
                print(f"   {result.summary}")
            print(f"\nresults={len(results)} estimated_tokens={payload['estimated_tokens']}")
        return 0
    finally:
        index.close()


def cmd_get(args: argparse.Namespace) -> int:
    _, index = _open_index(args)
    try:
        row = index.get(args.id)
        if not row:
            print(json.dumps({"error": "not_found", "id": args.id}, ensure_ascii=False), file=sys.stderr)
            return 1
        text = row["text"]
        max_tokens = args.max_tokens
        if max_tokens and estimate_tokens(text) > max_tokens:
            approx_chars = max(200, int(max_tokens * 2.2))
            text = text[:approx_chars].rstrip() + "\n...[truncated]"
        payload = {
            "memory_id": row["memory_id"] or Path(row["rel_path"]).stem,
            "topic_id": row["topic_id"],
            "status": row["status"],
            "supersedes": row["supersedes"],
            "superseded_by": row["superseded_by"],
            "source_repo": row["source_repo"],
            "commit": row["commit_sha"],
            "observed_at": row["observed_at"],
            "id": row["id"],
            "title": row["title"],
            "heading": row["heading"],
            "path": row["path"],
            "rel_path": row["rel_path"],
            "scope": row["scope"],
            "token_est": estimate_tokens(text),
            "text": text,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else text)
        return 0
    finally:
        index.close()


def cmd_stats(args: argparse.Namespace) -> int:
    _, index = _open_index(args)
    try:
        print(json.dumps(index.stats(), ensure_ascii=False, indent=2))
        return 0
    finally:
        index.close()


def cmd_crystallize(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    wiki_root = Path(args.wiki).expanduser() if args.wiki else config.wiki_root
    if args.body_file:
        body = Path(args.body_file).expanduser().read_text(encoding="utf-8")
    else:
        body = sys.stdin.read()
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    path = write_topic(
        wiki_root,
        args.title,
        body,
        tags=tags,
        recall_metadata=not args.no_recall_metadata,
        commit=args.commit,
        superseded_by=args.superseded_by,
        supersedes=args.supersedes,
        source_repo=args.source_repo,
        observed_at=args.observed_at,
    )
    if args.log:
        append_log(wiki_root, args.title, path, commit=args.commit)
    print(json.dumps({"path": str(path), "memory_id": path.stem, "wiki_link": f"[[{path.stem}]]", "supersedes": args.supersedes}, ensure_ascii=False, indent=2))
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    wiki_root = Path(args.wiki).expanduser() if args.wiki else config.wiki_root
    report = lint_wiki(wiki_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Wiki Root: {report['wiki_root']}")
        print(f"Total Markdown Files: {report['total_files']}")
        for error in report.get("errors", []):
            print(f"[ERROR] {error}")
        for key in ("ambiguous_links", "supersession_errors", "provenance_warnings"):
            for item in report.get(key, []):
                print(f"[{key}] {item}")
        broken = report["broken_links"]
        if broken:
            print(f"\n[!] Found {len(broken)} broken wikilink(s):")
            for item in broken:
                print(f"  - {item['source_file']} -> [[{item['target_link']}]]")
        else:
            print("\n[OK] No broken wikilinks found.")

        orphans = report["orphan_topics"]
        if orphans:
            print(f"\n[i] Found {len(orphans)} unlinked topic(s) (no incoming links):")
            for orphan in orphans:
                print(f"  - {orphan}")
        else:
            print("[OK] No unlinked topic files found.")

    if args.fail_on_broken and not report["ok"]:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="astor-wiki-memory")
    parser.add_argument("--config", help="Path to config JSON")
    parser.add_argument("--db", help="Path to index SQLite DB")

    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Index the LLM Wiki")
    p_index.add_argument("--wiki", help="Wiki root path")
    p_index.add_argument("--rebuild", action="store_true", help="Delete and rebuild the index DB")
    p_index.set_defaults(func=cmd_index)

    p_recall = sub.add_parser("recall", help="Recall relevant chunks")
    p_recall.add_argument("query")
    p_recall.add_argument("--limit", type=int)
    p_recall.add_argument("--max-tokens", type=int)
    p_recall.add_argument("--scope")
    p_recall.add_argument("--min-score", type=float)
    p_recall.add_argument("--json", action="store_true")
    p_recall.add_argument("--include-history", action="store_true", help="Allow superseded memories in search")
    p_recall.set_defaults(func=cmd_recall)

    p_get = sub.add_parser("get", help="Get a chunk by id")
    p_get.add_argument("id")
    p_get.add_argument("--max-tokens", type=int, default=800)
    p_get.add_argument("--json", action="store_true")
    p_get.set_defaults(func=cmd_get)

    p_stats = sub.add_parser("stats", help="Show index statistics")
    p_stats.set_defaults(func=cmd_stats)

    p_crystallize = sub.add_parser("crystallize", help="Write a crystallized memory topic")
    p_crystallize.add_argument("--wiki", help="Wiki root path")
    p_crystallize.add_argument("--title", required=True)
    p_crystallize.add_argument("--body-file")
    p_crystallize.add_argument("--tags", default="memory")
    p_crystallize.add_argument("--commit", help="Associated Git commit SHA (e.g. 5beb35b)")
    p_crystallize.add_argument("--superseded-by", help="Legacy: target that already supersedes this page")
    p_crystallize.add_argument("--supersedes", help="Existing memory ID to supersede with a new revision")
    p_crystallize.add_argument("--source-repo", help="Source repository owner/name")
    p_crystallize.add_argument("--observed-at", help="Date at which claim was observed, YYYY-MM-DD")
    p_crystallize.add_argument("--log", action="store_true", help="Append to log.md")
    p_crystallize.add_argument(
        "--no-recall-metadata",
        action="store_true",
        help="Do not append lightweight recall alias / natural-language entry sections",
    )
    p_crystallize.set_defaults(func=cmd_crystallize)

    p_lint = sub.add_parser("lint", help="Lint Wiki markdown files for broken links and orphan topics")
    p_lint.add_argument("--wiki", help="Wiki root path")
    p_lint.add_argument("--json", action="store_true", help="Output JSON report")
    p_lint.add_argument("--fail-on-broken", action="store_true", help="Exit with code 1 if broken links found")
    p_lint.set_defaults(func=cmd_lint)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
