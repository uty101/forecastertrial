"""Content-hash cache. Non-negotiable, for two separate reasons.

1. You will re-run the judge forty times while tuning. If that re-runs
   acquisition each time you lose the afternoon.
2. `make verify` needs byte-identical output from identical inputs. That is only
   possible if every external fetch is replayable.

The key includes `as_of`, so a cached fetch can never be reused across a
point-in-time boundary — the cache cannot become a leak vector.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


class Cache:
    def __init__(self, root: Path | str = "data/cache", read_only: bool = False) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.read_only = read_only
        self.hits = 0
        self.misses = 0

    def key(self, namespace: str, as_of: date, **parts: Any) -> str:
        payload = json.dumps(
            {"ns": namespace, "as_of": as_of.isoformat(), **parts},
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()[:20]
        return f"{namespace}/{as_of.isoformat()}/{digest}"

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(_read_with_retry(path))

    def put(self, key: str, value: Any) -> None:
        if self.read_only:
            # from_cache mode: a miss must fail loudly rather than silently
            # hitting the network and breaking determinism.
            raise CacheMiss(f"read-only cache: refusing to fetch and store {key}")
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, default=str, sort_keys=True))

    def fetch(self, key: str, producer):
        """get-or-produce. The only method callers should normally use."""
        cached = self.get(key)
        if cached is not None:
            return cached
        if self.read_only:
            raise CacheMiss(
                f"{key} not in cache and cache is read-only. Run without "
                "--from-cache once to populate it."
            )
        value = producer()
        if value is not None:
            self.put(key, value)
        return value

    def fetch_dated(self, key: str, producer, not_before: date):
        """get-or-produce, reusing a stored entry only if it was fetched on or
        after `not_before`.

        For an append-only payload — SEC `companyfacts` is the one that matters —
        a fixed cache key is wrong in exactly one direction. A payload fetched
        BEFORE `as_of` is missing everything filed in between, and the
        point-in-time filter downstream can drop facts it should not see but
        cannot restore facts that were never in the response. The result reads
        as "this company has not filed recently", which is indistinguishable
        from a genuine gap.

        Keying on `as_of` instead would be correct and ruinous: a 200-quarter
        backtest would refetch the same multi-megabyte payload 200 times per
        ticker. Freshness is the weaker condition and the right one.

        Read-only mode skips the check deliberately. `make verify` replays a
        recorded cache and must never reach the network to satisfy a freshness
        rule — that would make the golden-file test meaningless.
        """
        stored = self.get(key)
        if isinstance(stored, dict) and {"fetched_at", "value"} <= stored.keys():
            if self.read_only or date.fromisoformat(stored["fetched_at"]) >= not_before:
                return stored["value"]
        elif stored is not None and self.read_only:
            # Written by an earlier build with no envelope. Replay trusts it;
            # a live run falls through, refreshes, and writes the envelope back.
            return stored

        if self.read_only:
            raise CacheMiss(
                f"{key} not in cache and cache is read-only. Run without "
                "--from-cache once to populate it."
            )
        value = producer()
        if value is not None:
            self.put(
                key, {"fetched_at": date.today().isoformat(), "value": value}
            )
        return value

    @property
    def stats(self) -> dict[str, int | float]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }


def _read_with_retry(path: Path, attempts: int = 4, pause: float = 0.15) -> str:
    """Read a cache file, retrying briefly on a transient lock.

    A repo living inside OneDrive (or Dropbox, or under an on-access virus
    scanner) hands out `PermissionError` while the syncing process holds a
    handle. It clears in milliseconds, but the Loader treats any exception as a
    source failure — so a single sync tick silently cost a peer its entire
    financial history and counted against the circuit breaker.

    Deliberately narrow: only PermissionError, only a few attempts. A genuine
    permissions problem still surfaces, just half a second later.
    """
    import time

    for attempt in range(attempts):
        try:
            return path.read_text()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            log.debug("cache_locked", path=str(path), attempt=attempt)
            time.sleep(pause * (attempt + 1))
    raise AssertionError("unreachable")


class CacheMiss(RuntimeError):
    """Raised in read-only mode. Deliberately fatal — a silent network fallback
    during `make verify` would make the golden-file test meaningless."""
