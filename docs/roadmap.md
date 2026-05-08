# Roadmap

## Phase 1: Core MVP

- Markdown chunking.
- SQLite FTS5.
- Local hashing vector backend.
- Hybrid recall.
- Token-budget output.
- Crystallize writeback.

Status: completed.

## Phase 2: Higher Quality Semantic Backend

- Evaluate QMD backend.
- Evaluate sqlite-vec backend.
- Add OpenAI-compatible embedding provider behind the same interface.
- Keep local hashing as quota-free fallback.

## Phase 3: OpenClaw Integration

- Implement `wiki_recall`.
- Implement `wiki_get`.
- Implement `wiki_crystallize`.
- Fail open on all adapter errors.
- Add timeout guard.

## Phase 4: Hermes Integration

- Expose CLI or MCP contract to Hermes.
- Share the same index.
- Add Hermes-specific writeback tags.

## Phase 5: LanceDB Pro Removal

- Keep LanceDB Pro archived.
- Remove it from OpenClaw active memory slot after adapter recall quality is acceptable.

