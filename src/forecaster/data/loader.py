"""Source resolution — priority order with graceful fallback.

The design rule from `protocol.py`: every method may return None, meaning "I
don't have this." The loader tries sources in priority order and takes the first
real answer.

Why this matters on the day: the sponsor's feed is an unknown. A twenty-minute
adapter that only implements `get_consensus` is still useful, because everything
else falls through to yfinance and SEC. You are never blocked on making their
adapter complete.

It also records *which* source answered each call, so the UI can show where
every figure came from and you can spot the case where two sources disagree —
which is a finding, not an error.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

import structlog

from forecaster.data.protocol import DataSource, PointInTimeViolation

log = structlog.get_logger()

T = TypeVar("T")


class SourceFailure(RuntimeError):
    pass


class Loader:
    """Holds the source chain and the circuit breakers."""

    FAILURES_BEFORE_TRIP = 3

    def __init__(self, sources: list[DataSource]) -> None:
        self.sources = sorted(sources, key=lambda s: s.priority)
        self.provenance: dict[str, str] = {}
        self._failures: dict[str, int] = {}
        self.disagreements: list[dict[str, Any]] = []

    def _live(self) -> list[DataSource]:
        return [
            s
            for s in self.sources
            if self._failures.get(s.name, 0) < self.FAILURES_BEFORE_TRIP
        ]

    def _try(self, source: DataSource, call: Callable[[DataSource], T | None], what: str):
        try:
            return call(source)
        except PointInTimeViolation:
            # Never swallow this one. A source that leaks is a bug to fix, not a
            # transient failure to route around.
            raise
        except Exception as exc:
            self._failures[source.name] = self._failures.get(source.name, 0) + 1
            tripped = self._failures[source.name] >= self.FAILURES_BEFORE_TRIP
            log.warning(
                "source_failed",
                source=source.name,
                what=what,
                error=str(exc),
                circuit_tripped=tripped,
            )
            return None

    def resolve(
        self, what: str, call: Callable[[DataSource], T | None], cross_check: bool = False
    ) -> T | None:
        """First non-None answer wins.

        With cross_check=True, keep asking after the first hit and record any
        disagreement. Use it for consensus, where the sponsor feed and yfinance
        disagreeing tells you something real about which basis you're on.
        """
        answer: T | None = None
        winner: str | None = None

        for source in self._live():
            value = self._try(source, call, what)
            if value is None:
                continue
            if answer is None:
                answer, winner = value, source.name
                self.provenance[what] = source.name
                if not cross_check:
                    return answer
            elif value != answer:
                self.disagreements.append(
                    {"what": what, winner: answer, source.name: value}
                )
                log.info(
                    "sources_disagree", what=what, primary=winner, other=source.name
                )

        if answer is None:
            log.warning("no_source_answered", what=what)
        return answer

    # ------------------------------------------------------------------ #
    # typed convenience wrappers
    # ------------------------------------------------------------------ #

    def consensus(self, ticker: str, as_of: date):
        return self.resolve(
            f"consensus:{ticker}",
            lambda s: s.get_consensus(ticker, as_of),
            cross_check=True,
        )

    def actuals(self, ticker: str, period: str, as_of: date):
        return self.resolve(
            f"actuals:{ticker}:{period}", lambda s: s.get_actuals(ticker, period, as_of)
        )

    def history(self, ticker: str, as_of: date, keys: tuple[str, ...] | None = None):
        """The quarterly series the three-statement model is built from."""
        return self.resolve(
            f"history:{ticker}",
            lambda s: getattr(s, "get_history", lambda *_, **__: None)(
                ticker, as_of, keys
            ),
        )

    def peers(self, ticker: str, as_of: date, limit: int = 12):
        return self.resolve(
            f"peers:{ticker}",
            lambda s: getattr(s, "get_peers", lambda *_, **__: None)(
                ticker, as_of, limit
            ),
        )

    def prices(self, ticker: str, start: date, end: date):
        """Daily bars, unadjusted. Keyed on the window, not just the ticker —
        two different windows are two different questions."""
        return self.resolve(
            f"prices:{ticker}:{start}:{end}",
            lambda s: getattr(s, "get_prices", lambda *_, **__: None)(
                ticker, start, end
            ),
        )

    def guidance(self, ticker: str, as_of: date):
        return self.resolve(f"guidance:{ticker}", lambda s: s.get_guidance(ticker, as_of))

    def filings(
        self,
        ticker: str,
        as_of: date,
        forms: list[str],
        limit: int = 10,
        items: str | None = None,
    ):
        # `items` is part of the cache/provenance key: "the last three 8-Ks" and
        # "the last three earnings 8-Ks" are different questions with different
        # answers, and collapsing them would serve one from the other's result.
        what = f"filings:{ticker}:{','.join(forms)}"
        return self.resolve(
            f"{what}:items={items}" if items else what,
            lambda s: s.get_filings(ticker, as_of, forms, limit, items),
        )

    def transcript(self, ticker: str, as_of: date):
        return self.resolve(
            f"transcript:{ticker}", lambda s: s.get_transcript(ticker, as_of)
        )

    def report(self) -> dict[str, Any]:
        """Goes into the run manifest and the UI."""
        return {
            "sources": [s.name for s in self.sources],
            "answered_by": dict(self.provenance),
            "tripped": [
                n for n, c in self._failures.items() if c >= self.FAILURES_BEFORE_TRIP
            ],
            "disagreements": self.disagreements,
        }
