from __future__ import annotations

import re
import unicodedata


WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
SENSITIVE_LINE_RE = re.compile(
    r"(?i)(private\s*key|api\s*key|secret\s*key|client\s*secret|access\s*token|"
    r"refresh\s*token|auth\s*token|bot\s*token|bearer\s+[A-Za-z0-9]|password|"
    r"passwd|mnemonic|seed\s*phrase|私鑰|密鑰|金鑰|助記詞|密碼)"
)
SECRET_VALUE_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|0x[a-fA-F0-9]{64})"
)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def redact_sensitive_text(text: str) -> str:
    """Prevent credential-like lines from entering automatic recall."""
    redacted: list[str] = []
    for line in text.splitlines():
        if SENSITIVE_LINE_RE.search(line) or SECRET_VALUE_RE.search(line):
            redacted.append("[REDACTED sensitive line]")
        else:
            redacted.append(line)
    return "\n".join(redacted)


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in WORD_RE.finditer(normalize_text(text))]


def estimate_tokens(text: str) -> int:
    # Conservative mixed Chinese/English estimate for tool budget gating.
    chars = len(text)
    words = len(tokenize(text))
    return max(1, int(max(chars / 2.2, words * 1.3)))


def summarize(text: str, max_chars: int = 220) -> str:
    clean = normalize_text(re.sub(r"```.*?```", " ", text, flags=re.S))
    if len(clean) <= max_chars:
        return clean
    cut = clean[:max_chars].rsplit(" ", 1)[0]
    if len(cut) < max_chars * 0.5:
        cut = clean[:max_chars]
    return cut.rstrip("，,。.;；:：") + "..."


def slugify(text: str) -> str:
    text = normalize_text(text).lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "untitled"
