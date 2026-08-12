"""Bull, base and bear — on the swing factors only, with an explicit bridge.

**The version of this that is worth nothing** is three numbers with no arithmetic
between them: a bear case 10% below the base and a bull 10% above, decorated with
probabilities somebody felt were about right. Every sell-side note has one and
nobody has ever traded on one, because there is no way to check it.

What makes it worth something is the bridge. Each case is built by moving the
DRIVERS that E5 measured as material, one at a time, through the same
three-statement model — so the difference between bull and base is not a number,
it is a list of specific assumption changes each worth a stated number of cents.
A reader can disagree with one line of it rather than with the whole case.

**Only the swing factors move.** Everything E5 marked immaterial is held at base
in all three cases, and that is the discipline: a bear case that moves nine
drivers at once is not a scenario, it is a mood. If gross margin is 29% of the
answer and the tax rate is 3%, the bear case is a margin story and the tax rate
stays where it is.

**Probabilities are stated and are not the point.** They exist so the expected
value can be computed and compared to consensus, and they are the weakest thing
here — a subjective weight on three arbitrary points of a continuous
distribution. The interval that actually matters comes from V3, bootstrapped
from our own historical residuals. These three cases are for explaining the
shape of the risk, not for measuring it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import structlog

log = structlog.get_logger()

Case = Literal["bear", "base", "bull"]

# How far each material driver is moved. One standard deviation of its own
# historical quarterly variation would be better and needs a longer series than
# most companies give; a fixed relative move is the honest stand-in and it is
# declared rather than buried.
DEFAULT_MOVE = 0.15

# The weights. Symmetric and deliberately unopinionated — asymmetry here would be
# a view about direction smuggled in as a probability, and the place to hold a
# directional view is the driver, not the weight on it.
DEFAULT_WEIGHTS: dict[Case, float] = {"bear": 0.25, "base": 0.50, "bull": 0.25}


@dataclass
class Step:
    """One driver moved, and what that move is worth in EPS."""

    driver: str
    label: str
    base_value: float
    case_value: float
    eps_delta: float

    @property
    def direction(self) -> str:
        return "up" if self.case_value > self.base_value else "down"


@dataclass
class Scenario:
    case: Case
    eps: float
    probability: float
    steps: list[Step] = field(default_factory=list)

    @property
    def eps_delta(self) -> float:
        return sum(step.eps_delta for step in self.steps)

    def bridge(self, base_eps: float) -> str:
        """The arithmetic from base to this case, line by line.

        This is the whole artefact. Three numbers are an opinion; three numbers
        with the steps between them is something a reader can attack one line at
        a time.
        """
        rows = [f"{self.case.upper():5} {base_eps:.3f} base"]
        running = base_eps
        for step in self.steps:
            running += step.eps_delta
            rows.append(
                f"      {step.eps_delta:+.3f}  {step.label} "
                f"{step.base_value:.3f} -> {step.case_value:.3f}   = {running:.3f}"
            )
        rows.append(f"      {self.eps:.3f} {self.case}  (p={self.probability:.0%})")
        return "\n".join(rows)


@dataclass
class Scenarios:
    ticker: str
    base_eps: float
    cases: list[Scenario] = field(default_factory=list)
    drivers_moved: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)

    @property
    def expected_eps(self) -> float:
        """Probability-weighted. Compared to consensus, this is the number the
        position is sized on — but see the module docstring: the interval comes
        from V3's own residuals, not from these three points."""
        total = sum(c.probability for c in self.cases)
        if not total:
            return self.base_eps
        return sum(c.eps * c.probability for c in self.cases) / total

    def get(self, case: Case) -> Scenario | None:
        return next((c for c in self.cases if c.case == case), None)

    def spread(self) -> float | None:
        """Bull minus bear, in EPS. The width of the case, not of the forecast."""
        bull, bear = self.get("bull"), self.get("bear")
        return bull.eps - bear.eps if bull and bear else None


def build(
    ticker: str,
    base_eps: float,
    base_drivers: dict[str, float],
    eps_for: dict[tuple[str, float], float],
    material: list[str],
    immaterial: list[str] | None = None,
    move: float = DEFAULT_MOVE,
    weights: dict[Case, float] | None = None,
) -> Scenarios:
    """Assemble the three cases from a model already asked for each move.

    `eps_for[(driver, value)]` is the EPS the three-statement model produces with
    that one driver set to that value and everything else at base. Passing the
    results in rather than calling the model here keeps this module free of the
    projection — it is arithmetic on numbers somebody else computed, which is
    what makes it testable without a filing.

    Only `material` drivers move. Everything in `immaterial` is recorded as held
    so the sheet can say which assumptions were NOT stressed, which is the part a
    reader should check hardest: a scenario is defined as much by what it holds
    fixed as by what it moves.
    """
    weights = weights or DEFAULT_WEIGHTS
    result = Scenarios(
        ticker=ticker,
        base_eps=base_eps,
        drivers_moved=list(material),
        held=list(immaterial or []),
    )

    for case in ("bear", "base", "bull"):
        if case == "base":
            result.cases.append(
                Scenario(case="base", eps=base_eps, probability=weights["base"])
            )
            continue

        direction = 1.0 if case == "bull" else -1.0
        steps: list[Step] = []
        for driver in material:
            base_value = base_drivers.get(driver)
            if base_value is None:
                continue
            case_value = base_value * (1 + direction * move)
            eps = eps_for.get((driver, case_value))
            if eps is None:
                continue
            steps.append(
                Step(
                    driver=driver,
                    label=driver.replace("_", " "),
                    base_value=base_value,
                    case_value=case_value,
                    eps_delta=eps - base_eps,
                )
            )

        # The cases COMPOUND. Each step's delta was measured on its own, and
        # summing them assumes the drivers do not interact — true enough for a
        # margin and a tax rate, and an approximation for revenue growth and an
        # expense ratio. Stated here rather than hidden, because the alternative
        # is re-running the model on every combination and that is 2^n runs to
        # refine a number the probabilities are far cruder than.
        steps.sort(key=lambda s: -abs(s.eps_delta))
        result.cases.append(
            Scenario(
                case=case,  # type: ignore[arg-type]
                eps=base_eps + sum(s.eps_delta for s in steps),
                probability=weights[case],  # type: ignore[index]
                steps=steps,
            )
        )

    result.cases.sort(key=lambda c: c.eps)
    log.info(
        "scenarios_built",
        ticker=ticker,
        eps=[round(c.eps, 3) for c in result.cases],
        moved=material,
        held=result.held,
    )
    return result


def to_block(scenarios: Scenarios) -> str:
    if not scenarios.cases:
        return "(no scenarios — no material driver could be moved)"

    lines = [
        f"BULL / BASE / BEAR — {scenarios.ticker}. Only the swing factors move; "
        "each case is a list of specific assumption changes with the cents each "
        "is worth.",
        "",
    ]
    for scenario in scenarios.cases:
        lines.append(scenario.bridge(scenarios.base_eps))
        lines.append("")

    spread = scenarios.spread()
    if spread is not None:
        lines.append(f"Bull less bear: {spread:.3f} EPS")
    lines.append(f"Probability-weighted: {scenarios.expected_eps:.3f}")
    if scenarios.held:
        lines += [
            "",
            "HELD AT BASE IN ALL THREE CASES: " + ", ".join(scenarios.held) + ".",
            "A scenario is defined as much by what it holds fixed as by what it "
            "moves — these were measured as immaterial to this company's quarter, "
            "and stressing them would widen the range without informing it.",
        ]
    lines += [
        "",
        "The probabilities are the weakest thing here: a subjective weight on "
        "three arbitrary points of a continuous distribution. The interval to "
        "act on comes from V3, bootstrapped from our own historical residuals.",
    ]
    return "\n".join(lines)


def to_json(scenarios: Scenarios) -> dict:
    return {
        "ticker": scenarios.ticker,
        "base_eps": scenarios.base_eps,
        "expected_eps": scenarios.expected_eps,
        "spread": scenarios.spread(),
        "drivers_moved": scenarios.drivers_moved,
        "held": scenarios.held,
        "cases": [
            {
                "case": c.case,
                "eps": c.eps,
                "probability": c.probability,
                "eps_delta": c.eps_delta,
                "steps": [
                    {
                        "driver": s.driver,
                        "label": s.label,
                        "base_value": s.base_value,
                        "case_value": s.case_value,
                        "eps_delta": s.eps_delta,
                        "direction": s.direction,
                    }
                    for s in c.steps
                ],
            }
            for c in scenarios.cases
        ],
    }
