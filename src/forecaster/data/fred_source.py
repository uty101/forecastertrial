"""FRED — macro series for the Macro lens.

Free, keyed, well-documented, and revised. That last word is the whole reason
this file is more than twenty lines of `httpx.get`.

**Macro data is revised, and the revisions are the trap.** GDP, payrolls and
industrial production are all restated months after first publication. Pulling
today's value of a series for a quarter that ended last year gives you the
*revised* figure — which nobody had at the time, and which quietly leaks the
future into a backtest in the most invisible way available.

FRED solves this properly with ALFRED: the `realtime_start` parameter returns
the series *as it was published on a given date*. Every request here sets it
from `as_of`, so the Macro lens sees the numbers that actually existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import structlog

from forecaster.data.cache import Cache

log = structlog.get_logger()

FRED_BASE = "https://api.stlouisfed.org/fred"

# Sector-relevant series. The Macro lens is told to name the two or three that
# actually drive a company's quarter rather than reciting all of them — a
# homebuilder cares about mortgage rates, an enterprise software company barely
# does.
SERIES = {
    "rates": ["DFF", "DGS10", "MORTGAGE30US"],
    "fx": ["DTWEXBGS", "DEXUSEU", "DEXJPUS", "DEXCHUS"],
    "consumer": ["UMCSENT", "RSAFS", "PCE", "CPIAUCSL"],
    "industrial": ["INDPRO", "IPMAN", "NAPM"],
    "labour": ["PAYEMS", "UNRATE", "AHETPI"],
    "housing": ["HOUST", "PERMIT", "CSUSHPINSA"],
    "semis": ["IPG3344S", "WPU1178"],
}


@dataclass
class MacroPoint:
    series_id: str
    date: date
    value: float


class FREDSource:
    name = "fred"
    priority = 30  # nothing else provides macro, so priority barely matters

    def __init__(self, api_key: str, cache: Cache) -> None:
        self.api_key = api_key
        self.cache = cache
        self._client = None

    # ------------------------------------------------------------------ #

    def _get(self, path: str, as_of: date, **params) -> dict | None:
        import httpx

        key = self.cache.key("fred", as_of, path=path, **params)

        def produce():
            if self._client is None:
                self._client = httpx.Client(base_url=FRED_BASE, timeout=30.0)
            response = self._client.get(
                path,
                params={
                    **params,
                    "api_key": self.api_key,
                    "file_type": "json",
                    # THE POINT-IN-TIME LINE. Without these two, a backtest gets
                    # revised figures nobody had at the time.
                    "realtime_start": as_of.isoformat(),
                    "realtime_end": as_of.isoformat(),
                },
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

        return self.cache.fetch(key, produce)

    # ------------------------------------------------------------------ #

    def get_macro(
        self, series_ids: list[str], as_of: date, start: date | None = None
    ) -> dict[str, list[MacroPoint]] | None:
        """Series as they were published on `as_of`."""
        if not self.api_key:
            log.warning("fred_disabled", why="FRED_API_KEY unset")
            return None

        window_start = start or date(as_of.year - 2, as_of.month, 1)
        out: dict[str, list[MacroPoint]] = {}

        for series_id in series_ids:
            payload = self._get(
                "/series/observations",
                as_of,
                series_id=series_id,
                observation_start=window_start.isoformat(),
                observation_end=as_of.isoformat(),
            )
            if not payload:
                continue

            points = []
            for row in payload.get("observations", []):
                # FRED writes "." for a missing observation.
                if row.get("value") in (None, ".", ""):
                    continue
                try:
                    points.append(
                        MacroPoint(
                            series_id=series_id,
                            date=date.fromisoformat(row["date"]),
                            value=float(row["value"]),
                        )
                    )
                except (ValueError, KeyError):
                    continue
            if points:
                out[series_id] = points

        log.info("fred_fetched", series=len(out), as_of=as_of.isoformat())
        return out or None

    def get_fx_rates(self, currencies: list[str], start: date, end: date):
        """FX via the DEX* series. The Mechanical lens does the translation
        arithmetic; this only supplies the rates."""
        mapping = {"EUR": "DEXUSEU", "JPY": "DEXJPUS", "CNY": "DEXCHUS",
                   "GBP": "DEXUSUK", "CAD": "DEXCAUS"}
        ids = [mapping[c] for c in currencies if c in mapping]
        return self.get_macro(ids, end, start) if ids else None

    # -- unimplemented DataSource methods ------------------------------- #

    def get_consensus(self, ticker: str, as_of: date):
        return None

    def get_actuals(self, ticker: str, period: str, as_of: date):
        return None

    def get_guidance(self, ticker: str, as_of: date):
        return None

    def get_filings(self, ticker: str, as_of: date, forms: list[str], limit: int = 10):
        return None

    def get_transcript(self, ticker: str, as_of: date):
        return None


def macro_block(
    series: dict[str, list[MacroPoint]] | None, quarter_days: int = 92
) -> str:
    """Render series moves over the quarter for the Macro lens.

    Emits the *move*, not just the level. "10-year at 4.3%" is not an input; "the
    10-year went 3.9% to 4.3% over the quarter" is, because the lens's job is the
    gap between what happened and what estimates assumed.
    """
    if not series:
        return ""

    lines = []
    for series_id, points in sorted(series.items()):
        if len(points) < 2:
            continue
        ordered = sorted(points, key=lambda p: p.date)
        end = ordered[-1]
        start = next(
            (p for p in ordered if (end.date - p.date).days <= quarter_days),
            ordered[0],
        )
        change = end.value - start.value
        pct = f" ({change / start.value:+.1%})" if start.value else ""
        lines.append(
            f"- {series_id}: {start.value:,.4g} on {start.date} -> "
            f"{end.value:,.4g} on {end.date}, change {change:+,.4g}{pct}"
        )
    return "\n".join(lines)
