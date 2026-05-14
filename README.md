# astor-wiki-memory

Shared memory core for Astor's agents. The goal is to replace `memory-lancedb-pro` as the long-term recall layer while keeping the LLM Wiki as the durable source of truth.

## Design

```text
/home/astorhsu/Documents/我們的知識庫
  LLM Wiki Markdown source of truth
        ↓
astor-wiki-memory core
  heading-aware chunking
  SQLite FTS5 keyword search
  vector backend, default local hashing, pluggable later
  hybrid ranking
  token-budget recall output
        ↓
thin adapters
  OpenClaw
  Hermes
  Codex
```

This repo intentionally keeps the core independent from OpenClaw internals. If OpenClaw changes plugin contracts later, only the thin adapter should need changes.

## Current MVP

- Index Markdown from the LLM Wiki.
- Chunk by headings and paragraph budget.
- Store chunks in SQLite.
- Search using FTS5 + local vector similarity.
- Return compact recall summaries with a hard token budget.
- Read details on demand with `get`.
- Write crystallized lessons back to the Wiki.
- Redact credential-like lines before they enter the recall index.

The default vector backend is local hashing, so it does not depend on Gemini/OpenAI quota. A true embedding backend can be added behind the same interface without changing the Wiki source.

## Paths

```text
Code:
/home/astorhsu/repos/astor-wiki-memory

Wiki source:
/home/astorhsu/Documents/我們的知識庫

Rebuildable index:
/home/astorhsu/.local/share/astor-wiki-memory/index/wiki-memory.sqlite3
```

## Quick Start

Preferred command on this WSL machine:

```bash
/home/astorhsu/.local/bin/astor-wiki-memory index --rebuild
/home/astorhsu/.local/bin/astor-wiki-memory recall "OpenClaw LanceDB Pro replacement strategy" --limit 5
/home/astorhsu/.local/bin/astor-wiki-memory stats
```

Development mode:

```bash
cd /home/astorhsu/repos/astor-wiki-memory
PYTHONPATH=src python3 -m astor_wiki_memory index --rebuild
PYTHONPATH=src python3 -m astor_wiki_memory recall "OpenClaw LanceDB Pro replacement strategy" --limit 5
PYTHONPATH=src python3 -m astor_wiki_memory stats
```

If `/home/astorhsu/.local/bin` is added to `PATH`, the shorter `astor-wiki-memory` command is equivalent.

## Token Budget Contract

Recall tools must not return full Markdown by default.
Credential-like lines are redacted before indexing, not only at display time.

Default policy:

- Maximum 5 results.
- Maximum 1200 estimated tokens total.
- Each result returns title, summary, path, heading, score, and chunk id.
- Full text requires a separate `get` call.

## Adapter Contract

Thin adapters should call these commands:

```bash
/home/astorhsu/.local/bin/astor-wiki-memory recall "<query>" --json --limit 5 --max-tokens 1200
/home/astorhsu/.local/bin/astor-wiki-memory get "<chunk_id>" --json --max-tokens 800
/home/astorhsu/.local/bin/astor-wiki-memory crystallize --title "<title>" --tags openclaw,memory --log < body.md
/home/astorhsu/.local/bin/astor-wiki-memory index
/home/astorhsu/.local/bin/astor-wiki-memory stats
```

Adapters must fail open: if recall fails, return no memory and let the agent continue.

## Public X/Twitter Source Capture

OpenClaw workspaces that need public X/Twitter evidence can install [TweetClaw](https://github.com/Xquik-dev/tweetclaw) beside this memory adapter:

```bash
openclaw plugins install @xquik/tweetclaw
```

Use TweetClaw to search tweets, search tweet replies, export followers, look up users, monitor tweets, deliver webhooks, download media when authenticated, or draft approval-gated posts and replies. Then crystallize a wiki source page rather than storing raw timelines:

```bash
astor-wiki-memory crystallize --title "X/Twitter source: product launch feedback" --tags openclaw,memory,x-twitter,source --log < tweetclaw-summary.md
```

Good source pages should keep:

- The original query, monitor name, or workflow trigger
- Tweet IDs or URLs and capture date
- Short summary, confidence, and follow-up decision
- Links to related wiki entities or topics

Keep raw timelines, direct messages, credentials, and private account material outside the wiki unless your retention policy explicitly allows them. Store distilled facts and source references instead.
