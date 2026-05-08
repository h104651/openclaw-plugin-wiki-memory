# Hermes Adapter Plan

Hermes should use the same memory core as OpenClaw. Do not copy the Wiki or create a Hermes-specific memory database.

## Shared Paths

```text
Wiki source:
/home/astorhsu/Documents/我們的知識庫

Index:
/home/astorhsu/.local/share/astor-wiki-memory/index/wiki-memory.sqlite3

Core:
/home/astorhsu/repos/astor-wiki-memory
```

## Adapter Contract

Hermes can call the CLI directly or through an MCP server later:

```bash
/home/astorhsu/.local/bin/astor-wiki-memory recall "$QUERY" --json
/home/astorhsu/.local/bin/astor-wiki-memory get "$CHUNK_ID" --json
/home/astorhsu/.local/bin/astor-wiki-memory crystallize --title "$TITLE" --tags hermes,memory --log < body.md
```

Hermes adapter rules match OpenClaw:

- Recall must be token-budgeted.
- Detail reads are explicit.
- Writeback should crystallize root causes, decisions, and SOPs, not raw chats.
- Failure must be non-blocking.
