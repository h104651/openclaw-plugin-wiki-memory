# Architecture

## Final Target

```text
LLM Wiki Markdown source of truth
→ astor-wiki-memory core with sensitive-line redaction
→ CLI/MCP
→ OpenClaw and Hermes thin adapters
```

## Why This Replaces LanceDB Pro

LanceDB Pro stores both durable memory and retrieval index inside a plugin-managed database. That creates upgrade risk when embedding dimensions, plugin contracts, or provider quota change.

Astor Wiki Memory separates these concerns:

- Markdown Wiki is durable and human-readable.
- SQLite index is rebuildable.
- Adapter is replaceable.

## MVP Backend

Current backend:

- SQLite FTS5 for keyword search.
- Local deterministic hashing vectors for quota-free vector similarity.
- Hybrid ranking.
- Sensitive-line redaction before chunks enter SQLite.

Future backend options:

- QMD.
- sqlite-vec.
- OpenAI-compatible embeddings.
- Gemini embeddings when quota is stable.

The adapter contract should not change when the backend changes.
