"""Phase 7 — kill criteria, monitoring, and the post-mortem.

**The step most analysts skip, and the only one that compounds.** Everything
upstream produces a number. This decides what would make that number wrong, then
watches for it, then afterwards asks which line was actually responsible.

Three parts, and the middle one is where an agent is unambiguously better:

**Kill criteria.** Written at forecast time, when you still remember why you
believe the thing. "I am wrong if AMD guides datacentre down" is a real claim; "I
am wrong if the thesis breaks" is not. A criterion has to name an OBSERVABLE
event and a source that would show it, or it is not a criterion.

**Monitoring.** An analyst checks their kill criteria when something reminds
them. A process can check every one of them on a schedule against the same
sources it used to form the view, and the checking is deterministic — did the
peer report, did the price gap, did guidance change. No judgement, no tokens.

**The post-mortem.** Score the forecast, decompose the error BY LINE, feed it
back. Getting EPS right because revenue was low and margin was high is not
getting it right, and a process that records only the headline error learns
nothing from it. The decomposition is the same arithmetic as the swing factors
run after the fact instead of before.

Nothing here is a forecast. It is the record that makes the next forecast better,
which is why skipping it is so cheap and so expensive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import structlog

log = structlog.get_logger()

Watch = Literal["peer_result", "pre_announcement", "guidance_change",
                "price_move", "insider_selling", "macro_series"]

Verdict = Literal["holding", "triggered", "unobservable"]

# A price move this large before a print is the market pricing something we do
# not know. Not proof we are wrong, but the strongest routine signal available
# without paying for anything.
PRICE_MOVE_TRIGGER = 0.08


@dataclass
class KillCriterion:
    """One observable event that would say the forecast is wrong.

    `observable` is the discipline. A criterion nobody can check before the print
    is a caveat wearing a criterion's clothes, and the field exists so that
    failing to name a source disqualifies it rather than quietly weakening it.
    """

    watch: Watch
    what: str
    source: str
    # What the forecast rests on, so a triggered criterion says which part broke.
    invalidates: str
    threshold: float | None = None
    subject: str = ""

    @property
    def observable(self) -> bool:
        return bool(self.source and self.what)


@dataclass
class Check:
    criterion: KillCriterion
    verdict: Verdict
    detail: str
    observed_at: date | None = None


@dataclass
class Monitor:
    ticker: str
    period: str
    criteria: list[KillCriterion] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)

    @property
    def triggered(self) -> list[Check]:
        return [c for c in self.checks if c.verdict == "triggered"]

    @property
    def unobservable(self) -> list[KillCriterion]:
        """Criteria that cannot be checked before the print.

        Surfaced rather than dropped: a forecast whose kill criteria are all
        unobservable has no kill criteria, and that is worth knowing at the time
        rather than discovering afterwards.
        """
        return [c for c in self.criteria if not c.observable]

    def verdict(self) -> str:
        if self.triggered:
            return (
                f"{len(self.triggered)} of {len(self.criteria)} kill criteria have "
                "fired — the forecast rests on something that has since been "
                "contradicted"
            )
        if not self.criteria:
            return "no kill criteria were written, so nothing can contradict this"
        return f"all {len(self.criteria)} kill criteria holding"


def check_price(
    criterion: KillCriterion, price_at_forecast: float, price_now: float,
    observed: date,
) -> Check:
    """Deterministic. Did the market move enough to say it knows something?"""
    if not price_at_forecast:
        return Check(criterion, "unobservable", "no price at forecast time")
    move = price_now / price_at_forecast - 1
    trigger = criterion.threshold or PRICE_MOVE_TRIGGER
    if abs(move) >= trigger:
        return Check(
            criterion, "triggered",
            f"the shares have moved {move:+.1%} since the forecast, past the "
            f"{trigger:.0%} threshold — the market is pricing something this "
            "forecast does not contain",
            observed,
        )
    return Check(criterion, "holding", f"moved {move:+.1%}, inside {trigger:.0%}",
                 observed)


def check_peer(
    criterion: KillCriterion, peers_reported: dict[str, float], observed: date
) -> Check:
    """Did the named peer report, and did it surprise in the wrong direction?

    A peer print is the single most informative pre-print event available: it is
    the same demand, the same quarter, and it lands before ours.
    """
    surprise = peers_reported.get(criterion.subject)
    if surprise is None:
        return Check(
            criterion, "unobservable",
            f"{criterion.subject or 'the peer'} has not reported yet", observed,
        )
    trigger = criterion.threshold if criterion.threshold is not None else -0.05
    fired = surprise <= trigger if trigger < 0 else surprise >= trigger
    if fired:
        return Check(
            criterion, "triggered",
            f"{criterion.subject} reported a {surprise:+.1%} surprise, past the "
            f"{trigger:+.0%} threshold",
            observed,
        )
    return Check(
        criterion, "holding",
        f"{criterion.subject} reported {surprise:+.1%}, inside the threshold",
        observed,
    )


def check_news(
    criterion: KillCriterion, headlines: list[str], observed: date
) -> Check:
    """A pre-announcement or a guidance change, from the news search.

    Keyword matching rather than a model call, deliberately: this runs
    repeatedly between the forecast and the print, and a monitor that costs
    tokens every time it looks is a monitor that gets turned off.
    """
    terms = tuple(t.strip().lower() for t in criterion.what.split("|") if t.strip())
    for headline in headlines:
        low = headline.lower()
        if terms and all(t in low for t in terms[:1]) and any(t in low for t in terms):
            return Check(
                criterion, "triggered",
                f"matched a headline: {headline[:120]}", observed,
            )
    return Check(criterion, "holding", f"no headline matched {criterion.what[:60]}",
                 observed)


# --------------------------------------------------------------------------- #
# the post-mortem
# --------------------------------------------------------------------------- #


@dataclass
class LineError:
    """One line of the model, and how much of the miss it explains."""

    driver: str
    forecast: float
    actual: float
    eps_effect: float

    @property
    def error(self) -> float | None:
        if not self.actual:
            return None
        return self.forecast / self.actual - 1


@dataclass
class PostMortem:
    ticker: str
    period: str
    forecast_eps: float
    actual_eps: float
    consensus_eps: float | None = None
    lines: list[LineError] = field(default_factory=list)

    @property
    def eps_error(self) -> float:
        return self.forecast_eps - self.actual_eps

    @property
    def beat_consensus(self) -> bool | None:
        """Whether we were closer than consensus. The only score that matters —
        being right in absolute terms while further from the actual than the
        Street is a loss."""
        if self.consensus_eps is None:
            return None
        return abs(self.eps_error) < abs(self.consensus_eps - self.actual_eps)

    def attributed(self) -> list[LineError]:
        return sorted(self.lines, key=lambda line: -abs(line.eps_effect))

    def offsetting(self) -> bool:
        """Whether errors cancelled rather than being absent.

        **The finding that a headline error hides.** Revenue 4% low and margin
        80bp high can produce an EPS within a cent of the actual, and recording
        that as a good forecast teaches the process exactly the wrong lesson.
        """
        effects = [line.eps_effect for line in self.lines]
        if len(effects) < 2:
            return False
        gross = sum(abs(e) for e in effects)
        net = abs(sum(effects))
        return gross > 0 and net < gross * 0.5


def to_block(monitor: Monitor) -> str:
    lines = [f"KILL CRITERIA — {monitor.ticker} {monitor.period}", "",
             monitor.verdict(), ""]
    for check in monitor.checks:
        mark = {"triggered": "FIRED", "holding": "  ok", "unobservable": "  ??"}[
            check.verdict
        ]
        lines.append(f" {mark}  {check.criterion.what[:58]}")
        lines.append(f"        {check.detail[:96]}")
        lines.append(f"        would invalidate: {check.criterion.invalidates[:70]}")
    if monitor.unobservable:
        lines += [
            "",
            "NOT OBSERVABLE before the print, so not a kill criterion at all:",
        ] + [f"  {c.what[:76]}" for c in monitor.unobservable]
    return "\n".join(lines)


def post_mortem_block(result: PostMortem) -> str:
    lines = [
        f"POST-MORTEM — {result.ticker} {result.period}",
        f"  forecast {result.forecast_eps:.3f}  actual {result.actual_eps:.3f}  "
        f"error {result.eps_error:+.3f}",
    ]
    if result.consensus_eps is not None:
        lines.append(
            f"  consensus {result.consensus_eps:.3f} "
            f"({'we were closer' if result.beat_consensus else 'consensus was closer'})"
        )
    lines += ["", "Attribution by line:"]
    for line in result.attributed():
        error = f"{line.error:+.1%}" if line.error is not None else "n/a"
        lines.append(
            f"  {line.driver:24} forecast {line.forecast:>10.4f}  "
            f"actual {line.actual:>10.4f}  {error:>8}   {line.eps_effect:+.3f} EPS"
        )
    if result.offsetting():
        lines += [
            "",
            "ERRORS OFFSET. The headline is close because the line errors cancel, "
            "not because the lines were right — recording this as a good forecast "
            "would teach the process the opposite of what happened.",
        ]
    return "\n".join(lines)
