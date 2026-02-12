from __future__ import annotations

from app.common.hashing import sha256_text
from app.store.sqlite import SqliteStore


def compute_text_hash(text: str) -> str:
    return sha256_text(text)


def run_dedupe(store: SqliteStore, limit: int | None = None) -> dict[str, int]:
    stats = {"scanned": 0, "duplicates": 0}
    canonical_by_hash: dict[str, str] = {}

    for article in store.list_articles_for_dedupe(limit=limit):
        stats["scanned"] += 1
        text_hash = article["text_hash"]
        url = article["url"]

        canonical_url = canonical_by_hash.get(text_hash)
        if canonical_url is None:
            existing = store.find_article_by_text_hash(text_hash)
            if existing is not None:
                canonical_url = existing["url"]
                canonical_by_hash[text_hash] = canonical_url
            else:
                canonical_by_hash[text_hash] = url
                continue

        if canonical_url != url:
            store.mark_article_duplicate(url=url, canonical_url=canonical_url)
            stats["duplicates"] += 1

    return stats
