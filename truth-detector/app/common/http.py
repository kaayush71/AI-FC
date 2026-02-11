from __future__ import annotations

import time
from typing import Dict, Tuple

import requests


DEFAULT_HEADERS = {
    "User-Agent": "truth-detector-ingest/0.1 (+https://example.local)",
}
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _backoff_seconds(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    return min(cap, base * (2 ** max(0, attempt - 1)))


def http_get(
    url: str,
    timeout: int = 20,
    headers: Dict[str, str] | None = None,
    max_retries: int = 3,
) -> Tuple[bytes, str]:
    request_headers = dict(DEFAULT_HEADERS)
    if headers:
        request_headers.update(headers)
    attempts = max(1, max_retries + 1)

    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, headers=request_headers, timeout=timeout, allow_redirects=True)
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < attempts:
                time.sleep(_backoff_seconds(attempt))
                continue
            response.raise_for_status()
            return response.content, response.url
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt < attempts:
                time.sleep(_backoff_seconds(attempt))
                continue
            raise RuntimeError(f"HTTP GET failed for {url}: {exc}") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"HTTP GET failed for {url}: {exc}") from exc

    raise RuntimeError(f"HTTP GET failed for {url}: exhausted retries")
