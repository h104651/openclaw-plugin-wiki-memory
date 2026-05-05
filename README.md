# openclaw-plugin-wiki-memory

OpenClaw memory plugin backed by a **Markdown-based LLM Wiki** with hybrid semantic search (embedding + FTS).

Thin adapter that delegates to the [`astor-wiki-memory`](https://github.com/h104651/astor-wiki-memory) CLI tool. Fail-open by design: if the CLI or index is unavailable, the plugin returns a graceful fallback instead of blocking the agent.

## Features

- **Human-readable memory** — every memory is a Markdown file in your wiki. No binary lock-in, no proprietary format.
- **Hybrid search** — embedding + FTS score fusion for relevant recall.
- **Fail-open** — CLI errors, missing index, or tool unavailability won't break the agent.
- **Post-write auto-index** — optional `autoIndexAfterWrite` re-indexes after each write so new memories are immediately searchable.
- **10 tools** — `memory_recall`, `wiki_recall`, `wiki_get`, `memory_store`, `wiki_crystallize`, `memory_update`, `memory_forget`, `wiki_index_update`, `memory_stats`, `wiki_stats`.

## Prerequisites

- **Node.js 20+** (ESM)
- **OpenClaw** (tested with v0.6+)
- **`astor-wiki-memory` CLI** — the binary that does the actual indexing and search.  
  Install from [h104651/astor-wiki-memory](https://github.com/h104651/astor-wiki-memory) or build from source.
- **LLM Wiki** — a directory of Markdown files. See the wiki repo for setup.

## Installation

1. **Install the CLI** (see upstream README).
2. **Clone this plugin** into your OpenClaw workspace:
   ```bash
   cd /path/to/your/openclaw/workspace
   git clone https://github.com/h104651/openclaw-plugin-wiki-memory.git
   ```
3. **Add to `openclaw.json`**:
   ```json
   {
     "plugins": {
       "slots": {
         "memory": "astor-wiki-memory"
       },
       "allow": ["astor-wiki-memory"],
       "load": {
         "paths": ["/path/to/openclaw-plugin-wiki-memory"],
         "allowFail": true
       }
     }
   }
   ```
4. **(Optional) Configure the CLI path** — if `astor-wiki-memory` is not at `/usr/local/bin/astor-wiki-memory`:
   ```json
   {
     "plugins": {
       "config": {
         "astor-wiki-memory": {
           "cliPath": "/custom/path/astor-wiki-memory",
           "autoIndexAfterWrite": true
         }
       }
     }
   }
   ```

## Available Tools

| Tool | Description |
|------|-------------|
| `memory_recall` | Hybrid semantic search of the wiki (embedding + FTS). |
| `wiki_recall` | Same as above, strict token budget variant. |
| `wiki_get` | Retrieve a single chunk by ID (from recall results). |
| `memory_store` | Write a new memory page via Markdown. Triggers auto-index if enabled. |
| `wiki_crystallize` | Same as `memory_store` with wiki-centric naming. |
| `memory_update` | Write a superseding/corrected memory. |
| `memory_forget` | Safe guard — does not auto-delete; instructs the agent to edit the wiki file manually. |
| `wiki_index_update` | Manually rebuild the search index from Markdown sources. |
| `memory_stats` | Show index chunk count and DB path. |
| `wiki_stats` | Same as `memory_stats`. |

## Architecture

```
┌─────────────┐   tool calls    ┌──────────────────────┐   exec    ┌──────────────────┐
│  OpenClaw   │ ──────────────▶ │  openclaw-plugin-    │ ────────▶ │ astor-wiki-memory │
│  Agent      │ ◀────────────── │  wiki-memory         │ ◀──────── │ CLI              │
└─────────────┘                 └──────────────────────┘           └──────────────────┘
                                                                         │
                                                                         ▼
                                                                ┌──────────────────┐
                                                                │  LLM Wiki        │
                                                                │  (Markdown files) │
                                                                │                  │
                                                                │  SQLite index     │
                                                                │  (hybrid search)  │
                                                                └──────────────────┘
```

- **Source of truth**: the Markdown files. Edit them directly with any editor.
- **Search index**: SQLite-backed, rebuilt on demand (`wiki_index_update`) or automatically after write.
- **No vector DB vendor lock**: the index is local, file-based, and portable.

## Acknowledgments

This plugin's design was informed by several projects in the LLM-native memory space.
No code was copied; the architecture, tool shape, and fail-open approach were independently developed.

### Knowledge Base Schema

The wiki directory structure (`wiki/entities/`, `wiki/topics/`, `wiki/sources/`, `raw/`, `index.md`, `log.md`) is inherited from:

- **[Karpathy's llm-wiki](https://gist.github.com/karpathy/193a681de9e5f5c1d049e1e2c290eff9)** — the original concept of AI-maintained Markdown wiki as long-term memory
- **[sdyckjq-lab/llm-wiki-skill](https://github.com/sdyckjq-lab/llm-wiki-skill)** (v3.3.0) — multi-platform implementation of Karpathy's methodology that shaped the file layout and workflow

### Architecture & API Design

- **[QMD](https://github.com/tobi/qmd)** — Markdown collection, BM25/vector hybrid search, MCP agent workflow
- **[Pyrite](https://github.com/markramm/pyrite)** — Markdown/YAML source of truth with SQLite index, MCP/REST access patterns
- **[sage-wiki](https://github.com/xoai/sage-wiki)** — chunk-level indexing, wiki Q&A, hybrid search
- **[LanceDB](https://github.com/lancedb/lancedb)** — API design inspiration for scope isolation and recall/writeback

## License

MIT
