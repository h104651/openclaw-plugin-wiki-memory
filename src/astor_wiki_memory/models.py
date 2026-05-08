from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Chunk:
    id: str
    path: Path
    rel_path: str
    title: str
    heading: str
    ordinal: int
    text: str
    summary: str
    scope: str
    tags: list[str]
    updated_at: str
    mtime: float
    token_est: int

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass(frozen=True)
class RecallResult:
    id: str
    score: float
    fts_score: float
    vector_score: float
    title: str
    summary: str
    path: str
    rel_path: str
    heading: str
    scope: str
    token_est: int

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

