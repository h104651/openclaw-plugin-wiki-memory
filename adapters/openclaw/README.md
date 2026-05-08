# OpenClaw Adapter Placeholder

This directory is reserved for the thin OpenClaw adapter.

The adapter must call the stable core CLI/MCP contract rather than directly coupling memory logic to OpenClaw internals.

Initial adapter commands:

```bash
/home/astorhsu/.local/bin/astor-wiki-memory recall "$QUERY" --json --limit 5 --max-tokens 1200
/home/astorhsu/.local/bin/astor-wiki-memory get "$CHUNK_ID" --json --max-tokens 800
/home/astorhsu/.local/bin/astor-wiki-memory crystallize --title "$TITLE" --tags openclaw,memory --log < body.md
```

Do not implement auto-capture as raw transcript storage. Writeback must crystallize root cause, fix, SOP, and pitfalls.
