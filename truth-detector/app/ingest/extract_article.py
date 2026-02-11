from __future__ import annotations

import re
from html import unescape

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None

from app.common.http import http_get
from app.common.logging import get_logger
from app.common.time import utcnow_iso
from app.ingest.clean import normalize_text
from app.ingest.dedupe import compute_text_hash
from app.store.sqlite import SqliteStore

logger = get_logger(__name__)


def extract_main_text(html: str) -> str:
    if BeautifulSoup is None:
        text = re.sub(r"<script\\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", html, flags=re.I)
        text = re.sub(r"<style\\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = unescape(text)
        return normalize_text(text)

    soup = BeautifulSoup(html, "html.parser")

    for tag_name in ["script", "style", "nav", "footer", "header", "noscript", "form"]:
        for node in soup.find_all(tag_name):
            node.decompose()

    article = soup.find("article")
    if article is not None:
        text = article.get_text("\n")
    else:
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        paragraphs = [p for p in paragraphs if p]
        text = "\n\n".join(paragraphs)

    return normalize_text(text)


def run_extract_articles(store: SqliteStore, limit: int | None = None) -> dict[str, int]:
    stats = {"processed": 0, "extracted": 0, "failed": 0}

    for item in store.list_queued_items(limit=limit):
        stats["processed"] += 1
        item_id = item["item_id"]
        url = item["url"]

        try:
            body, final_url = http_get(url, timeout=30)
            html = body.decode("utf-8", errors="ignore")
            text = extract_main_text(html)
            if not text:
                raise RuntimeError("No article text extracted")

            normalized = normalize_text(text)
            text_hash = compute_text_hash(normalized)

            store.upsert_article(
                {
                    "url": url,
                    "source_id": item["source_id"],
                    "final_url": final_url,
                    "title": item["title"],
                    "published_at": item["published_at"],
                    "author": None,
                    "text": normalized,
                    "html": None,
                    "extracted_at": utcnow_iso(),
                    "text_hash": text_hash,
                    "duplicate_of_url": None,
                }
            )
            store.update_rss_status(item_id, "extracted")
            stats["extracted"] += 1
        except Exception as exc:
            logger.exception("Failed to extract article from url=%s", url)
            store.update_rss_status(item_id, "failed", error=str(exc))
            stats["failed"] += 1

    return stats
