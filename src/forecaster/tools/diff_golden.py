"""Golden-file diff for `make verify`.

Exits non-zero on any difference. Wired into CI, so determinism is checked on
every commit rather than asserted in a README.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Fields that legitimately vary run to run and are excluded from the comparison.
VOLATILE = {"wall_clock_ms", "latency_ms", "fetched", "total_cost_usd"}


def strip(obj):
    if isinstance(obj, dict):
        return {k: strip(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [strip(v) for v in obj]
    return obj


def main() -> int:
    actual, golden = Path(sys.argv[1]), Path(sys.argv[2])
    if not golden.exists():
        print(f"golden file {golden} missing — create it with:\n  cp {actual} {golden}")
        return 1
    a, b = strip(json.loads(actual.read_text())), strip(json.loads(golden.read_text()))
    if a == b:
        print(f"verify OK — {actual.name} matches {golden.name}")
        return 0
    print(f"DETERMINISM FAILURE: {actual} != {golden}")
    for key in sorted(set(a) | set(b)):
        if a.get(key) != b.get(key):
            print(f"  {key}:\n    actual {a.get(key)!r}\n    golden {b.get(key)!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
