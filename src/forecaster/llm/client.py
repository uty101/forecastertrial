"""The only place this repo talks to a model.

Five things it does that a bare `messages.create` does not, each of which exists
because of a specific way the day goes wrong:

1. **Schema-forced output.** Every response is validated against a pydantic
   model before it is returned. Fail closed — a lens that returns prose where a
   float belongs is dropped, not coerced. `response.parsed_output` is the whole
   point of `messages.parse`.

2. **Content-hash caching.** You will re-run the judge forty times while tuning.
   Without this you re-pay for acquisition every time and `make verify` cannot
   be byte-identical. The key includes the prompt's text fingerprint, so editing
   a prompt invalidates its cached answers — otherwise you would tune a prompt
   and score the old one's output.

3. **A hard cost ceiling.** A loop burning credits at 14:00 ends the day. This
   raises *before* the call that would breach it, not after.

4. **Prompt caching of the shared corpus.** Seven lenses fan out against the
   same evidence store. The corpus goes in `system` behind a cache breakpoint
   and the lens-specific question goes in the user turn — so the corpus is
   written once and read six times at a tenth of the price.

5. **Retry on transient errors only.** Backoff on rate limits and 5xx; fail
   fast on schema errors. Retrying malformed output mostly just costs money.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from forecaster.config import Settings
from forecaster.config import settings as default_settings
from forecaster.data.cache import Cache
from forecaster.llm.prompt import Prompt, load

log = structlog.get_logger()

# Adaptive thinking and the `effort` parameter are NOT universal, and sending
# them to a model that lacks them is a hard 400, not a warning:
#
#   anthropic.BadRequestError: adaptive thinking is not supported on this model
#
# Haiku 4.5 is the one in our tier set that accepts neither, and it is the CHEAP
# tier — which every extraction prompt runs on. So this took down guidance
# extraction outright, and would have taken down any cheap-tier prompt on the
# day, at the point where there is no time to debug an SDK error.
#
# Prefix-matched rather than listed exactly, because a dated snapshot id
# (`claude-haiku-4-5-20251001`) is the same model with the same limitation.
_NO_REASONING_CONTROLS = ("claude-haiku",)


def _reasoning_kwargs(model: str, effort: str) -> dict:
    """Thinking and effort, for models that have them."""
    if model.startswith(_NO_REASONING_CONTROLS):
        return {}
    return {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }

T = TypeVar("T", bound=BaseModel)


# --------------------------------------------------------------------------- #
# pricing — USD per million tokens, from the published rate card
# --------------------------------------------------------------------------- #

# Cache writes cost 1.25x base input; cache reads cost 0.1x. With seven lenses
# fanning out against one corpus, that read multiplier is most of the reason
# this pipeline is affordable to run five times per config.
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10

PRICING: dict[str, tuple[float, float]] = {
    # model id: (input $/Mtok, output $/Mtok)
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Sonnet 5 carries introductory pricing of $2/$10 through 2026-08-31, which
# covers the whole prep window and the event itself. Costing at the full rate
# means the number on the slide is an over-estimate, never an under-estimate.


class LLMError(RuntimeError):
    pass


class CostCeilingExceeded(LLMError):
    """The kill switch. Deliberately fatal and deliberately checked before the
    call rather than after — an overspend you detect afterwards is an overspend
    you already paid for."""


class SchemaRejected(LLMError):
    """Model output did not validate. Not retried: a model that returns the
    wrong shape once usually returns it again, and the retry costs money."""


class Refused(LLMError):
    """`stop_reason == "refusal"`. Vanishingly unlikely on earnings prompts, but
    reading `content[0]` without checking is how it would surface — as a
    confusing IndexError at 15:20 rather than a clear message."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    cache_hit: bool = False
    model: str = ""

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens + other.cache_creation_input_tokens
            ),
            cache_read_input_tokens=(
                self.cache_read_input_tokens + other.cache_read_input_tokens
            ),
            cost_usd=self.cost_usd + other.cost_usd,
            latency_ms=self.latency_ms + other.latency_ms,
        )


def price(model: str, usage: Usage) -> float:
    """Cost of one call in USD. Unknown models price at the most expensive
    tier — an over-estimate is a safe failure, an under-estimate is not."""
    rate_in, rate_out = PRICING.get(model, max(PRICING.values()))
    return (
        usage.input_tokens * rate_in
        + usage.cache_creation_input_tokens * rate_in * CACHE_WRITE_MULT
        + usage.cache_read_input_tokens * rate_in * CACHE_READ_MULT
        + usage.output_tokens * rate_out
    ) / 1_000_000


@dataclass
class CallRecord:
    """One row of the run manifest. Goes into the UI's cost line, so the token
    figure on stage is measured rather than asserted."""

    prompt_id: str
    prompt_version: int
    model: str
    tier: str
    run_index: int
    usage: Usage


@dataclass
class LLMClient:
    """One instance per run. Holds the spend counter and the response cache."""

    cache: Cache
    settings: Settings = field(default_factory=lambda: default_settings)
    calls: list[CallRecord] = field(default_factory=list)
    _client: object | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ #

    @property
    def spent_usd(self) -> float:
        return sum(c.usage.cost_usd for c in self.calls)

    @staticmethod
    def supports_reasoning_controls(model: str) -> str:
        """Exposed for the manifest, so the UI can say which tier thinks."""
        return "" if model.startswith(_NO_REASONING_CONTROLS) else "adaptive"

    def model_for(self, tier: str) -> str:
        return {
            "cheap": self.settings.model_cheap,
            "mid": self.settings.model_mid,
            "deep": self.settings.model_deep,
        }[tier]

    def report(self) -> dict:
        """Per-stage token accounting for the run manifest and the UI."""
        by_prompt: dict[str, dict] = {}
        for call in self.calls:
            row = by_prompt.setdefault(
                call.prompt_id,
                {"calls": 0, "input": 0, "output": 0, "cost_usd": 0.0, "cached": 0},
            )
            row["calls"] += 1
            row["input"] += call.usage.input_tokens + call.usage.cache_read_input_tokens
            row["output"] += call.usage.output_tokens
            row["cost_usd"] = round(row["cost_usd"] + call.usage.cost_usd, 6)
            row["cached"] += int(call.usage.cache_hit)
        return {
            "total_cost_usd": round(self.spent_usd, 4),
            "ceiling_usd": self.settings.cost_ceiling_usd,
            "total_calls": len(self.calls),
            "by_prompt": by_prompt,
        }

    # ------------------------------------------------------------------ #

    def _sdk(self):
        if self._client is None:
            import anthropic

            if not self.settings.anthropic_api_key:
                raise LLMError(
                    "ANTHROPIC_API_KEY is unset. Run with --from-cache to replay a "
                    "recorded run, or set the key in .env."
                )
            self._client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key,
                max_retries=0,  # we own the retry policy; see _with_retry
            )
        return self._client

    def _key(
        self,
        prompt: Prompt,
        model: str,
        variables: dict,
        corpus: str,
        run_index: int,
        schema: type[BaseModel],
    ) -> str:
        payload = json.dumps(
            {
                "prompt": prompt.fingerprint,
                "model": model,
                "effort": self.settings.effort,
                "schema": schema.__name__,
                "variables": variables,
                "corpus": hashlib.sha256(corpus.encode()).hexdigest()[:16],
                "run": run_index,
                "seed": self.settings.seed,
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
        return f"llm/{prompt.id}/v{prompt.version}/{digest}"

    # ------------------------------------------------------------------ #

    def call(
        self,
        prompt_id: str,
        schema: type[T],
        variables: dict | None = None,
        *,
        corpus: str = "",
        run_index: int = 0,
        max_tokens: int = 8000,
    ) -> tuple[T, Usage]:
        """One schema-validated model call.

        `corpus` is the shared evidence block. It is placed in `system` behind a
        cache breakpoint so that a fan-out of lenses writes it once and reads it
        six times — put anything that varies per lens in `variables` instead, or
        the cache silently never hits.
        """
        variables = variables or {}
        prompt = load(prompt_id)
        model = self.model_for(prompt.model_tier)
        key = self._key(prompt, model, variables, corpus, run_index, schema)

        cached = self.cache.get(key)
        if cached is not None:
            usage = Usage(**cached["usage"])
            usage.cache_hit = True
            self.calls.append(
                CallRecord(prompt.id, prompt.version, model, prompt.model_tier,
                           run_index, usage)
            )
            return schema.model_validate(cached["parsed"]), usage

        if self.cache.read_only:
            from forecaster.data.cache import CacheMiss

            raise CacheMiss(
                f"{key} not cached and cache is read-only. `make verify` replays a "
                "recorded run; populate it once without --from-cache."
            )

        self._check_ceiling()
        parsed, usage = self._live_call(prompt, schema, variables, corpus,
                                        run_index, model, max_tokens)

        self.cache.put(key, {"parsed": parsed.model_dump(mode="json"),
                             "usage": _usage_dict(usage)})
        self.calls.append(
            CallRecord(prompt.id, prompt.version, model, prompt.model_tier,
                       run_index, usage)
        )
        return parsed, usage

    # ------------------------------------------------------------------ #

    def _check_ceiling(self) -> None:
        if self.spent_usd >= self.settings.cost_ceiling_usd:
            raise CostCeilingExceeded(
                f"spent ${self.spent_usd:.2f} of ${self.settings.cost_ceiling_usd:.2f} "
                f"ceiling across {len(self.calls)} calls — stopping before the next "
                "call rather than after it"
            )

    def _live_call(
        self,
        prompt: Prompt,
        schema: type[T],
        variables: dict,
        corpus: str,
        run_index: int,
        model: str,
        max_tokens: int,
    ) -> tuple[T, Usage]:
        system_text, user_text = prompt.render(variables)

        # Render order is tools -> system -> messages, and caching is a PREFIX
        # match. So the corpus goes first and the breakpoint goes after it; the
        # per-prompt instructions follow, outside the cached region.
        #
        # This was the other way round — instructions first, corpus second — and
        # the comment justifying it said "stable content first". The corpus is
        # stable across the fan-out; the instructions are not, since each lens
        # has its own. With a per-lens block in front of the breakpoint the
        # prefix differed on every call, so eight lenses each WROTE the corpus at
        # the 1.25x write rate and none of them ever read one. A live run showed
        # cached_in=0 on every single call, which is what sent me looking.
        system_blocks: list[dict] = []
        if corpus:
            system_blocks.append(
                {
                    "type": "text",
                    "text": corpus,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        system_blocks.append({"type": "text", "text": system_text})

        # k>1 runs must actually differ. Sampling parameters are rejected on
        # these models, so vary the prompt instead — this is the only honest way
        # to measure "a single run of a model is a coin flip wearing a suit".
        if run_index:
            user_text = (
                f"{user_text}\n\n(Independent analysis pass {run_index + 1}. Reason "
                "from the evidence again from the start; do not anchor on a "
                "previous answer.)"
            )

        started = time.monotonic()
        response = self._with_retry(
            lambda: self._sdk().messages.parse(
                model=model,
                max_tokens=max_tokens,
                system=system_blocks,
                messages=[{"role": "user", "content": user_text}],
                output_format=schema,
                **_reasoning_kwargs(model, self.settings.effort),
            )
        )
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            raise Refused(
                f"{prompt.id}: model declined "
                f"({getattr(response.stop_details, 'category', None)})"
            )

        parsed = response.parsed_output
        if parsed is None:
            # `stop_reason == "max_tokens"` is the usual cause: the schema was
            # half-written when the budget ran out.
            raise SchemaRejected(
                f"{prompt.id}: no parsed output (stop_reason={response.stop_reason}). "
                f"Raise max_tokens above {max_tokens} if this is truncation."
            )

        raw = response.usage
        usage = Usage(
            input_tokens=raw.input_tokens,
            output_tokens=raw.output_tokens,
            cache_creation_input_tokens=raw.cache_creation_input_tokens or 0,
            cache_read_input_tokens=raw.cache_read_input_tokens or 0,
            latency_ms=latency_ms,
            model=model,
        )
        usage.cost_usd = price(model, usage)

        log.info(
            "llm_call",
            prompt=prompt.id,
            version=prompt.version,
            model=model,
            run=run_index,
            in_tokens=usage.input_tokens,
            cached_in=usage.cache_read_input_tokens,
            # Logged beside the read, because the two together are the only way
            # to see the cache working. A run where every call writes and none
            # reads looks identical on `cached_in` alone — it reads as "no cache
            # configured" rather than as "the cache is being paid for and thrown
            # away", which is the more expensive of the two.
            cache_write=usage.cache_creation_input_tokens,
            out_tokens=usage.output_tokens,
            cost_usd=round(usage.cost_usd, 5),
            latency_ms=latency_ms,
        )
        return parsed, usage

    def _with_retry(self, fn):
        """Backoff on transient errors only.

        A rate limit or a 502 is worth waiting out. A schema violation is not —
        the model will produce the same wrong shape and you will pay for it
        twice.
        """
        import anthropic
        from tenacity import (
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            wait_exponential,
        )

        transient = (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        )

        @retry(
            retry=retry_if_exception_type(transient),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            stop=stop_after_attempt(4),
            reraise=True,
        )
        def _attempt():
            try:
                return fn()
            except ValidationError as exc:  # schema mismatch: fail closed, fast
                raise SchemaRejected(str(exc)) from exc

        return _attempt()


def _usage_dict(usage: Usage) -> dict:
    """Latency is excluded from the cached record on purpose — it is wall clock,
    it varies run to run, and `make verify` diffs this file."""
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "cost_usd": usage.cost_usd,
        "model": usage.model,
    }
