"""Layer E — EXPECTATIONS. What is the bar?

Everything here measures what is ALREADY expected, before any lens forms a view.
Nothing in this stage produces a forecast, and that separation is the point: the
system's thesis is that consensus is beatable where it is structurally weak, and
you cannot locate a weakness without first stating precisely what is assumed.

    E1  consensus      level, dispersion, staleness, revision direction
    E2  landing        where this company lands inside its own guided range
    E3  priced in      the growth the current share price requires
    E4  positioning    implied move, options skew, insider trades
    E5  swing factors  which lines actually decide this company's quarter

Almost all of it is deterministic. E1 comes from the consensus record, E3 is the
reverse DCF stage D already builds, E5 is arithmetic on the model. Only E2 needs
anything extracted, and that extraction has already happened at B5.

**E5 is the one that changes the shape of what follows.** Until now six lenses
ran on every company regardless and the judge weighed them by an asserted
materiality. Measuring which lines move THIS company's EPS turns both into a
fitted quantity: a company whose misses come from gross margin gets Margins run
deep and Macro skipped, and the judge's weights come from the model rather than
from a paragraph.
"""

from forecaster.pipeline.e_expect import landing, swing

__all__ = ["landing", "swing"]
