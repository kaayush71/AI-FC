from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.common.http import http_get
from app.common.logging import get_logger
from app.common.time import utcnow_iso
from app.store.sqlite import SqliteStore

logger = get_logger(__name__)


def _parse_published(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return value


def _parse_feed_entries(feed_bytes: bytes) -> list[dict[str, Any]]:
    try:
        import feedparser  # type: ignore

        feed = feedparser.parse(feed_bytes)
        entries = []
        for entry in feed.entries:
            entries.append(
                {
                    "guid": getattr(entry, "id", None) or getattr(entry, "guid", None),
                    "link": getattr(entry, "link", None),
                    "title": getattr(entry, "title", None),
                    "published": _parse_published(getattr(entry, "published", None)),
                }
            )
        return entries
    except Exception:
        pass

    root = ET.fromstring(feed_bytes)
    entries: list[dict[str, Any]] = []

    for item in root.findall("./channel/item"):
        guid = item.findtext("guid")
        link = item.findtext("link")
        title = item.findtext("title")
        pub_date = item.findtext("pubDate")
        entries.append(
            {
                "guid": guid,
                "link": link,
                "title": title,
                "published": _parse_published(pub_date),
            }
        )

    if entries:
        return entries

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for item in root.findall("atom:entry", ns):
        guid = item.findtext("atom:id", default=None, namespaces=ns)
        title = item.findtext("atom:title", default=None, namespaces=ns)
        pub_date = item.findtext("atom:updated", default=None, namespaces=ns)
        link = None
        for link_node in item.findall("atom:link", ns):
            href = link_node.attrib.get("href")
            if href:
                link = href
                break
        entries.append(
            {
                "guid": guid,
                "link": link,
                "title": title,
                "published": _parse_published(pub_date),
            }
        )

    return entries


def run_fetch_rss(
    store: SqliteStore,
    sources: list[dict[str, Any]],
    since_minutes: int | None = None,
) -> dict[str, int]:
    cutoff: datetime | None = None
    if since_minutes is not None and since_minutes > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

    stats = {"sources": 0, "feeds": 0, "fetched_items": 0, "queued_items": 0, "errors": 0}

    for source in sources:
        source_id = source["id"]
        store.upsert_source(source)
        if not source.get("enabled", True):
            continue

        stats["sources"] += 1
        for feed_url in source.get("rss_urls", []):
            stats["feeds"] += 1
            fetched_at = utcnow_iso()
            try:
                payload, _ = http_get(feed_url, timeout=20)
                entries = _parse_feed_entries(payload)
                stats["fetched_items"] += len(entries)
                for entry in entries:
                    link = entry.get("link")
                    if not link:
                        continue
                    published = entry.get("published")
                    if cutoff and published:
                        try:
                            pdt = datetime.fromisoformat(published)
                            if pdt < cutoff:
                                continue
                        except Exception:
                            pass
                    store.upsert_rss_item(
                        source_id=source_id,
                        guid=entry.get("guid"),
                        url=link,
                        title=entry.get("title"),
                        published_at=published,
                        fetched_at=fetched_at,
                        status="queued",
                    )
                    stats["queued_items"] += 1
                store.mark_source_success(source_id, fetched_at)
            except Exception as exc:
                logger.exception("RSS fetch failed for source=%s feed=%s", source_id, feed_url)
                stats["errors"] += 1
                store.mark_source_error(source_id, fetched_at, str(exc))

    return stats
