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
        return json.loads(path.read_text())

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

    @property
    def stats(self) -> dict[str, int | float]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }


class CacheMiss(RuntimeError):
    """Raised in read-only mode. Deliberately fatal — a silent network fallback
    during `make verify` would make the golden-file test meaningless."""
