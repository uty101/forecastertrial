"""Typed config. No magic numbers in prompts, no secrets in code."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from forecaster.schemas import LambdaPreset


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORECASTER_", env_file=".env")

    # The three credentials are read WITHOUT the FORECASTER_ prefix, and the
    # aliases are the whole point.
    #
    # `env_prefix` applies to every field, so these used to want
    # FORECASTER_ANTHROPIC_API_KEY while .env.example documented
    # ANTHROPIC_API_KEY. Anyone following the template got a Settings object with
    # three empty strings and no error — SEC disabled, no LLM, no FRED — and the
    # symptom was "the data sources don't work", which sends you debugging the
    # network instead of the config. It survived until the first time real
    # credentials were used, because nothing else reads them.
    #
    # Unprefixed is also the correct name: ANTHROPIC_API_KEY is what the
    # Anthropic SDK itself reads, so a key already exported for any other tool
    # works here without being copied under a second name.
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    sec_identity: str = Field(default="", validation_alias="SEC_IDENTITY")
    fred_api_key: str = Field(default="", validation_alias="FRED_API_KEY")

    # Every credential below must be DECLARED even while unused, because the
    # model forbids extra inputs: a key pasted into .env for a field that does
    # not exist here stops the CLI from starting at all, with a pydantic
    # traceback rather than anything resembling a config error. Declaring them
    # up front means adding a key is a one-line edit to .env and nothing else.
    lse_api_key: str = Field(default="", validation_alias="LSE_API_KEY")
    lse_base_url: str = Field(default="", validation_alias="LSE_BASE_URL")
    exa_api_key: str = Field(default="", validation_alias="EXA_API_KEY")
    tavily_api_key: str = Field(default="", validation_alias="TAVILY_API_KEY")
    polygon_api_key: str = Field(default="", validation_alias="POLYGON_API_KEY")
    fmp_api_key: str = Field(default="", validation_alias="FMP_API_KEY")

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
    #
    # Raised from 12 when 8-K exhibits became separately citable: one earnings
    # 8-K is now three documents (cover page, EX-99.1 press release, EX-99.2 CFO
    # commentary), so the doc counter started binding three times sooner for no
    # change in how much was actually read. The token budget below is the
    # meaningful ceiling and is the one that should bind.
    max_docs_per_source: int = 20
    max_tokens_per_acquire: int = 60_000
    acquire_deadline_s: int = 90

    # "A single run of a model is a coin flip wearing a suit."
    runs_per_config: int = 5

    default_preset: LambdaPreset = LambdaPreset.SHRINK
    cache_dir: Path = Path("data/cache")
    out_dir: Path = Path("out")
    seed: int = 0


settings = Settings()
