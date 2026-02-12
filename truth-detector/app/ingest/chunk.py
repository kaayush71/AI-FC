from __future__ import annotations

import re

from app.common.hashing import sha256_text
from app.common.time import utcnow_iso
from app.store.sqlite import SqliteStore

TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", flags=re.UNICODE)


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text)


def _detokenize(tokens: list[str]) -> str:
    text = " ".join(tokens)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def chunk_tokens(tokens: list[str], target_tokens: int, overlap_tokens: int) -> list[list[str]]:
    if target_tokens <= 0:
        raise ValueError("target_tokens must be > 0")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be >= 0 and < target_tokens")

    chunks: list[list[str]] = []
    step = target_tokens - overlap_tokens
    start = 0
    while start < len(tokens):
        end = min(start + target_tokens, len(tokens))
        chunks.append(tokens[start:end])
        if end == len(tokens):
            break
        start += step
    return chunks


def run_chunking(
    store: SqliteStore,
    target_tokens: int = 420,
    overlap_tokens: int = 60,
    limit_articles: int | None = None,
) -> dict[str, int]:
    stats = {"articles": 0, "chunks": 0}

    for article in store.list_articles_for_chunking(limit=limit_articles):
        stats["articles"] += 1
        tokens = tokenize(article["text"])
        if not tokens:
            continue

        rows = []
        for idx, token_slice in enumerate(chunk_tokens(tokens, target_tokens=target_tokens, overlap_tokens=overlap_tokens)):
            text = _detokenize(token_slice)
            if not text:
                continue
            rows.append(
                {
                    "url": article["url"],
                    "source_id": article["source_id"],
                    "title": article["title"],
                    "published_at": article["published_at"],
                    "chunk_index": idx,
                    "text": text,
                    "chunk_hash": sha256_text(f"{article['url']}::{idx}::{text}"),
                    "token_count": len(token_slice),
                    "created_at": utcnow_iso(),
                }
            )

        store.insert_chunks(rows)
        stats["chunks"] += len(rows)

    return stats
