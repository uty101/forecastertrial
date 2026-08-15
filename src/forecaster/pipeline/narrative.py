"""
Narrative generation stage: synthesize all lenses and the forecast into a one-pager.

This stage runs AFTER the judge produces a forecast but BEFORE output.
It generates a narrative that explains to judges why the forecast differs from consensus
and where consensus is structurally weak.

Output: JSON with narrative, thesis, and evidence breakdown.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from forecaster.config import Config
from forecaster.llm.client import LLMClient
from forecaster.llm.prompt import load_prompt


logger = logging.getLogger(__name__)


class NarrativeEvidence(BaseModel):
    """One piece of evidence supporting the forecast."""

    evidence: str = Field(..., description="Specific finding from a lens")
    quote: Optional[str] = Field(None, description="Verbatim quote from source if available")
    impact: str = Field(..., description="Impact vs consensus (e.g., '+2.3%')")


class NarrativeOutput(BaseModel):
    """Structured one-pager narrative for judges."""

    title: str = Field(..., description="Title of the analysis")
    thesis: str = Field(..., description="One-sentence core insight")
    our_forecast: str = Field(..., description="Our EPS forecast and confidence")
    consensus_context: str = Field(
        ..., description="Why consensus walked down and what that reveals"
    )
    our_case: dict[str, NarrativeEvidence] = Field(
        ..., description="Top 3 reasons we differ from consensus"
    )
    risks: list[str] = Field(..., description="2–3 risks that would prove us wrong")
    narrative: str = Field(..., description="400–500 word prose narrative for judges")


async def generate_narrative(
    ticker: str,
    forecast_eps: float,
    consensus_eps: float,
    confidence_percent: float,
    lenses: list[dict[str, Any]],
    consensus_history: str,
    model_mae: float,
    comp_range: tuple[float, float],
    regime: str,
    as_of: str,
    fiscal_period: str,
    config: Config,
) -> NarrativeOutput:
    """
    Generate a narrative one-pager explaining the forecast.

    Args:
        ticker: Company ticker
        forecast_eps: Our EPS forecast
        consensus_eps: Current consensus EPS
        confidence_percent: Confidence in forecast (0-100)
        lenses: List of lens outputs (name, impact_bps, key_finding, evidence)
        consensus_history: Recent consensus revision history
        model_mae: Historical model MAE for calibration
        comp_range: (min, max) from comparable company analysis
        regime: Description of current regime (coverage, dispersion, staleness, etc.)
        as_of: Date the forecast is as of
        fiscal_period: Fiscal period being forecast (e.g., "Q3 2026")
        config: Configuration object

    Returns:
        NarrativeOutput with structured one-pager
    """

    # Load prompt template
    prompt_template = load_prompt("narrative_generation", version="1.0")

    # Sort lenses by impact
    lenses_sorted = sorted(lenses, key=lambda x: abs(x.get("impact_bps", 0)), reverse=True)

    # Format lens rankings
    lens_rankings = "\n".join(
        [
            f"**{i + 1}. {lens.get('name', 'Unknown Lens')}** "
            f"(Impact: {lens.get('impact_bps', 0):+.0f} bps)\n"
            f"   Finding: {lens.get('key_finding', 'No finding')}"
            for i, lens in enumerate(lenses_sorted[:9])
        ]
    )

    # Calculate consensus walkdown
    consensus_walkdown_pct = ((forecast_eps - consensus_eps) / consensus_eps) * 100

    # Render prompt
    rendered_prompt = prompt_template.format(
        ticker=ticker,
        fiscal_period=fiscal_period,
        as_of=as_of,
        consensus_eps=consensus_eps,
        forecast_eps=forecast_eps,
        confidence_percent=confidence_percent,
        consensus_history=consensus_history,
        lens_rankings=lens_rankings,
        model_mae=model_mae,
        comp_min=comp_range[0],
        comp_max=comp_range[1],
        regime=regime,
        pct_walkdown=consensus_walkdown_pct,
    )

    logger.info(f"Generating narrative for {ticker} (forecast: ${forecast_eps:.2f})")

    # Call LLM
    client = LLMClient(api_key=config.openai_api_key, model=config.llm_model)

    try:
        response = await client.call(
            system_prompt=prompt_template.system_prompt,
            user_prompt=rendered_prompt,
            response_format="json_object",
            temperature=0.7,
            max_tokens=1200,
        )

        # Parse response
        parsed = json.loads(response)
        output = NarrativeOutput(**parsed)

        logger.info(f"Generated narrative: {output.title}")
        return output

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse narrative response: {e}")
        logger.error(f"Raw response: {response}")
        raise ValueError(f"Narrative LLM returned invalid JSON: {e}")

    except ValueError as e:
        logger.error(f"Narrative validation failed: {e}")
        raise


async def run_narrative_stage(
    ticker: str,
    dossier_path: Path,
    forecast_json: dict[str, Any],
    config: Config,
) -> dict[str, Any]:
    """
    Run the narrative generation stage.

    Args:
        ticker: Company ticker
        dossier_path: Path to dossier directory
        forecast_json: Output from the judge (forecast, confidence, etc.)
        config: Configuration object

    Returns:
        Dictionary with narrative output and metadata
    """

    # Extract forecast data
    forecast_eps = forecast_json.get("forecast_eps")
    consensus_eps = forecast_json.get("consensus_eps")
    confidence = forecast_json.get("confidence_percent", 50.0)

    if forecast_eps is None or consensus_eps is None:
        raise ValueError("Forecast JSON missing forecast_eps or consensus_eps")

    # Extract lens data
    lenses = forecast_json.get("lenses", [])
    if not lenses:
        raise ValueError("No lens outputs available for narrative")

    # Extract model diagnostics
    model_mae = forecast_json.get("model_mae", 0.0)
    comp_range = forecast_json.get("comparable_range", (consensus_eps * 0.95, consensus_eps * 1.05))
    regime = forecast_json.get("regime", "unknown")

    # Read consensus history from dossier
    consensus_file = dossier_path / "consensus_history.json"
    if consensus_file.exists():
        with open(consensus_file) as f:
            consensus_data = json.load(f)
            consensus_history = f"Last 30 days: {len(consensus_data)} revisions"
    else:
        consensus_history = "Historical consensus not available"

    # Generate narrative
    narrative = await generate_narrative(
        ticker=ticker,
        forecast_eps=forecast_eps,
        consensus_eps=consensus_eps,
        confidence_percent=confidence,
        lenses=lenses,
        consensus_history=consensus_history,
        model_mae=model_mae,
        comp_range=comp_range,
        regime=regime,
        as_of=forecast_json.get("as_of", "unknown"),
        fiscal_period=forecast_json.get("fiscal_period", "unknown"),
        config=config,
    )

    logger.info(f"Narrative stage complete for {ticker}")

    return {
        "success": True,
        "ticker": ticker,
        "narrative": narrative.dict(),
    }
