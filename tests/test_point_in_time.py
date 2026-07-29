"""Point-in-time enforcement.

This is the test that matters most and the one almost nobody writes. A backtest
that cannot fail this way is not enforcing anything, and the resulting numbers
are meaningless — restated figures leak future information silently and your
model looks brilliant for no reason.

The test deliberately tries to leak and asserts the system stops it.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.data.protocol import PointInTimeViolation, assert_point_in_time

AS_OF = date(2026, 8, 16)  # forecasts lock on hackathon day


def test_fact_filed_before_as_of_is_allowed():
    assert_point_in_time(date(2026, 5, 28), AS_OF, "Q1 10-Q")


def test_fact_filed_on_as_of_is_allowed():
    assert_point_in_time(AS_OF, AS_OF, "same-day 8-K")


def test_fact_filed_after_as_of_is_refused():
    """The whole point: NVIDIA reports on 26 August. Its results must be
    invisible to a forecast locked on the 16th."""
    with pytest.raises(PointInTimeViolation) as err:
        assert_point_in_time(date(2026, 8, 26), AS_OF, "NVDA Q2 8-K")
    assert "leak future information" in str(err.value)


def test_restatement_after_as_of_is_refused():
    """The subtle one. The *period* is historical, so it looks safe — but the
    restated figure was only published later, and using it is look-ahead bias.
    XBRL's `filed` field is what saves you here, not the period label."""
    with pytest.raises(PointInTimeViolation):
        assert_point_in_time(
            published=date(2026, 9, 30),  # restatement filed after our lock
            as_of=AS_OF,
            what="FY2024 revenue, as restated",
        )


@pytest.mark.parametrize(
    "published,should_raise",
    [
        (date(2020, 1, 1), False),
        (date(2026, 8, 15), False),
        (date(2026, 8, 16), False),
        (date(2026, 8, 17), True),
        (date(2027, 1, 1), True),
    ],
)
def test_boundary(published: date, should_raise: bool):
    if should_raise:
        with pytest.raises(PointInTimeViolation):
            assert_point_in_time(published, AS_OF, "boundary")
    else:
        assert_point_in_time(published, AS_OF, "boundary")
