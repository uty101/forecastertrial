.PHONY: setup types run backtest verify ui test lint clean

setup:                       ## install python + node deps
	uv sync
	cd ui && npm install

types:                       ## pydantic schemas -> ui/lib/types.ts
	uv run python -m forecaster.tools.export_types > ui/lib/types.ts

run:                         ## one forecast: make run TICKER=NVDA ASOF=2026-08-16
	uv run forecast run --ticker $(TICKER) --as-of $(ASOF)

backtest:                    ## N historical quarters, k runs each
	uv run forecast backtest --quarters 200 --runs 5

verify:                      ## THE ONE THAT MATTERS
	uv run forecast run --ticker NVDA --as-of 2026-05-01 \
	  --from-cache --seed 0 --out out/verify.json
	uv run python -m forecaster.tools.diff_golden \
	  out/verify.json tests/golden/nvda_2026q1.json

ui:
	cd ui && npm run build && cd out && python3 -m http.server 3000

test:
	uv run pytest -q
	uv run ruff check .

lint:
	uv run ruff check --fix . && uv run ruff format .

clean:
	rm -rf out/*.json out/*.ndjson .pytest_cache
