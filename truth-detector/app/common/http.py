from __future__ import annotations

import time
from typing import Dict, Tuple
from urllib.parse import urlparse

import requests


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
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

    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        request_headers.setdefault("Referer", f"{parsed.scheme}://{parsed.netloc}/")

    attempts = max(1, max_retries + 1)
    browser_retry_headers = dict(request_headers)
    browser_retry_headers.setdefault("Sec-Fetch-Dest", "document")
    browser_retry_headers.setdefault("Sec-Fetch-Mode", "navigate")
    browser_retry_headers.setdefault("Sec-Fetch-Site", "none")
    browser_retry_headers.setdefault("Sec-Fetch-User", "?1")
    used_browser_profile = False

    with requests.Session() as session:
        for attempt in range(1, attempts + 1):
            try:
                response = session.get(url, headers=request_headers, timeout=timeout, allow_redirects=True)

                if response.status_code == 403 and not used_browser_profile and attempt < attempts:
                    # Some publishers block non-browser profiles; retry once with fuller browser headers.
                    used_browser_profile = True
                    request_headers = browser_retry_headers
                    time.sleep(_backoff_seconds(attempt))
                    continue

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
