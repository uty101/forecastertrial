"""
Template DataSource adapter for the sponsor's earnings data feed.

INSTRUCTIONS FOR TOMORROW:
1. Copy this file to src/forecaster/data/your_sponsor_source.py
2. Replace TODO markers with your implementation
3. Add to loader.py: one line in the sources list
4. Test with: uv run forecast sources --ticker NVDA
5. Run pipeline: uv run forecast run --ticker YOUR_TICKER --asof 2026-08-16

This template follows the DataSource protocol (see protocol.py).
Keep the type hints and Pydantic models — they are validated at runtime.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

from forecaster.data.protocol import (
    DataSource,
    Estimate,
    Guidance,
    PointInTimeViolation,
)


logger = logging.getLogger(__name__)


class YourSponsorDataSource(DataSource):
    """
    Adapter for the sponsor's earnings data feed.
    
    Replace "YourSponsor" with actual name.
    """

    def __init__(self, api_key: str, base_url: str = "https://api.example.com"):
        """
        Initialize the data source.
        
        Args:
            api_key: API key for authentication (should come from env var)
            base_url: Base URL for the API (check the feed documentation)
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = 30  # seconds
        self.client = httpx.AsyncClient(timeout=self.timeout)

    async def earnings_estimates(
        self, ticker: str, as_of: datetime
    ) -> list[Estimate]:
        """
        Fetch consensus EPS estimates as they stood on as_of date.
        
        CRITICAL: No data filed after as_of.
        
        Args:
            ticker: Company ticker (e.g., "AAPL")
            as_of: Point-in-time date (e.g., "2026-08-15")
        
        Returns:
            List of Estimate objects with EPS consensus
        
        Raises:
            PointInTimeViolation: If any returned estimate was filed after as_of
        """
        try:
            # TODO: Fetch from your API
            response = await self.client.get(
                f"{self.base_url}/v1/estimates",
                params={
                    "ticker": ticker,
                    "as_of": as_of.isoformat(),
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            data = response.json()

            estimates = []
            for item in data.get("estimates", []):
                # TODO: Map your feed schema to Estimate fields
                # Expected fields:
                #   - fiscal_year: int (e.g., 2026)
                #   - fiscal_quarter: int (1-4)
                #   - eps: float (e.g., 2.15)
                #   - filed_date: datetime (when estimate was published)
                #   - basis: str ("GAAP" or "NON_GAAP") — CHECK YOUR FEED!

                filed_date = datetime.fromisoformat(item["filed_date"])

                # CRITICAL: Validate point-in-time
                if filed_date > as_of:
                    raise PointInTimeViolation(
                        f"Estimate filed {filed_date} is after as_of {as_of}"
                    )

                estimate = Estimate(
                    ticker=ticker,
                    fiscal_year=item["fiscal_year"],
                    fiscal_quarter=item["fiscal_quarter"],
                    eps=float(item["eps"]),
                    filed_date=filed_date,
                    source="YourSponsor",  # Your source name
                    basis=item.get("basis", "NON_GAAP"),  # GAAP or NON_GAAP
                )
                estimates.append(estimate)

            logger.info(
                f"Fetched {len(estimates)} estimates for {ticker} as_of {as_of}"
            )
            return estimates

        except PointInTimeViolation:
            raise  # Re-raise point-in-time violations
        except httpx.HTTPStatusError as e:
            logger.error(
                f"API error fetching estimates for {ticker}: {e.response.status_code}"
            )
            return []  # Fail gracefully, return empty list
        except Exception as e:
            logger.error(f"Error fetching estimates for {ticker}: {e}")
            return []

    async def guidance_history(self, ticker: str, as_of: datetime) -> list[Guidance]:
        """
        Fetch company guidance issued before as_of.
        
        CRITICAL: No guidance issued after as_of.
        
        Args:
            ticker: Company ticker
            as_of: Point-in-time date
        
        Returns:
            List of Guidance objects
        
        Raises:
            PointInTimeViolation: If any guidance was issued after as_of
        """
        try:
            # TODO: Fetch guidance from your API
            response = await self.client.get(
                f"{self.base_url}/v1/guidance",
                params={
                    "ticker": ticker,
                    "as_of": as_of.isoformat(),
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            data = response.json()

            guidance_list = []
            for item in data.get("guidance", []):
                # TODO: Map your feed schema to Guidance fields
                # Expected fields:
                #   - fiscal_year: int
                #   - fiscal_quarter: int
                #   - guidance_type: str ("EPS" or "REVENUE")
                #   - low: float, high: float (or mid: float)
                #   - issued_date: datetime
                #   - basis: str ("GAAP" or "NON_GAAP")

                issued_date = datetime.fromisoformat(item["issued_date"])

                # CRITICAL: Validate point-in-time
                if issued_date > as_of:
                    raise PointInTimeViolation(
                        f"Guidance issued {issued_date} is after as_of {as_of}"
                    )

                guidance = Guidance(
                    ticker=ticker,
                    fiscal_year=item["fiscal_year"],
                    fiscal_quarter=item["fiscal_quarter"],
                    guidance_type=item.get("guidance_type", "EPS"),
                    low=float(item.get("low")),
                    high=float(item.get("high")),
                    issued_date=issued_date,
                    source="YourSponsor",
                    basis=item.get("basis", "NON_GAAP"),
                )
                guidance_list.append(guidance)

            logger.info(
                f"Fetched {len(guidance_list)} guidance items for {ticker} as_of {as_of}"
            )
            return guidance_list

        except PointInTimeViolation:
            raise
        except httpx.HTTPStatusError as e:
            logger.error(
                f"API error fetching guidance for {ticker}: {e.response.status_code}"
            )
            return []
        except Exception as e:
            logger.error(f"Error fetching guidance for {ticker}: {e}")
            return []

    async def close(self):
        """Clean up HTTP client."""
        await self.client.aclose()
