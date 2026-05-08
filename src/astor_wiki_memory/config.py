from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "default.json"


@dataclass(frozen=True)
class ChunkConfig:
    max_chars: int = 1800
    overlap_chars: int = 160


@dataclass(frozen=True)
class RecallConfig:
    limit: int = 5
    max_tokens: int = 1200
    per_item_summary_chars: int = 220
    min_score: float = 0.05


@dataclass(frozen=True)
class EmbeddingConfig:
    backend: str = "hashing"
    dimensions: int = 384


@dataclass(frozen=True)
class AppConfig:
    wiki_root: Path
    index_db: Path
    chunk: ChunkConfig
    recall: RecallConfig
    embedding: EmbeddingConfig


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    path = Path(config_path).expanduser() if config_path else DEFAULT_CONFIG_PATH
    raw = _read_json(path)

    chunk = raw.get("chunk", {})
    recall = raw.get("recall", {})
    embedding = raw.get("embedding", {})

    return AppConfig(
        wiki_root=Path(raw["wiki_root"]).expanduser(),
        index_db=Path(raw["index_db"]).expanduser(),
        chunk=ChunkConfig(
            max_chars=int(chunk.get("max_chars", 1800)),
            overlap_chars=int(chunk.get("overlap_chars", 160)),
        ),
        recall=RecallConfig(
            limit=int(recall.get("limit", 5)),
            max_tokens=int(recall.get("max_tokens", 1200)),
            per_item_summary_chars=int(recall.get("per_item_summary_chars", 220)),
            min_score=float(recall.get("min_score", 0.05)),
        ),
        embedding=EmbeddingConfig(
            backend=str(embedding.get("backend", "hashing")),
            dimensions=int(embedding.get("dimensions", 384)),
        ),
    )

