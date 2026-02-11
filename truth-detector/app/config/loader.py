from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REQUIRED_SOURCE_FIELDS = {
    "id",
    "name",
    "country",
    "category",
    "rss_urls",
    "enabled",
    "fetch_interval_minutes",
    "trust_rank",
}


def load_sources(config_path: str) -> list[dict[str, Any]]:
    path = Path(config_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "sources" not in payload:
        raise ValueError(f"Invalid sources config: {config_path}")

    sources = payload["sources"]
    if not isinstance(sources, list):
        raise ValueError("Expected 'sources' to be a list")

    normalized: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Each source entry must be an object")
        missing = REQUIRED_SOURCE_FIELDS - set(source.keys())
        if missing:
            raise ValueError(f"Source '{source.get('id', '<unknown>')}' missing fields: {sorted(missing)}")
        if not isinstance(source["rss_urls"], list) or not source["rss_urls"]:
            raise ValueError(f"Source '{source['id']}' must define at least one rss_urls entry")
        normalized.append(source)

    return normalized
