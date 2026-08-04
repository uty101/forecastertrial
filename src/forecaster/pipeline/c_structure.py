"""Layer B — the evidence store.

Acquisition produces a pile of Claims. This turns that pile into the single
block of text every lens reads, and it is the only thing in the pipeline that
touches all seven lenses at once.

Two properties it has to have:

**Identical bytes across lenses.** The corpus is the cached prefix. Seven lenses
fan out against it, so it is written to the cache once and read six times at a
tenth of the price. Any per-lens variation — a lens name in a header, a
timestamp, an unsorted dict — silently breaks that and you pay full price seven
times without any error to tell you.

**Claim ids the model can actually cite.** A lens must return `claim_ids` that
resolve, because the reconciler checks them and drops the lens if they don't.
So the corpus assigns short, stable, human-typeable ids (`c1`, `c2`, ...) rather
than exposing the internal `sec:NVDA:2026Q1:Revenue` form, which models truncate,
reformat, and get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from forecaster.schemas import Claim, Consensus, Guidance, LandingDistribution

log = structlog.get_logger()

# A corpus larger than this is mostly noise for a one-quarter forecast, and it
# is charged on every lens. Acquisition ranks claims; this truncates the tail
# and says what it dropped.
MAX_CORPUS_CHARS = 120_000


@dataclass
class EvidenceStore:
    """Claims plus the documents needed to verify their quotes.

    `documents` is what makes citation verification possible: `verify_citations`
    string-matches every quote against the source text. A claim whose document
    is absent counts as unverified, never as passed.
    """

    claims: dict[str, Claim] = field(default_factory=dict)
    documents: dict[str, str] = field(default_factory=dict)
    consensus: Consensus | None = None
    guidance: list[Guidance] = field(default_factory=list)
    landing: LandingDistribution | None = None
    dropped: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- #

    @property
    def n_claims(self) -> int:
        return len(self.claims)

    def get(self, claim_id: str) -> Claim | None:
        return self.claims.get(claim_id)

    def resolve(self, claim_ids: list[str]) -> tuple[list[Claim], list[str]]:
        """Split cited ids into (found, unknown).

        An unknown id is a fabricated citation — the model referring to evidence
        that does not exist — and it must reach the reconciler as a failure
        rather than being quietly skipped.
        """
        found, unknown = [], []
        for cid in claim_ids:
            claim = self.claims.get(cid)
            (found.append(claim) if claim else unknown.append(cid))
        return found, unknown

    # ---------------------------------------------------------------- #

    def corpus(self) -> str:
        """The shared, cached evidence block. Byte-identical for every lens.

        Sorted by id so the ordering is deterministic — an unsorted dict
        iteration would produce a different prefix on some runs and quietly
        halve the cache hit rate.
        """
        lines = [
            "EVIDENCE",
            "",
            "Every figure below carries an id. Cite the ids you rely on. Do not",
            "cite an id that is not in this list, and do not state a figure that",
            "is not derived from one.",
            "",
        ]

        for cid in sorted(self.claims, key=_natural):
            claim = self.claims[cid]
            value = _fmt(claim.value, claim.unit)
            period = f" [{claim.period}]" if claim.period else ""
            source = claim.source
            lines.append(f"{cid}. {claim.label}{period}: {value}")
            lines.append(f"    source: {source.kind.value}, filed {source.as_of}")
            lines.append(f'    "{_clip(claim.verbatim_quote, 400)}"')

        text = "\n".join(lines)
        if len(text) > MAX_CORPUS_CHARS:
            text = text[:MAX_CORPUS_CHARS]
            note = (
                f"\n\n[TRUNCATED at {MAX_CORPUS_CHARS} characters — "
                f"{len(self.claims)} claims did not all fit. Lower-ranked "
                "evidence was dropped; this is a budget limit, not an absence "
                "of evidence.]"
            )
            log.warning("corpus_truncated", n_claims=len(self.claims),
                        chars=len(text))
            text += note
        return text

    def cited_block(self, claim_ids: list[str]) -> str:
        """Just the claims one lens cited. Used by the champion, which argues
        about a single case and does not need the whole corpus in context."""
        found, unknown = self.resolve(claim_ids)
        lines = []
        for claim in found:
            lines.append(
                f"{claim.id}. {claim.label}: {_fmt(claim.value, claim.unit)}\n"
                f'    "{_clip(claim.verbatim_quote, 400)}"'
            )
        for cid in unknown:
            lines.append(f"{cid}. [NOT IN THE EVIDENCE STORE — fabricated citation]")
        return "\n".join(lines) or "(this lens cited nothing)"


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #


def build(
    claims: list[Claim],
    documents: dict[str, str] | None = None,
    consensus: Consensus | None = None,
    guidance: list[Guidance] | None = None,
    landing: LandingDistribution | None = None,
) -> EvidenceStore:
    """Assemble the store, renumbering claims to short citable ids.

    Renumbering is the point. Internally a claim is
    `sec:NVDA:2026Q1:Diluted EPS (GAAP)`; a model asked to cite that will
    truncate it, change the case, or drop the colon, and the reconciler will
    correctly but uselessly drop the lens for a fabricated citation. `c7` is
    hard to get wrong.
    """
    store = EvidenceStore(
        documents=dict(documents or {}),
        consensus=consensus,
        guidance=list(guidance or []),
        landing=landing,
    )

    # Deduplicate on (label, period, value) — acquisition hits the same fact
    # from several sources and seven copies of the share count is seven times
    # the cost for no extra information.
    seen: dict[tuple, str] = {}
    remap: dict[str, str] = {}
    ordinal = 0
    for claim in claims:
        signature = (claim.label, claim.period, claim.value)
        if signature in seen:
            store.dropped.append(f"{claim.id} (duplicate of an earlier claim)")
            # Point the dropped id at the survivor rather than nowhere: a
            # Guidance whose claim was deduplicated still has a real quote
            # behind it, just under a different short id.
            remap[claim.id] = seen[signature]
            continue
        ordinal += 1
        short = f"c{ordinal}"
        seen[signature] = short
        remap[claim.id] = short
        store.claims[short] = claim.model_copy(update={"id": short})

    # Guidance carries the id of the claim holding its quote, and renumbering
    # would leave every one of them dangling — the guide would survive with a
    # citation pointing at a claim that no longer exists under that name, which
    # the reconciler reads as a fabricated citation and drops the lens for.
    store.guidance = [
        guide.model_copy(update={"claim_id": remap[guide.claim_id]})
        if guide.claim_id in remap
        else guide
        for guide in store.guidance
    ]

    log.info(
        "evidence_store_built",
        claims=len(store.claims),
        deduped=len(store.dropped),
        documents=len(store.documents),
        corpus_chars=len(store.corpus()),
    )
    return store


# --------------------------------------------------------------------------- #
# block builders — the small per-lens strings that go in the user turn
# --------------------------------------------------------------------------- #
#
# These stay OUT of the corpus deliberately. Anything that differs per lens must
# live after the cache breakpoint or the shared prefix stops matching.


def guidance_block(guides: list[Guidance]) -> str:
    if not guides:
        return "(no guidance issued for this quarter — this company may not guide)"
    lines = []
    for g in guides:
        if g.low is not None and g.high is not None:
            span = f"{g.low:.4g} to {g.high:.4g} (midpoint {g.midpoint:.4g})"
        elif g.point is not None:
            span = f"{g.point:.4g} (point)"
        else:
            span = "range not stated"
        cc = ", constant currency" if g.constant_currency else ""
        lines.append(
            f"- {g.metric} for {g.period}: {span} [{g.basis.value}{cc}] "
            f"(claim {g.claim_id})"
        )
    return "\n".join(lines)


def landing_block(landing: LandingDistribution | None) -> str:
    if landing is None:
        return "(no guided-range history available for this company)"
    positions = ", ".join(f"{p:.2f}" for p in landing.positions)
    return (
        f"- positions, oldest first: {positions}\n"
        f"- raw median: {landing.median_position:.2f} over "
        f"{landing.n_quarters} quarters\n"
        f"- shrunk toward the sector: {landing.shrunk_position:.2f}  "
        f"<- weight this one; with n~8 the raw median is mostly sampling noise"
    )


def consensus_block(consensus: Consensus | None) -> str:
    if consensus is None:
        return "(no consensus available)"
    parts = [f"- EPS {consensus.eps:.4g} ({consensus.basis.value})"]
    if consensus.revenue:
        parts.append(f"- revenue {consensus.revenue:,.0f}")
    if consensus.n_analysts is not None:
        parts.append(f"- {consensus.n_analysts} analysts contributing")
    if consensus.dispersion is not None:
        parts.append(f"- high-low dispersion {consensus.dispersion:.1%} of the mean")
    if consensus.days_since_last_revision is not None:
        parts.append(
            f"- last revised roughly {consensus.days_since_last_revision} days ago"
        )
    return "\n".join(parts)


def dropped_block(dropped: dict[str, str]) -> str:
    if not dropped:
        return "(none — every lens reached you)"
    return "\n".join(f"- {lens}: {why}" for lens, why in sorted(dropped.items()))


# --------------------------------------------------------------------------- #


def _natural(cid: str) -> tuple[int, str]:
    """Sort c2 before c10. Lexical sort puts c10 first, which looks like a bug
    to anyone reading the corpus and makes diffs between runs noisy."""
    if cid.startswith("c") and cid[1:].isdigit():
        return (int(cid[1:]), "")
    return (10**9, cid)


def _fmt(value: float | str | None, unit: str | None) -> str:
    if value is None:
        return "(no value — qualitative)"
    if isinstance(value, str):
        return value
    if abs(value) < 1000:
        rendered = f"{value:,.4f}".rstrip("0").rstrip(".")
    else:
        rendered = f"{value:,.0f}"
    return f"{rendered} {unit}" if unit else rendered


def _clip(text: str, limit: int) -> str:
    """Quotes are clipped for the corpus only. Verification always runs against
    the full stored quote, so clipping here cannot cause a false failure."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
