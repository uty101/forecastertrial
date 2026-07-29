"""Typed config. No magic numbers in prompts, no secrets in code."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from forecaster.schemas import LambdaPreset


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORECASTER_", env_file=".env")

    anthropic_api_key: str = ""
    sec_identity: str = ""
    fred_api_key: str = ""

    # Model tiering — tokens are a variable cost, allocated by leverage.
    model_cheap: str = "claude-haiku-4-5"   # retrieval, extraction
    model_mid: str = "claude-sonnet-5"      # the seven lenses, the advocate
    model_deep: str = "claude-opus-5"       # the judge: one call, highest leverage

    # Thinking depth. `high` is the API default; the judge is the one call where
    # `xhigh` is worth the tokens, and F/G are plain code either way. Note the
    # sampling parameters (temperature, top_p) are rejected on these models —
    # k=5 run variance comes from adaptive thinking, not from a temperature dial.
    effort: str = "high"

    # Hard kill switch. A runaway loop at 14:00 ends your day.
    cost_ceiling_usd: float = 25.0

    # Acquisition budgets — unbounded research is how you lose the afternoon.
    max_docs_per_source: int = 12
    max_tokens_per_acquire: int = 60_000
    acquire_deadline_s: int = 90

    # "A single run of a model is a coin flip wearing a suit."
    runs_per_config: int = 5

    default_preset: LambdaPreset = LambdaPreset.SHRINK
    cache_dir: Path = Path("data/cache")
    out_dir: Path = Path("out")
    seed: int = 0


settings = Settings()
