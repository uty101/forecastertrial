"""A tiny dependency-graph evaluator — the substrate under the 3-statement model.

Deliberately not a spreadsheet engine and deliberately not an LLM. Cells are
either an input (a value that traces to a Claim) or a formula over other cells.
Evaluation is a topological sort. About 150 lines, fully testable, and it cannot
produce a number it can't explain.

Why this rather than a dict of floats: every cell carries provenance, so the UI
can render the model with a clickable source on each figure, and `make verify`
can assert the whole thing byte-for-byte.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from forecaster.schemas import Claim


class CycleError(RuntimeError):
    pass


class MissingInput(RuntimeError):
    pass


@dataclass
class Cell:
    """One line item. Either `value` (an input) or `fn` + `deps` (a formula)."""

    key: str
    label: str
    unit: str
    value: float | None = None
    fn: Callable[[dict[str, float]], float] | None = None
    deps: tuple[str, ...] = ()
    claim: Claim | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.value is None and self.fn is None:
            raise ValueError(f"cell {self.key}: needs either a value or a formula")
        if self.value is not None and self.fn is not None:
            raise ValueError(f"cell {self.key}: cannot be both an input and a formula")
        # An input with no claim is exactly the "invented number" failure mode.
        if self.value is not None and self.claim is None and self.note is None:
            raise ValueError(
                f"cell {self.key}: input cells need a Claim (or an explicit note "
                f"saying why not). No number enters the model without a source."
            )

    @property
    def is_input(self) -> bool:
        return self.fn is None


@dataclass
class Model:
    """A set of cells plus the machinery to evaluate them in the right order."""

    name: str
    cells: dict[str, Cell] = field(default_factory=dict)
    _cache: dict[str, float] = field(default_factory=dict, repr=False)

    def add(self, cell: Cell) -> Model:
        if cell.key in self.cells:
            raise ValueError(f"duplicate cell {cell.key}")
        self.cells[cell.key] = cell
        self._cache.clear()
        return self

    def input(
        self,
        key: str,
        label: str,
        unit: str,
        value: float,
        claim: Claim | None = None,
        note: str | None = None,
    ) -> Model:
        return self.add(
            Cell(key=key, label=label, unit=unit, value=value, claim=claim, note=note)
        )

    def formula(
        self,
        key: str,
        label: str,
        unit: str,
        deps: tuple[str, ...],
        fn: Callable[[dict[str, float]], float],
        note: str | None = None,
    ) -> Model:
        return self.add(
            Cell(key=key, label=label, unit=unit, fn=fn, deps=deps, note=note)
        )

    # ----------------------------------------------------------------- #

    def _order(self) -> list[str]:
        """Topological sort. Raises on cycles rather than iterating to a
        fixed point — a circular reference in a 3-statement model is a bug,
        not a feature to be solved numerically."""
        state: dict[str, int] = {}  # 0 unvisited, 1 in progress, 2 done
        order: list[str] = []

        def visit(key: str, path: tuple[str, ...]) -> None:
            if key not in self.cells:
                raise MissingInput(
                    f"cell '{key}' referenced by {' -> '.join(path) or 'root'} "
                    "does not exist"
                )
            s = state.get(key, 0)
            if s == 2:
                return
            if s == 1:
                cyc = " -> ".join([*path, key])
                raise CycleError(f"circular reference: {cyc}")
            state[key] = 1
            for dep in self.cells[key].deps:
                visit(dep, (*path, key))
            state[key] = 2
            order.append(key)

        for key in self.cells:
            visit(key, ())
        return order

    def evaluate(self) -> dict[str, float]:
        if self._cache:
            return dict(self._cache)
        values: dict[str, float] = {}
        for key in self._order():
            cell = self.cells[key]
            if cell.is_input:
                assert cell.value is not None
                values[key] = cell.value
            else:
                assert cell.fn is not None
                values[key] = cell.fn({d: values[d] for d in cell.deps})
        self._cache = values
        return dict(values)

    def get(self, key: str) -> float:
        return self.evaluate()[key]

    def provenance(self, key: str) -> list[Claim]:
        """Every sourced claim this cell ultimately depends on.

        Drives the hover-to-see-source behaviour in the UI, and is how you prove
        a forecast figure traces all the way back to a filing.
        """
        seen: set[str] = set()
        out: list[Claim] = []

        def walk(k: str) -> None:
            if k in seen:
                return
            seen.add(k)
            cell = self.cells[k]
            if cell.claim is not None:
                out.append(cell.claim)
            for dep in cell.deps:
                walk(dep)

        walk(key)
        return out

    def unsourced_inputs(self) -> list[str]:
        """Input cells with no Claim. Should be empty in any run you'd submit."""
        return [k for k, c in self.cells.items() if c.is_input and c.claim is None]

    def to_rows(self) -> list[dict]:
        """Flat rows for the UI and for xlsx export."""
        values = self.evaluate()
        return [
            {
                "key": k,
                "label": c.label,
                "unit": c.unit,
                "value": values[k],
                "is_input": c.is_input,
                "sourced": c.claim is not None,
                "source_uri": c.claim.source.uri if c.claim else None,
                "quote": c.claim.verbatim_quote if c.claim else None,
                "note": c.note,
            }
            for k, c in self.cells.items()
        ]
