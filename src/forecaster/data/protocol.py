"""The data boundary.

Every source implements this. On the day the *only* genuinely new code you write
is another implementation of this protocol against the sponsor's feed.

Two design rules that matter:

1. Every method may return None, meaning "I don't have this." A half-working
   adapter written in twenty minutes is still useful, because the loader falls
   back to the next source in priority order.

2. Every method takes `as_of`. Implementations MUST NOT return anything filed or
   published after that date. This is what makes honest backtesting possible,
   and it is the single most common thing teams get wrong — restated figures
   leak future information silently and your backtest looks great for no reason.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoids a cycle: history imports nothing from here
    from forecaster.data.history import History
from typing import Protocol, runtime_checkable

from forecaster.schemas import Claim, Consensus, Guidance


class PointInTimeViolation(RuntimeError):
    """Raised when a source tries to return data that did not exist at `as_of`.

    Deliberately loud. See tests/test_point_in_time.py, which triggers it on
    purpose — a backtest that cannot fail this way is not enforcing anything.
    """


@runtime_checkable
class DataSource(Protocol):
    name: str
    priority: int  # lower wins when several sources can answer

    def get_consensus(self, ticker: str, as_of: date) -> Consensus | None: ...

    def get_actuals(
        self, ticker: str, period: str, as_of: date
    ) -> list[Claim] | None: ...

    def get_history(
        self, ticker: str, as_of: date, keys: tuple[str, ...] | None = None
    ) -> History | None:
        """Every mapped line item as a quarterly series, point-in-time.

        Distinct from `get_actuals`, which answers "what was this one number in
        this one quarter". A three-statement model is built from trends — margin
        trajectory, working-capital ratios, share-count drift — and none of that
        is visible in a single period. Sources without history return None; the
        Loader treats it like any other unanswered request.
        """
        return None

    def get_guidance(self, ticker: str, as_of: date) -> list[Guidance] | None: ...

    def get_filings(
        self, ticker: str, as_of: date, forms: list[str], limit: int = 10
    ) -> list[Claim] | None: ...

    def get_transcript(self, ticker: str, as_of: date) -> str | None: ...

    def get_fx_rates(self, currencies: list[str], start: date, end: date): ...

    def get_macro(self, series_ids: list[str], as_of: date): ...


def assert_point_in_time(published: date, as_of: date, what: str) -> None:
    """Call this in every source implementation, on every record.

    Cheap, and it converts the most dangerous class of silent bug into a crash.
    """
    if published > as_of:
        raise PointInTimeViolation(
            f"{what}: published {published} is after as_of {as_of} — "
            "this would leak future information into the backtest"
        )
