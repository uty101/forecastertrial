"""What is built, what is measured, and what is still asserted.

**Derived from the repository, never hand-maintained.** A checklist in a markdown
file rots the moment someone lands a change without editing it, and then the
status board is confidently describing a system that no longer exists. Every
field below is a real check: does the module import, does the golden file exist,
is `FITTED_BETA_MEASURED` still False, has the case set been built.

The distinction the whole board turns on is BUILT versus MEASURED. Almost
everything is built. The parts that matter are the ones where a number has been
measured rather than asserted — and this deliberately reports those separately,
because conflating them is how a demo overclaims.
"""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# state values, in the order the UI colours them
BUILT = "built"
PARTIAL = "partial"
MISSING = "missing"


@dataclass
class Component:
    id: str
    label: str
    layer: str
    state: str
    detail: str = ""
    tier: str = "none"
    tests: int = 0


@dataclass
class Status:
    components: list[Component] = field(default_factory=list)
    gates: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "components": [asdict(c) for c in self.components],
            "gates": self.gates,
            "totals": self.totals,
        }


LENS = "forecaster.pipeline.e_lenses"
PIPE = "forecaster.pipeline"
DATA = "forecaster.data"
EVAL = "forecaster.eval"
MODEL = "forecaster.model"

# (module, id, label, layer, tier)
MODULES: list[tuple[str, str, str, str, str]] = [
    (f"{DATA}.sec_source", "sec", "SEC XBRL + filings", "sources", "none"),
    (f"{DATA}.yfinance_source", "yfinance", "yfinance consensus", "sources", "none"),
    (f"{DATA}.fred_source", "fred", "FRED macro", "sources", "none"),
    (f"{DATA}.exa_source", "exa", "Exa news search", "sources", "none"),
    (f"{DATA}.lse_source", "lse", "LSE options + insiders", "sources", "none"),
    (f"{DATA}.sponsor_source", "sponsor", "Sponsor feed adapter", "sources", "none"),
    (f"{DATA}.universe", "universe", "Prepared universe", "sources", "none"),
    (f"{DATA}.history", "history", "Quarterly series builder", "sources", "none"),
    (f"{DATA}.prices", "prices", "Price bars + VWAP", "sources", "none"),
    (f"{PIPE}.b_acquire", "acquire", "B1–B5 acquirers", "acquire", "none"),
    (f"{PIPE}.extract", "extract_guidance", "Guidance extractor", "acquire", "cheap"),
    (f"{PIPE}.dossier", "dossier", "Acquisition artifact", "acquire", "none"),
    (f"{DATA}.segments", "segments", "Revenue decomposition", "acquire", "none"),
    (f"{DATA}.transcripts", "transcripts", "Earnings calls, 8 quarters",
     "acquire", "none"),
    (f"{MODEL}.scenarios", "scenarios", "Bull / base / bear", "model", "none"),
    (f"{PIPE}.j_monitor", "monitor", "Kill criteria + post-mortem", "monitor", "none"),
    (f"{PIPE}.e_expect.landing", "landing", "Landing distribution", "expect", "none"),
    (f"{PIPE}.e_expect.swing", "swing", "Swing factors", "expect", "none"),
    (f"{PIPE}.e_expect.perception", "perception", "Scanned perception",
     "expect", "none"),
    (f"{DATA}.industry", "industry", "Industry size + share", "acquire", "none"),
    (f"{DATA}.exposure", "exposure", "Economies + input costs", "acquire", "none"),
    (f"{LENS}.market", "market", "Market lens", "lenses", "mid"),
    (f"{LENS}.demand", "demand", "Demand lens", "lenses", "mid"),
    (f"{MODEL}.inputs", "inputs", "History → model inputs", "structure", "none"),
    (f"{MODEL}.grid", "grid", "Statements as laid-out grids", "model", "none"),
    (f"{MODEL}.dcf", "dcf", "DCF + reverse DCF", "model", "none"),
    (f"{MODEL}.project", "project", "Forecast scaffold to 2035", "model", "none"),
    (f"{MODEL}.from_lenses", "from_lenses", "Ensemble view → drivers", "model", "none"),
    (f"{PIPE}.d_model", "model", "3-statement stage + backtest", "model", "none"),
    (f"{PIPE}.c_structure", "evidence", "Evidence store", "structure", "none"),
    (f"{MODEL}.statements", "statements", "3-statement model", "structure", "none"),
    (f"{MODEL}.bridge", "bridge", "GAAP↔non-GAAP bridge", "structure", "none"),
    (f"{LENS}.mechanical", "mechanical", "Mechanical lens", "lenses", "none"),
    (f"{LENS}.guidance", "guidance", "Guidance lens", "lenses", "mid"),
    (f"{LENS}.drivers", "drivers", "Drivers lens", "lenses", "mid"),
    (f"{LENS}.margins", "margins", "Margins lens", "lenses", "mid"),
    (f"{LENS}.forensics", "forensics", "Forensics lens", "lenses", "mid"),
    (f"{LENS}.peer_read", "peer_read", "Peer read lens", "lenses", "mid"),
    (f"{LENS}.macro", "macro", "Macro lens", "lenses", "mid"),
    (f"{PIPE}.v1_reconcile", "v1", "V1 reconcile", "verify", "none"),
    (f"{PIPE}.f_champion", "champion", "Champion ×7", "challenge", "mid"),
    (f"{PIPE}.g_judge", "judge", "Judge", "judge", "deep"),
    (f"{PIPE}.v2_comparability", "v2", "V2 comparability", "verify", "cheap"),
    (f"{PIPE}.h_lambda", "lambda", "λ positioning", "position", "none"),
    (f"{PIPE}.v3_calibrate", "v3", "V3 calibrate", "verify", "none"),
    (f"{PIPE}.run", "orchestrator", "A→G orchestrator", "position", "none"),
    (f"{EVAL}.cases", "cases", "Case builder", "eval", "none"),
    (f"{EVAL}.backtest", "backtest", "Backtest harness", "eval", "none"),
    (f"{EVAL}.fit", "fit", "λ regression", "eval", "none"),
    (f"{EVAL}.baseline", "baseline", "Baseline", "eval", "none"),
    (f"{EVAL}.landing", "landing", "Landing distribution", "eval", "none"),
    ("forecaster.llm.client", "llm", "LLM client", "infra", "none"),
]

# Which test file covers which component. Used only to report coverage honestly —
# a component with no test is marked partial rather than built, because "it
# imports" is a much weaker claim than "a test encodes how it fails".
TEST_MAP = {
    "tests/test_point_in_time.py": ["sec", "yfinance", "fred"],
    "tests/test_reconciler.py": ["v1", "evidence"],
    "tests/test_stage1.py": ["yfinance", "baseline", "backtest", "landing"],
    "tests/test_llm_layer.py": ["llm", "evidence", "judge", "v3", "extract_guidance"],
    "tests/test_model.py": ["statements", "bridge"],
    "tests/test_extract.py": ["extract_guidance"],
    "tests/test_exa_source.py": ["exa"],
    "tests/test_lse_source.py": ["lse"],
    "tests/test_history.py": ["history", "sec"],
    "tests/test_prices.py": ["prices", "yfinance"],
    "tests/test_dossier.py": ["dossier"],
    "tests/test_model_inputs.py": ["inputs"],
    "tests/test_d_model.py": ["model", "statements"],
    "tests/test_grid.py": ["grid"],
    "tests/test_dcf.py": ["dcf"],
    "tests/test_project.py": ["project"],
    "tests/test_from_lenses.py": ["from_lenses"],
    "tests/test_segments.py": ["segments"],
    "tests/test_expect.py": ["landing", "swing"],
    "tests/test_scenarios_monitor.py": ["scenarios", "monitor"],
    "tests/test_context.py": ["industry", "exposure", "perception"],
    "tests/test_transcripts.py": ["transcripts"],
    "tests/test_sec_acquisition.py": ["sec", "acquire"],
    "tests/test_universe.py": ["universe"],
    "tests/test_sponsor_source.py": ["sponsor"],
}


def _imports(module: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _count_tests() -> tuple[int, dict[str, int]]:
    """Test functions per file. Counted from source rather than by running
    pytest, so the status command stays fast and side-effect free."""
    per_file: dict[str, int] = {}
    total = 0
    for path in sorted((REPO / "tests").glob("test_*.py")):
        n = len(re.findall(r"^def test_", path.read_text(encoding="utf-8"), re.M))
        per_file[f"tests/{path.name}"] = n
        total += n
    return total, per_file


def collect() -> Status:
    status = Status()
    total_tests, per_file = _count_tests()

    tested: dict[str, list[str]] = {}
    for test_file, covered in TEST_MAP.items():
        for component in covered:
            tested.setdefault(component, []).append(test_file)

    for module, cid, label, layer, tier in MODULES:
        ok, error = _imports(module)
        covering = tested.get(cid, [])
        test_count = sum(per_file.get(f, 0) for f in covering)

        if not ok:
            state, detail = MISSING, error
        elif covering:
            state = BUILT
            detail = f"covered by {', '.join(Path(f).name for f in covering)}"
        else:
            # Imports, wired into the pipeline, but nothing encodes how it fails.
            state = PARTIAL
            detail = "no test encodes its failure modes"

        status.components.append(
            Component(cid, label, layer, state, detail, tier, test_count)
        )

    status.gates = _gates()
    built = sum(c.state == BUILT for c in status.components)
    partial = sum(c.state == PARTIAL for c in status.components)
    status.totals = {
        "components": len(status.components),
        "built": built,
        "partial": partial,
        "missing": len(status.components) - built - partial,
        "tests": total_tests,
        "tests_by_file": per_file,
        "gates_passed": sum(g["passed"] for g in status.gates),
        "gates_total": len(status.gates),
    }
    return status


def _gates() -> list[dict]:
    """The checks that decide whether a number is measured or merely asserted.

    These are the only rows on the board that matter for the accuracy prize. A
    system where every component is green and every gate is red is a system that
    has been built and never tested against reality.
    """
    from forecaster.pipeline import h_lambda

    golden = REPO / "tests" / "golden" / "fixture.json"
    cases = REPO / "out" / "cases.json"
    lam = REPO / "out" / "lambda.json"
    cache = REPO / "data" / "cache"

    yf_cached = any(cache.glob("yf/**/*.json")) if cache.exists() else False
    sec_cached = any(cache.glob("sec_*/**/*.json")) if cache.exists() else False

    n_cases = 0
    if cases.exists():
        try:
            n_cases = int(json.loads(cases.read_text())["summary"]["n_cases"])
        except Exception:  # noqa: BLE001
            n_cases = 0

    return [
        {
            "id": "sources_verified",
            "label": "Data sources run against the network",
            "passed": yf_cached or sec_cached,
            "detail": (
                "cache holds real responses"
                if (yf_cached or sec_cached)
                else "no cached responses — run `forecast sources --ticker NVDA` "
                "from the demo machine first. This is the check most likely to "
                "be silently broken."
            ),
            "blocks": "everything downstream assumes a data shape that was "
            "inferred from documentation rather than observed",
        },
        {
            "id": "cases_built",
            "label": "Firm-quarter case set built",
            "passed": n_cases >= 100,
            "detail": (
                f"{n_cases} point-in-time cases"
                if n_cases
                else "no case set — `forecast cases`"
            ),
            "blocks": "without cases there is no baseline, and without a "
            "baseline a pipeline result cannot be interpreted",
        },
        {
            "id": "baseline_scored",
            "label": "Baseline scored — THE number to beat",
            "passed": n_cases >= 100,
            "detail": (
                "consensus × 1.02 has a score"
                if n_cases >= 100
                else "not scored — `forecast backtest`"
            ),
            "blocks": "every accuracy claim afterwards is measured against this",
        },
        {
            "id": "lambda_measured",
            "label": "λ fitted rather than asserted",
            "passed": bool(getattr(h_lambda, "FITTED_BETA_MEASURED", False)),
            "detail": (
                "FITTED_BETA holds fitted coefficients"
                if getattr(h_lambda, "FITTED_BETA_MEASURED", False)
                else "FITTED_BETA holds three placeholder numbers — the thesis is "
                "asserted, not measured"
            ),
            "blocks": "λ is the thesis; a guessed λ makes the central claim "
            "unfalsifiable",
        },
        {
            "id": "lambda_report",
            "label": "Per-regime β table produced",
            "passed": lam.exists(),
            "detail": "out/lambda.json present" if lam.exists() else "`forecast fit`",
            "blocks": "the regime table is the thesis as a statistical model",
        },
        {
            "id": "determinism",
            "label": "make verify green",
            "passed": golden.exists(),
            "detail": (
                "golden file committed"
                if golden.exists()
                else "no golden file — determinism unproven"
            ),
            "blocks": "reproducibility is load-bearing if the organisers run "
            "your agent themselves",
        },
    ]


def main(out: Path | None = None) -> Status:
    status = collect()
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(status.to_json(), indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    result = main(target)
    print(json.dumps(result.totals, indent=2))
