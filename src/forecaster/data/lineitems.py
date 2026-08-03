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
    # A company sitting on tens of billions of cash earns real money on it, and
    # it lands in other income where it is invisible as a driver.
    LineItem("interest_income", "Interest income", "USD", "income", "flow",
             ("InvestmentIncomeInterest",)),
    # `OtherNonoperatingIncomeExpense` is the residual line and
    # `NonoperatingIncomeExpense` the total, so the total leads — but a great
    # many filers tag only the residual. AMD has 286 facts for it and none at
    # all for the total, which read as "this company has no non-operating
    # income" rather than as a missing tag.
    LineItem("other_income", "Other income, net", "USD", "income", "flow",
             ("NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense")),
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
    # The model links D&A and capex through net PP&E, so without this the whole
    # investing side of the roll-forward has no opening balance to move.
    LineItem("ppe_net", "Property, plant and equipment, net", "USD",
             "balance", "stock",
             ("PropertyPlantAndEquipmentNet",), core=True),
    LineItem("equity", "Shareholders' equity", "USD", "balance", "stock",
             ("StockholdersEquity",
              "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
             core=True),

    # ---- balance sheet: the rest of it ----------------------------------- #
    #
    # Without these the extracted balance sheet does not add up, and a model
    # built on the subset has to plug the difference into equity. For NVDA that
    # plug was 123.9bn against 195.5bn of reported equity — the omitted lines
    # were larger than most of the ones we carried.
    LineItem("goodwill", "Goodwill", "USD", "balance", "stock", ("Goodwill",)),
    LineItem("intangibles", "Intangible assets, net", "USD", "balance", "stock",
             ("IntangibleAssetsNetExcludingGoodwill",
              "FiniteLivedIntangibleAssetsNet")),
    LineItem("other_current_assets", "Other current assets", "USD",
             "balance", "stock",
             ("PrepaidExpenseAndOtherAssetsCurrent", "OtherAssetsCurrent")),
    LineItem("other_assets", "Other non-current assets", "USD",
             "balance", "stock", ("OtherAssetsNoncurrent",)),
    LineItem("accrued_liabilities", "Accrued liabilities", "USD",
             "balance", "stock",
             ("AccruedLiabilitiesCurrent", "AccruedLiabilitiesCurrentAndNoncurrent")),
    LineItem("deferred_revenue", "Deferred revenue", "USD", "balance", "stock",
             ("ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent")),
    LineItem("short_term_debt", "Short-term debt", "USD", "balance", "stock",
             ("LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings")),
    LineItem("other_liabilities", "Other non-current liabilities", "USD",
             "balance", "stock", ("OtherLiabilitiesNoncurrent",)),
    # Where net income lands. Without it the equity roll-forward has no anchor
    # and every quarter's retained balance has to be inferred.
    LineItem("retained_earnings", "Retained earnings", "USD", "balance", "stock",
             ("RetainedEarningsAccumulatedDeficit",), core=True),
    LineItem("deferred_tax_assets", "Deferred tax assets, net", "USD",
             "balance", "stock",
             ("DeferredIncomeTaxAssetsNet", "DeferredTaxAssetsNetNoncurrent")),
    LineItem("taxes_payable", "Income taxes payable", "USD", "balance", "stock",
             ("TaxesPayableCurrent", "AccruedIncomeTaxesCurrent")),
    LineItem("operating_lease_assets", "Operating lease right-of-use assets",
             "USD", "balance", "stock", ("OperatingLeaseRightOfUseAsset",)),
    LineItem("long_term_investments", "Long-term investments", "USD",
             "balance", "stock",
             ("MarketableSecuritiesNoncurrent", "LongTermInvestments",
              "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent")),
    LineItem("treasury_stock", "Treasury stock", "USD", "balance", "stock",
             ("TreasuryStockValue", "TreasuryStockCommonValue")),
    # AMD spells APIC `AdditionalPaidInCapitalCommonStock` and reports 63.9bn
    # under it while `AdditionalPaidInCapital` — NVDA's spelling — is empty.
    LineItem("paid_in_capital", "Paid-in capital", "USD", "balance", "stock",
             ("AdditionalPaidInCapital", "AdditionalPaidInCapitalCommonStock",
              "CommonStockIncludingAdditionalPaidInCapital", "CommonStockValue")),
    LineItem("aoci", "Accumulated other comprehensive income", "USD",
             "balance", "stock",
             ("AccumulatedOtherComprehensiveIncomeLossNetOfTax",)),
    # The filer's own total. This is what `assets == liabilities + equity` gets
    # checked against, so it is the anchor for completeness rather than a line
    # anyone forecasts.
    LineItem("liabilities_and_equity", "Total liabilities and equity", "USD",
             "balance", "stock", ("LiabilitiesAndStockholdersEquity",), core=True),

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
    # Four spellings of the same cash-flow add-back, and filers move between
    # them. NVDA tags `DepreciationAndAmortization` 150 times and the depletion
    # variant 43, so listing only the latter saw a third of the history.
    LineItem("depreciation", "D&A", "USD", "cashflow", "flow",
             ("DepreciationDepletionAndAmortization",
              "DepreciationAndAmortization",
              "DepreciationAmortizationAndAccretionNet",
              "Depreciation")),
    LineItem("sbc", "Stock-based compensation", "USD", "cashflow", "flow",
             ("ShareBasedCompensation",), core=True),
    LineItem("buyback", "Share repurchases", "USD", "cashflow", "flow",
             ("PaymentsForRepurchaseOfCommonStock",)),
    # Cash out and equity down. Small for NVDA, decisive for a mature payer, and
    # a missing dividend line makes the equity roll-forward drift every quarter
    # by exactly the amount paid.
    LineItem("dividends", "Dividends paid", "USD", "cashflow", "flow",
             ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock")),

    # ---- cash flow: the rest of it --------------------------------------- #
    #
    # The working-capital movements AS THE FILER REPORTED THEM. Differencing two
    # balance-sheet levels gives a different number whenever an acquisition, a
    # reclassification or an FX translation moved the balance without cash
    # moving — so the reported line is the truth and the difference is a proxy.
    #
    # Sign convention: `IncreaseDecreaseInAccountsReceivable` is POSITIVE when
    # receivables grew, which CONSUMES cash. The cash flow statement therefore
    # subtracts it. Getting this backwards is the error that leaves the model
    # balanced and the cash flow saying the opposite of the truth.
    LineItem("cf_receivables", "Change in receivables (as reported)", "USD",
             "cashflow", "flow", ("IncreaseDecreaseInAccountsReceivable",)),
    LineItem("cf_inventory", "Change in inventory (as reported)", "USD",
             "cashflow", "flow", ("IncreaseDecreaseInInventories",)),
    LineItem("cf_payables", "Change in payables (as reported)", "USD",
             "cashflow", "flow", ("IncreaseDecreaseInAccountsPayable",)),
    LineItem("acquisitions", "Acquisitions, net of cash", "USD",
             "cashflow", "flow", ("PaymentsToAcquireBusinessesNetOfCashAcquired",)),
    LineItem("debt_issued", "Debt issued", "USD", "cashflow", "flow",
             ("ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt")),
    LineItem("debt_repaid", "Debt repaid", "USD", "cashflow", "flow",
             ("RepaymentsOfDebt", "RepaymentsOfLongTermDebt")),
    LineItem("stock_issued", "Stock issued", "USD", "cashflow", "flow",
             ("ProceedsFromIssuanceOfCommonStock",)),
    LineItem("fx_on_cash", "FX effect on cash", "USD", "cashflow", "flow",
             ("EffectOfExchangeRateOnCashAndCashEquivalents",
              "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCash"
              "AndRestrictedCashEquivalents")),
    # The filer's own total. `cfo + cfi + cff + fx` is checked against this, so
    # it is the completeness anchor for the cash flow statement.
    LineItem("net_change_cash", "Net change in cash", "USD", "cashflow", "flow",
             ("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
              "PeriodIncreaseDecreaseIncludingExchangeRateEffect",
              "CashAndCashEquivalentsPeriodIncreaseDecrease")),
)

BY_KEY: dict[str, LineItem] = {item.key: item for item in LINE_ITEMS}

CORE_KEYS: tuple[str, ...] = tuple(i.key for i in LINE_ITEMS if i.core)
