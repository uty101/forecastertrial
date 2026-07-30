"""Config loading — specifically, that credentials are read under the names the
template documents.

This exists because of a bug that survived until the first time real credentials
were used. `Settings` sets `env_prefix="FORECASTER_"`, which applies to every
field, so `anthropic_api_key` wanted `FORECASTER_ANTHROPIC_API_KEY` while
`.env.example` documented `ANTHROPIC_API_KEY`. Following the template produced a
Settings object with three empty strings and no error at all: SEC disabled, no
LLM, no FRED.

The symptom is the dangerous part. It does not look like a config problem — it
looks like "the data sources don't work", so you go and debug the network. The
gap between cause and symptom is why this is pinned rather than left to be
noticed again.
"""

from __future__ import annotations

import pytest

from forecaster.config import Settings

CREDENTIALS = [
    ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    ("SEC_IDENTITY", "sec_identity"),
    ("FRED_API_KEY", "fred_api_key"),
]


@pytest.mark.parametrize(("env_name", "field"), CREDENTIALS)
def test_credentials_read_the_unprefixed_name(env_name, field, monkeypatch):
    """The name in .env.example is the name that has to work.

    Unprefixed is also correct rather than merely convenient: ANTHROPIC_API_KEY
    is what the Anthropic SDK itself reads, so a key already exported for another
    tool works here without being copied under a second name.
    """
    monkeypatch.setenv(env_name, "sentinel-value")
    # No .env, so the test cannot pass by accident off the developer's own file.
    assert getattr(Settings(_env_file=None), field) == "sentinel-value"


@pytest.mark.parametrize(("env_name", "field"), CREDENTIALS)
def test_credentials_ignore_the_prefixed_name(env_name, field, monkeypatch):
    """And the prefixed name must NOT work, or the bug comes back silently.

    If both spellings resolved, someone would set FORECASTER_ANTHROPIC_API_KEY,
    it would work on their machine, and the next person following .env.example
    would be back to three empty strings.
    """
    monkeypatch.setenv(f"FORECASTER_{env_name}", "sentinel-value")
    assert getattr(Settings(_env_file=None), field) == ""


def test_tuning_knobs_keep_the_prefix(monkeypatch):
    """Everything that is NOT a credential stays namespaced.

    `COST_CEILING_USD` or `SEED` as bare environment names would collide with
    whatever else is in the shell; the prefix is doing real work there.
    """
    monkeypatch.setenv("FORECASTER_COST_CEILING_USD", "3.5")
    monkeypatch.setenv("FORECASTER_SEED", "42")
    loaded = Settings(_env_file=None)
    assert loaded.cost_ceiling_usd == 3.5
    assert loaded.seed == 42


def test_env_example_documents_exactly_what_is_read():
    """The template and the loader cannot disagree.

    A `.env.example` that lists a name nothing reads is worse than no template:
    it is a confident instruction to do the wrong thing.
    """
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    documented = {
        line.split("=", 1)[0].strip()
        for line in example.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    for env_name, _ in CREDENTIALS:
        assert env_name in documented, (
            f"{env_name} is read by Settings but not documented in .env.example"
        )
        assert f"FORECASTER_{env_name}" not in documented, (
            f"FORECASTER_{env_name} is documented but is NOT what Settings reads"
        )
