# Durable Wiki Memory: revision and upgrade guide

## Core invariants

- Markdown pages are the durable source of truth. SQLite is disposable and can be rebuilt.
- Every new write creates a uniquely named revision. Existing facts must not be silently overwritten.
- Use memory_update with supersedes=<existing memory_id> to create a successor and mark the predecessor superseded.
- Do not infer "current" truth from wiki notes alone: status applies to the recorded observation, not live source code.
- An optional commit must be 7-40 hexadecimal characters. Include source_repo=owner/name for meaningful code provenance. The CLI validates syntax, not remote existence of the commit.
- Legacy Markdown pages continue to work without a schema migration; new writes use schema_version 2.

## CLI examples

Create an initial revision:

    astor-wiki-memory crystallize --title "WebRTC tuning" --source-repo h104651/MirrorBridge --commit abc1234 --observed-at 2026-10-22 --log < note.md

The command returns memory_id. Update with a successor:

    astor-wiki-memory crystallize --title "WebRTC tuning" --supersedes "<old-memory-id>" --source-repo h104651/MirrorBridge --commit def5678 --log < updated-note.md

Current-state and historical recall:

    astor-wiki-memory index
    astor-wiki-memory recall "WebRTC tuning" --json
    astor-wiki-memory recall "WebRTC tuning" --include-history --json
    astor-wiki-memory lint --json

The new memory_update adapter tool requires an existing memory ID; use memory_store for new independent topics.
The legacy --superseded-by flag is retained for existing integrations, but new revisions should use --supersedes instead.

## Upgrade and rollback

1. Back up the Markdown wiki and SQLite DB before deploying a new plugin version.
2. Upgrade the Python package and OpenClaw adapter together to version 0.2.0.
3. Run astor-wiki-memory index --rebuild once. New SQLite columns are added automatically if an old DB is opened, but a rebuild is recommended to populate provenance metadata for legacy rows.
4. Run astor-wiki-memory lint --json and review errors and supersession warnings.
5. Run python3 -m unittest discover -s tests -v and run OpenClaw integration smoke tests in the installed runtime.
6. If you roll back the adapter/core, first disable auto-writes; older readers may ignore the additional frontmatter but cannot manage the revision graph. Your Markdown history is preserved and can be reindexed. Keep a copy of the old DB if returning to an earlier SQLite schema.

## Failure recovery

A new revision and predecessor metadata are written with atomic file replacement under an inter-process write lock. If the predecessor update fails, the newly created file is removed. A sudden process crash between two filesystem writes is not fully transactional: the Wiki lint tool checks broken successor/predecessor chains. Review and reconcile that report before accepting new memory. Do not force-delete source history.

Orphan topics and incomplete source_repo values are warnings, not necessarily fatal. Missing directories, broken links, ambiguous links and invalid revision chains cause lint ok=false.

## Index performance

Normal index updates use file modification times to re-chunk changed pages, retaining unchanged vectors and FTS rows. Use --rebuild to force a complete refresh after configuration, embedding settings, or recovery changes. Very unusual mtime-preserving edits require a forced rebuild.
