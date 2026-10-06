"""Rate-limited HTTP sessions and a small on-disk cache for API listings and downloads."""
import hashlib
import json
import time
from datetime import date

import requests

from . import config


class RateLimitedSession(requests.Session):
    def __init__(self, max_per_sec, user_agent):
        super().__init__()
        self.min_interval = 1.0 / max_per_sec
        self._last = 0.0
        self.headers["User-Agent"] = user_agent

    def request(self, *args, **kwargs):
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        kwargs.setdefault("timeout", 60)
        return super().request(*args, **kwargs)


SEC = RateLimitedSession(8, config.SEC_USER_AGENT)          # SEC limit is 10 req/s
WEB = RateLimitedSession(2, config.BROWSER_UA)               # cninfo / HKEXnews: be polite


def _key(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode()).hexdigest()[:24]


def cached_json(name, fetch, daily=True):
    """Cache fetch() result as JSON. Listings change over time, so by default the key includes today's date."""
    d = config.CACHE_DIR / "api"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_key(name, str(date.today()) if daily else '')}.json"
    if path.exists():
        return json.loads(path.read_text())
    data = fetch()
    path.write_text(json.dumps(data, ensure_ascii=False, default=str))
    return data


def cached_download(session, url, subdir, filename):
    """Download once; published filings never change, so no expiry."""
    path = config.CACHE_DIR / "docs" / subdir / filename
    if path.exists() and path.stat().st_size > 0:
        return path
    r = session.get(url)
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return path
