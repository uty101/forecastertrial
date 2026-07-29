"""Versioned prompt loading.

Prompts live in `llm/prompts/*.yaml` and are never inlined in Python. You will
iterate on these a hundred times, and when a backtest number moves you need to
know which prompt version produced it — so the version is loaded with the text
and stamped onto every LLM call's cache key.

That last part is the reason this file exists rather than a `yaml.safe_load`
one-liner: bumping `version` in the YAML must invalidate the response cache. If
it didn't, you would edit a prompt, re-run the backtest, and score the *old*
prompt's cached answers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Formatter
from typing import Any

import yaml

PROMPT_DIR = Path(__file__).parent / "prompts"

# Which model tier a prompt is written for. Cheap models get extraction, mid
# models get the lenses and the advocate, the expensive model gets one judge
# call — tokens are a variable cost allocated by leverage.
TIERS = {"cheap", "mid", "deep"}


class PromptError(RuntimeError):
    """Raised for a malformed or missing prompt. Deliberately fatal — a typo in
    a prompt id should not silently fall through to a default."""


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    model_tier: str
    system: str
    user: str
    description: str = ""

    @property
    def fingerprint(self) -> str:
        """Hash of the actual text, not just the version number.

        Belt and braces: if someone edits a prompt and forgets to bump
        `version`, the cache still invalidates. The version number is for
        humans reading a backtest log; this is for correctness.
        """
        payload = f"{self.id}|{self.version}|{self.system}|{self.user}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def placeholders(self) -> set[str]:
        """Every `{name}` the templates expect."""
        names: set[str] = set()
        for template in (self.system, self.user):
            for _, field, _, _ in Formatter().parse(template):
                if field:
                    names.add(field)
        return names

    def render(self, variables: dict[str, Any]) -> tuple[str, str]:
        """Fill the templates. Missing variables raise rather than render
        `{ticker}` into the prompt, which produces a confident answer about a
        company that does not exist."""
        missing = self.placeholders() - set(variables)
        if missing:
            raise PromptError(
                f"prompt {self.id} v{self.version}: missing variables "
                f"{sorted(missing)} — refusing to render a template hole"
            )
        return self.system.format(**variables), self.user.format(**variables)


def _parse(path: Path) -> Prompt:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PromptError(f"{path}: not a YAML mapping")

    for key in ("id", "version", "model_tier", "system", "user"):
        if key not in raw:
            raise PromptError(f"{path}: missing required key '{key}'")

    if raw["model_tier"] not in TIERS:
        raise PromptError(
            f"{path}: model_tier '{raw['model_tier']}' not in {sorted(TIERS)}"
        )
    if raw["id"] != path.stem:
        raise PromptError(f"{path}: id '{raw['id']}' does not match filename")

    return Prompt(
        id=raw["id"],
        version=int(raw["version"]),
        model_tier=raw["model_tier"],
        system=raw["system"],
        user=raw["user"],
        description=raw.get("description", ""),
    )


@cache
def load(prompt_id: str) -> Prompt:
    path = PROMPT_DIR / f"{prompt_id}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in PROMPT_DIR.glob("*.yaml"))
        raise PromptError(f"no prompt '{prompt_id}'. Available: {available}")
    return _parse(path)


def load_all() -> dict[str, Prompt]:
    """Used by the test that asserts every prompt parses and every version is
    an integer. A prompt that only breaks when its lens runs is a prompt that
    breaks at 14:00 on the day."""
    return {p.stem: load(p.stem) for p in sorted(PROMPT_DIR.glob("*.yaml"))}
