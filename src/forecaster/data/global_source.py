"""Companies that do not file with the SEC — which is most of the world.

The whole acquisition layer was built on EDGAR, and EDGAR is a US registry. Hand
this system Nestlé and it does not degrade: it collapses. There is no CIK, so no
`companyfacts`, so no history, so no ratio base, so every lens abstains and the
run raises. That is the correct failure — it refuses to forecast rather than
inventing one — but "correctly refuses" is not the same as "works", and on the
day nobody is handing out marks for a well-formed exception.

**What this module is.** A second numeric backbone for issuers with no SEC
presence, built from the statements the exchange data carries, mapped onto the
same 62 line items `sec_source` produces so that everything downstream — the
three-statement model, the ratio base, the projection, the DCF — is unchanged.
The lenses cannot tell which registry a number came from, and should not.

**What it is NOT, stated plainly because the difference matters more here than
anywhere else in the repo:**

*These statements are not point-in-time.* EDGAR gives you the document as filed,
with the date it was filed, so a restatement is visible as a second filing. This
feed gives you the figures AS THEY STAND TODAY. A company that restated 2023
shows the restated 2023, and there is no way to see that from here.

So the invariant is preserved on the axis it can be — KNOWABILITY. A fiscal year
ending 31 December is not published on 31 December; it appears with the annual
report, months later. Every observation here is admitted only if its results
were plausibly published before `as_of`, using a conservative reporting lag, and
its `filed` date is that estimate rather than a fact. `estimated_filing` is set
on every observation so nothing downstream can mistake one for the other.

The exposure that remains is restatement, not look-ahead, and it is recorded in
the trace rather than papered over. On a forecast horizon of one period it is a
small effect; on a ten-year backtest it would not be, which is why the backtest
path still refuses anything but SEC data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import structlog

from forecaster.data.history import History, Observation

log = structlog.get_logger()

# How long after a period ends before its figures are public. Deliberately
# generous: half-year and annual reports from European issuers routinely land
# 6–10 weeks out, and admitting a number a week early is exactly the look-ahead
# this system exists to prevent. Being a fortnight conservative costs one stale
# period at the edge; being a week optimistic invalidates the whole run.
ANNUAL_LAG = timedelta(days=75)
INTERIM_LAG = timedelta(days=55)

# Below this many periods there is no ratio base worth calling one — the model
# needs enough history to take a median over, not two points and a slope.
MIN_PERIODS = 3

# yfinance statement rows -> the line-item keys the model is built on. Ordered
# alternatives per key: the first row present wins, so a filer using IFRS
# wording still lands on the same key as one using US GAAP wording.
#
# Verified against Nestlé (IFRS, CHF, SIX) rather than written from the docs.
ROW_MAP: dict[str, tuple[str, ...]] = {
    # ---- income ----
    "revenue": ("Total Revenue", "Operating Revenue"),
    "cost_of_revenue": ("Cost Of Revenue", "Reconciled Cost Of Revenue"),
    "gross_profit": ("Gross Profit",),
    "rnd": ("Research And Development",),
    "sgna": ("Selling General And Administration", "Selling And Marketing Expense"),
    "opex": ("Operating Expense",),
    "operating_income": ("Operating Income", "Total Operating Income As Reported"),
    "interest_expense": ("Interest Expense", "Interest Expense Non Operating"),
    "interest_income": ("Interest Income", "Interest Income Non Operating"),
    "other_income": ("Other Non Operating Income Expenses",),
    "pretax_income": ("Pretax Income",),
    "tax": ("Tax Provision",),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    # ---- shares ----
    "eps_diluted": ("Diluted EPS",),
    "eps_basic": ("Basic EPS",),
    "diluted_shares": ("Diluted Average Shares",),
    # ---- balance ----
    "cash": (
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
    ),
    "short_term_investments": ("Other Short Term Investments",),
    "receivables": ("Accounts Receivable", "Gross Accounts Receivable"),
    "inventory": ("Inventory",),
    "current_assets": ("Current Assets",),
    "total_assets": ("Total Assets",),
    "payables": ("Accounts Payable", "Payables"),
    "current_liabilities": ("Current Liabilities",),
    "total_liabilities": ("Total Liabilities Net Minority Interest",),
    "long_term_debt": ("Long Term Debt And Capital Lease Obligation", "Long Term Debt"),
    "short_term_debt": ("Current Debt And Capital Lease Obligation", "Current Debt"),
    "ppe_net": ("Net PPE",),
    "equity": ("Stockholders Equity", "Common Stock Equity"),
    "goodwill": ("Goodwill",),
    "intangibles": ("Other Intangible Assets",),
    "other_assets": ("Other Non Current Assets",),
    "retained_earnings": ("Retained Earnings",),
    "taxes_payable": ("Total Tax Payable",),
    "treasury_stock": ("Treasury Stock",),
    "long_term_investments": (
        "Long Term Equity Investment",
        "Investmentin Financial Assets",
    ),
    # ---- cash flow ----
    "cfo": ("Operating Cash Flow",),
    "cfi": ("Investing Cash Flow",),
    "cff": ("Financing Cash Flow",),
    "capex": ("Capital Expenditure", "Capital Expenditure Reported"),
    "depreciation": ("Depreciation And Amortization", "Depreciation"),
    "sbc": ("Stock Based Compensation",),
    "buyback": ("Repurchase Of Capital Stock", "Common Stock Payments"),
    "dividends": ("Cash Dividends Paid", "Common Stock Dividend Paid"),
    "cf_receivables": ("Change In Receivables",),
    "cf_inventory": ("Change In Inventory",),
    "cf_payables": ("Change In Payable",),
    "acquisitions": ("Purchase Of Business", "Net Business Purchase And Sale"),
    "debt_issued": ("Issuance Of Debt", "Long Term Debt Issuance"),
    "debt_repaid": ("Repayment Of Debt", "Long Term Debt Payments"),
    "stock_issued": ("Net Common Stock Issuance",),
    "fx_on_cash": ("Effect Of Exchange Rate Changes",),
    "net_change_cash": ("Changes In Cash",),
}

# Rows whose sign convention is the opposite of the model's. yfinance reports
# capex and buybacks as negatives (cash out); the model's `capex` is a positive
# magnitude, same as the SEC path produces. Getting this wrong does not fail —
# it builds a company that spends money to receive cash.
NEGATE = {"capex", "buyback", "dividends", "acquisitions", "debt_repaid"}


@dataclass
class GlobalSource:
    """Statements and identity for issuers outside EDGAR.

    Ordered AFTER `SecSource` in the loader, so a US filer never touches this —
    EDGAR is strictly better where it exists, being both point-in-time and
    filed rather than aggregated.
    """

    name: str = "global"
    # Highest number in the system, so every other source is asked first. This
    # only ever answers when EDGAR has never heard of the ticker.
    priority: int = 90

    def get_history(
        self, ticker: str, as_of: date, keys: tuple[str, ...] | None = None
    ) -> History | None:
        """Annual and interim statements, mapped onto the model's line items."""
        try:
            import yfinance as yf
        except ImportError:  # pragma: no cover - dependency is declared
            return None

        handle = yf.Ticker(ticker)
        frames = [
            (self._frame(handle, "income_stmt"), "FY", ANNUAL_LAG),
            (self._frame(handle, "balance_sheet"), "FY", ANNUAL_LAG),
            (self._frame(handle, "cashflow"), "FY", ANNUAL_LAG),
            (self._frame(handle, "quarterly_income_stmt"), "H", INTERIM_LAG),
            (self._frame(handle, "quarterly_balance_sheet"), "H", INTERIM_LAG),
            (self._frame(handle, "quarterly_cashflow"), "H", INTERIM_LAG),
        ]
        if not any(frame is not None for frame, _, _ in frames):
            return None

        currency = self._currency(handle)
        series: dict[str, list[Observation]] = {}
        wanted = set(keys) if keys else set(ROW_MAP)
        excluded = 0

        for frame, kind, lag in frames:
            if frame is None:
                continue
            for column in frame.columns:
                period_end = self._as_date(column)
                if period_end is None:
                    continue
                # The knowability check. Not point-in-time — knowable-by.
                published = period_end + lag
                if published > as_of:
                    excluded += 1
                    continue
                for key in wanted & set(ROW_MAP):
                    value = self._value(frame, key, column)
                    if value is None:
                        continue
                    series.setdefault(key, []).append(
                        Observation(
                            key=key,
                            fy=period_end.year,
                            fp=self._label(period_end, kind),
                            value=-value if key in NEGATE else value,
                            unit=currency,
                            period_end=period_end,
                            filed=published,
                            form="exchange-aggregated",
                            accession="",
                            derived=True,
                        )
                    )

        # One observation per (item, period end). A December balance sheet
        # arrives twice — once from the annual frame labelled FY and once from
        # the interim frame labelled H2 — and they are the same balance on the
        # same day. The ANNUAL label wins: `FY` is what the annualisation rules
        # downstream key on, and a fiscal year end silently labelled `H2` would
        # be summed as if it were half a year.
        for key in series:
            best: dict[date, Observation] = {}
            for observation in series[key]:
                held = best.get(observation.period_end)
                if held is None or (held.fp != "FY" and observation.fp == "FY"):
                    best[observation.period_end] = observation
            series[key] = sorted(best.values(), key=lambda o: o.period_end)

        periods = {o.period_end for rows in series.values() for o in rows}
        if len(periods) < MIN_PERIODS:
            log.warning(
                "global_history_too_thin", ticker=ticker, periods=len(periods),
                needed=MIN_PERIODS,
            )
            return None

        log.info(
            "global_history_built",
            ticker=ticker,
            items=len(series),
            periods=len(periods),
            currency=currency,
            excluded_not_yet_published=excluded,
            # Never silent. This is the invariant this source cannot honour.
            point_in_time=False,
            restatement_risk="figures are as they stand today, not as filed",
        )
        return History(ticker=ticker, as_of=as_of, series=series, cik="")

    # ---- identity, where there is no SIC code ---------------------------- #

    def get_sic(self, ticker: str, as_of: date) -> tuple[str, str] | None:
        """There is no SIC outside the US, so the sector comes from the listing.

        Returned in the same shape the SEC path uses so `b_acquire` does not
        branch: the code is empty and the description carries the industry. Every
        consumer reads element [1], which is the one that means something.
        """
        try:
            import yfinance as yf
        except ImportError:  # pragma: no cover
            return None
        try:
            info = yf.Ticker(ticker).info
        except Exception:  # noqa: BLE001 — a missing profile is not an error
            return None
        industry = info.get("industry") or info.get("sector")
        return ("", industry) if industry else None

    def get_name(self, ticker: str, as_of: date) -> str | None:
        """The company's own name, for a ticker nobody prepared in advance.

        Every text search in the acquisition layer is built from this. Without
        it the queries are built from the SYMBOL — "NESN.SW half-year results
        press release" — which matches nothing, while "Nestle half-year results
        press release" returns the release. The prepared universe has names for
        twelve companies; on the day the ticker is not one of them.
        """
        try:
            import yfinance as yf
        except ImportError:  # pragma: no cover
            return None
        try:
            info = yf.Ticker(ticker).info
        except Exception:  # noqa: BLE001
            return None
        return info.get("longName") or info.get("shortName")

    def get_website(self, ticker: str, as_of: date) -> str | None:
        """The company's own domain, for the IR-document route.

        From the exchange profile rather than derived from the company name.
        Deriving it gets Nestlé right and almost everyone else wrong — Toyota
        publishes on global.toyota, LVMH on lvmh.com, and a wrong domain filter
        returns nothing, which is indistinguishable from a company that files
        nothing.
        """
        try:
            import yfinance as yf
        except ImportError:  # pragma: no cover
            return None
        try:
            info = yf.Ticker(ticker).info
        except Exception:  # noqa: BLE001
            return None
        return info.get("irWebsite") or info.get("website")

    # ---- helpers --------------------------------------------------------- #

    @staticmethod
    def _frame(handle, attribute: str):
        try:
            frame = getattr(handle, attribute)
        except Exception:  # noqa: BLE001
            return None
        return None if frame is None or frame.empty else frame

    @staticmethod
    def _as_date(column) -> date | None:
        try:
            return column.date() if hasattr(column, "date") else None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _label(period_end: date, kind: str) -> str:
        """A period label the rest of the system can sort and display.

        Annual figures get `FY`. Interim ones get the half they end in — a
        European issuer reporting twice a year has no Q1, and labelling a
        June-ending half as `Q2` would put a six-month flow in a slot every
        downstream annualisation treats as three months.
        """
        if kind == "FY":
            return "FY"
        return "H1" if period_end.month <= 6 else "H2"

    @staticmethod
    def _currency(handle) -> str:
        try:
            return handle.info.get("financialCurrency") or handle.info.get(
                "currency"
            ) or "USD"
        except Exception:  # noqa: BLE001
            return "USD"

    @staticmethod
    def _value(frame, key: str, column) -> float | None:
        """First mapped row that is present AND has a number in this column.

        Both halves matter. A row can exist in the frame and be NaN for one
        period — Nestlé's 2021 revenue is exactly that — and returning the NaN
        rather than falling through to the alternative row would propagate it
        into the ratio base, where `bool(nan)` is True and every guard passes it.
        """
        import math

        for row in ROW_MAP[key]:
            if row not in frame.index:
                continue
            try:
                value = float(frame.at[row, column])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(value):
                return value
        return None
