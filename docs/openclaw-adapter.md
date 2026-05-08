# OpenClaw Thin Adapter Plan

The OpenClaw adapter must stay thin. The memory core is the CLI/MCP-capable repo, not an OpenClaw runtime implementation detail.

## Tools

Expose these tools to OpenClaw:

```text
wiki_recall(query, scope?, limit?, maxTokens?)
wiki_get(id, maxTokens?)
wiki_crystallize(title, body, tags?)
wiki_index_update()
wiki_stats()
```

## Fail-open Rule

If `wiki_recall` fails, timeout, or returns invalid JSON, the adapter returns:

```json
{
  "results": [],
  "warning": "wiki_recall unavailable; continuing without memory"
}
```

The adapter must never block Telegram/HQ, Forge, or Audit.

## Token Budget

Default recall budget:

- `limit=5`
- `maxTokens=1200`
- `wiki_get maxTokens=800`

No full Markdown is returned by recall.

## Commands

```bash
/home/astorhsu/.local/bin/astor-wiki-memory recall "$QUERY" --json --limit 5 --max-tokens 1200
/home/astorhsu/.local/bin/astor-wiki-memory get "$ID" --json --max-tokens 800
/home/astorhsu/.local/bin/astor-wiki-memory crystallize --title "$TITLE" --tags openclaw,memory --log < body.md
/home/astorhsu/.local/bin/astor-wiki-memory index
/home/astorhsu/.local/bin/astor-wiki-memory stats
```
