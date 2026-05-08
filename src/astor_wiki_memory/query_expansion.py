from __future__ import annotations

import re

from .text import normalize_text


DOMAIN_SYNONYMS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("五分鐘", "5分鐘", "五分", "5分", "5m"),
        ("5m", "5分鐘", "五分鐘", "5-minute"),
    ),
    (
        ("影子", "shadow", "shadow-only", "shadowonly"),
        ("shadow", "影子", "shadow-only"),
    ),
    (
        ("交易", "單", "signal", "signals", "符合"),
        ("signal", "signals", "交易", "符合"),
    ),
    (
        ("結果", "resolution", "resolutions", "勝率", "輸贏"),
        ("resolution", "resolutions", "結果", "輸贏"),
    ),
    (
        ("oracle", "oracle lag", "oracle-lag", "oracle lag sniper"),
        ("oracle-lag-sniper", "Oracle-Lag-Sniper", "oracle"),
    ),
    (
        ("polymarket", "clob"),
        ("Polymarket", "CLOB"),
    ),
)


INTENT_SYNONYMS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("狀態", "進度", "目前", "現在", "完成", "做到哪", "結果如何", "能不能用", "可用"),
        ("status", "current state", "implementation status", "完成狀態", "結果"),
    ),
    (
        ("根因", "原因", "為什麼", "壞在哪", "問題在哪", "踩坑", "故障"),
        ("root cause", "原因", "pitfall", "failure", "修復"),
    ),
    (
        ("修", "修復", "解法", "怎麼處理", "怎麼修", "修好", "處理方式"),
        ("fix", "resolution", "solution", "修復", "解法"),
    ),
    (
        ("路徑", "在哪", "位置", "檔案", "檔名", "repo", "repository"),
        ("path", "rel_path", "檔案", "路徑", "repository"),
    ),
    (
        ("決策", "為何決定", "策略", "取代", "方案"),
        ("decision", "strategy", "rationale", "決策", "策略"),
    ),
)


QUERY_STOPWORDS = {
    "的",
    "了",
    "嗎",
    "呢",
    "有",
    "沒有",
    "可不可以",
    "可以",
    "一下",
    "幫我",
    "看看",
    "看",
    "查",
    "查詢",
    "如何",
    "怎麼樣",
    "what",
    "is",
    "the",
    "a",
    "an",
    "to",
    "of",
    "and",
}


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def expand_query(query: str, *, max_terms: int = 18) -> str:
    """Return a compact recall query with light, domain-aware aliases.

    This intentionally stays conservative: it preserves the user's original words,
    adds only aliases whose trigger already appears in the query, and caps total
    terms to avoid noisy broad searches.
    """

    normalized = normalize_text(query)
    terms: list[str] = []

    def add(term: str) -> None:
        term = normalize_text(term)
        if not term or term.lower() in QUERY_STOPWORDS:
            return
        if term not in terms:
            terms.append(term)

    add(normalized)
    for triggers, aliases in DOMAIN_SYNONYMS:
        if _contains_any(normalized, triggers):
            for alias in aliases:
                add(alias)
    for triggers, aliases in INTENT_SYNONYMS:
        if _contains_any(normalized, triggers):
            for alias in aliases:
                add(alias)

    return " ".join(terms[:max_terms])


def should_expand_recall(results_count: int, best_score: float, *, min_results: int = 3, weak_score: float = 0.48) -> bool:
    """Decide whether the first-pass recall looks too weak.

    Hybrid recall can return many plausible but off-target chunks with mid scores.
    A modest threshold keeps exact strong hits stable while still expanding the
    common Astor pattern: natural Chinese phrasing for a code/English concept.
    """

    return results_count < min_results or best_score < weak_score
