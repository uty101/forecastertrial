"""Acquisition's output as an artifact on disk.

Stage 2 gathers everything the analysis needs; this is the handover. The tests
are about what has to survive the round trip, and one thing that must not vary
between two runs of identical data.
"""

from __future__ import annotations

from datetime import date

from forecaster.data.history import History, Observation
from forecaster.data.prices import PriceBar
from forecaster.pipeline import dossier
from forecaster.pipeline.a_acquire import Acquired
from forecaster.pipeline.v1_reconcile import verify_citations
from forecaster.schemas import Basis, Claim, Consensus, Guidance, Source, SourceKind

AS_OF = date(2026, 8, 4)
ARTICLE = "Omdia raises its forecast. AI demand drove a 94.1% surge in the quarter."
URI = "https://example.test/omdia-raises-forecast"


def _acquired() -> Acquired:
    claim = Claim(
        id="exa:NVDA:abc123",
        label="Omdia raises its forecast",
        value=None,
        source=Source(kind=SourceKind.NEWS, uri=URI, as_of=date(2026, 7, 30)),
        verbatim_quote="Omdia raises its forecast.",
    )
    observation = Observation(
        key="revenue", fy=2027, fp="Q1", value=81_615e6, unit="USD",
        period_end=date(2026, 4, 26), filed=date(2026, 5, 20),
        form="10-Q", accession="0001045810-26-000052",
    )
    return Acquired(
        claims=[claim],
        documents={URI: ARTICLE},
        consensus=Consensus(eps=2.083, basis=Basis.NON_GAAP, as_of=AS_OF),
        budgets={"A2": {"docs": 12, "tokens": 33612, "elapsed_s": 1.5,
                        "skipped": ["10-K: geographic mix"]}},
        sector="semiconductors",
        prepared=True,
        peer_block="AMD (already reported)",
        history=History("NVDA", AS_OF, {"revenue": [observation]}, cik="0001045810"),
        prices=[PriceBar(date(2026, 7, 24), 207.45, 211.91, 204.81, 206.84, 1.1e8)],
    )


def test_everything_survives_the_round_trip(tmp_path):
    path = dossier.write(_acquired(), "NVDA", "2027Q2", AS_OF, root=tmp_path)
    back, guides, manifest = dossier.read(path)

    assert len(back.claims) == 1
    assert back.documents[URI] == ARTICLE
    assert back.consensus.eps == 2.083
    assert back.sector == "semiconductors"
    assert back.peer_block == "AMD (already reported)"
    assert back.history.n_quarters() == 1
    assert back.history.get("revenue", "2027Q1").value == 81_615e6
    assert back.history.cik == "0001045810"
    assert back.prices[0].close == 206.84
    assert manifest["counts"]["claims"] == 1


def test_citations_still_verify_after_a_round_trip(tmp_path):
    """The reason documents are stored verbatim.

    `verify_citations` string-matches every prose quote against its source, so
    anything that reformats, truncates or re-encodes a document on the way to
    disk silently breaks every citation resting on it — and a lens whose
    citations fail is dropped, not warned about.
    """
    path = dossier.write(_acquired(), "NVDA", "2027Q2", AS_OF, root=tmp_path)
    back, _, _ = dossier.read(path)

    verified, failed = verify_citations(back.claims, back.documents)
    assert verified and not failed


def test_two_writes_of_the_same_data_are_byte_identical(tmp_path):
    """`make verify` compares output byte for byte, so the dossier cannot carry
    wall-clock time. The budget reports include `elapsed_s`, which differs on
    every run — persisting it would make identical data compare unequal."""
    first = dossier.write(_acquired(), "NVDA", "2027Q2", AS_OF, root=tmp_path / "a")
    second = dossier.write(_acquired(), "NVDA", "2027Q2", AS_OF, root=tmp_path / "b")

    for name in ("manifest.json", "claims.json", "history.json", "prices.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_the_manifest_records_what_was_skipped(tmp_path):
    """A budget that ran out has to be visible in the artifact, not only in a log
    line that scrolled past. Silent truncation reads as "we covered everything"."""
    path = dossier.write(_acquired(), "NVDA", "2027Q2", AS_OF, root=tmp_path)
    _, _, manifest = dossier.read(path)

    assert manifest["budgets"]["A2"]["skipped"] == ["10-K: geographic mix"]
    assert "elapsed_s" not in manifest["budgets"]["A2"]


def test_guidance_and_rejections_are_both_kept(tmp_path):
    """Rejections are not an error list to swallow — a high rate means the
    extractor is paraphrasing, which is worth knowing before the forecast
    rests on it."""
    guide = Guidance(metric="revenue", period="Q2 FY2027", low=89.18e9,
                     high=92.82e9, basis=Basis.NON_GAAP, claim_id="c57")
    path = dossier.write(
        _acquired(), "NVDA", "2027Q2", AS_OF,
        guides=[guide], rejections=["eps: no low, high or point"], root=tmp_path,
    )
    _, guides, _ = dossier.read(path)

    assert guides[0].midpoint == 91e9
    assert dossier._load(path / "guidance.json")["rejected"] == [
        "eps: no low, high or point"
    ]
