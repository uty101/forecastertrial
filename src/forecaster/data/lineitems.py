"""The line items a three-statement model is built from, and their XBRL tags.

Everything downstream keys off the canonical names here rather than off US-GAAP
tag strings, because the tags are not stable across filers or across time. NVDA
reports revenue as `RevenueFromContractWithCustomerExcludingAssessedTax`; older
filings use `SalesRevenueNet`; some filers use `Revenues`. A model that hardcodes
one of them silently produces an empty line for everyone else, and an empty line
in a linked model is not an error — it is a zero that propagates.

So each item lists its tags in PREFERENCE ORDER and the first one that returns
facts wins. `sec_source._concept` already works this way; this file is what
turns three hardcoded tag groups into a full statement.

**Flow vs stock is load-bearing and is declared, not inferred.** A flow item
(revenue, net income, capex) covers a period and has both `start` and `end`; a
stock item (cash, inventory, equity) is a balance at an instant and has only
`end`. Getting this wrong is the units error that stays internally consistent:
you can sum four quarters of cash balances and get a number that looks like a
year of cash generation and is meaningless.

Only the items an earnings forecast actually needs are here. A complete US-GAAP
taxonomy is thousands of concepts, most of which do not move a quarterly EPS
number, and every extra line is another thing to reconcile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Statement = Literal["income", "balance", "cashflow", "shares"]
Kind = Literal["flow", "stock"]


@dataclass(frozen=True)
class LineItem:
    key: str
    label: str
    unit: str
    statement: Statement
    kind: Kind
    tags: tuple[str, ...]
    """True when the item is expected to be present for essentially every filer.
    Used to tell "this company does not report it" from "the tag map is wrong",
    which are the same symptom and very different bugs."""
    core: bool = False
    """False for anything that is a RATIO or an AVERAGE rather than a total.

    Q4 is not filed separately and has to come out as FY − (Q1+Q2+Q3), which is
    valid for a total and nonsense for a ratio: EPS has a different denominator
    every quarter, and weighted-average share counts do not add up either.
    Deriving Q4 EPS that way produced −4.49 for a quarter that earned $22.1bn.

    Non-additive items simply have no Q4 unless the filer tagged one. That gap is
    the honest answer, and EPS can be recomputed from net income and shares by
    anything that needs it."""
    additive: bool = True


LINE_ITEMS: tuple[LineItem, ...] = (
    # ---- income statement ------------------------------------------------ #
    LineItem(
        "revenue", "Revenue", "USD", "income", "flow",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ),
        core=True,
    ),
    LineItem(
        "cost_of_revenue", "Cost of revenue", "USD", "income", "flow",
        ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
        core=True,
    ),
    LineItem("gross_profit", "Gross profit", "USD", "income", "flow",
             ("GrossProfit",), core=True),
    LineItem("rnd", "R&D", "USD", "income", "flow",
             ("ResearchAndDevelopmentExpense",)),
    LineItem("sgna", "SG&A", "USD", "income", "flow",
             ("SellingGeneralAndAdministrativeExpense",
              "GeneralAndAdministrativeExpense")),
    LineItem("opex", "Operating expenses", "USD", "income", "flow",
             ("OperatingExpenses", "CostsAndExpenses")),
    LineItem("operating_income", "Operating income", "USD", "income", "flow",
             ("OperatingIncomeLoss",), core=True),
    LineItem("interest_expense", "Interest expense", "USD", "income", "flow",
             ("InterestExpense", "InterestIncomeExpenseNet")),
    LineItem("other_income", "Other income, net", "USD", "income", "flow",
             ("NonoperatingIncomeExpense",)),
    LineItem(
        "pretax_income", "Pre-tax income", "USD", "income", "flow",
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ),
    ),
    LineItem("tax", "Income tax", "USD", "income", "flow",
             ("IncomeTaxExpenseBenefit",)),
    LineItem("net_income", "Net income", "USD", "income", "flow",
             ("NetIncomeLoss", "ProfitLoss"), core=True),

    # ---- per share ------------------------------------------------------- #
    LineItem("eps_diluted", "Diluted EPS (GAAP)", "USD/shares", "shares", "flow",
             ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
             core=True, additive=False),
    LineItem("eps_basic", "Basic EPS (GAAP)", "USD/shares", "shares", "flow",
             ("EarningsPerShareBasic",), additive=False),
    LineItem(
        "diluted_shares", "Diluted shares", "shares", "shares", "flow",
        ("WeightedAverageNumberOfDilutedSharesOutstanding",
         "WeightedAverageNumberOfSharesOutstandingBasic"),
        core=True, additive=False,
    ),

    # ---- balance sheet (instants) ---------------------------------------- #
    LineItem("cash", "Cash and equivalents", "USD", "balance", "stock",
             ("CashAndCashEquivalentsAtCarryingValue",), core=True),
    LineItem("short_term_investments", "Short-term investments", "USD",
             "balance", "stock",
             ("ShortTermInvestments", "MarketableSecuritiesCurrent",
              "AvailableForSaleSecuritiesDebtSecuritiesCurrent")),
    LineItem("receivables", "Accounts receivable", "USD", "balance", "stock",
             ("AccountsReceivableNetCurrent",), core=True),
    LineItem("inventory", "Inventory", "USD", "balance", "stock",
             ("InventoryNet",), core=True),
    LineItem("current_assets", "Current assets", "USD", "balance", "stock",
             ("AssetsCurrent",)),
    LineItem("total_assets", "Total assets", "USD", "balance", "stock",
             ("Assets",), core=True),
    LineItem("payables", "Accounts payable", "USD", "balance", "stock",
             ("AccountsPayableCurrent",)),
    LineItem("current_liabilities", "Current liabilities", "USD", "balance",
             "stock", ("LiabilitiesCurrent",)),
    LineItem("total_liabilities", "Total liabilities", "USD", "balance", "stock",
             ("Liabilities",), core=True),
    LineItem("long_term_debt", "Long-term debt", "USD", "balance", "stock",
             ("LongTermDebtNoncurrent", "LongTermDebt")),
    LineItem("equity", "Shareholders' equity", "USD", "balance", "stock",
             ("StockholdersEquity",
              "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
             core=True),

    # ---- cash flow ------------------------------------------------------- #
    LineItem("cfo", "Cash from operations", "USD", "cashflow", "flow",
             ("NetCashProvidedByUsedInOperatingActivities",
              "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
             core=True),
    LineItem("cfi", "Cash from investing", "USD", "cashflow", "flow",
             ("NetCashProvidedByUsedInInvestingActivities",)),
    LineItem("cff", "Cash from financing", "USD", "cashflow", "flow",
             ("NetCashProvidedByUsedInFinancingActivities",)),
    LineItem("capex", "Capital expenditure", "USD", "cashflow", "flow",
             ("PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets")),
    LineItem("depreciation", "D&A", "USD", "cashflow", "flow",
             ("DepreciationDepletionAndAmortization",
              "DepreciationAmortizationAndAccretionNet")),
    LineItem("sbc", "Stock-based compensation", "USD", "cashflow", "flow",
             ("ShareBasedCompensation",), core=True),
    LineItem("buyback", "Share repurchases", "USD", "cashflow", "flow",
             ("PaymentsForRepurchaseOfCommonStock",)),
)

BY_KEY: dict[str, LineItem] = {item.key: item for item in LINE_ITEMS}

CORE_KEYS: tuple[str, ...] = tuple(i.key for i in LINE_ITEMS if i.core)
