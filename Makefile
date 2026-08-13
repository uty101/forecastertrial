.PHONY: setup types run backtest cases fit verify fixture ui ui-build serve test lint agents

setup:                       ## install python + node deps
	uv sync
	cd ui && npm install

types:                       ## pydantic schemas -> ui/lib/types.ts
	uv run python -m forecaster.tools.export_types > ui/lib/types.ts

agents:                      ## the roster, printed from the prompt files
	uv run forecast agents

run:                         ## one forecast: make run TICKER=NVDA ASOF=2026-08-16
	uv run forecast run --ticker $(TICKER) --as-of $(ASOF)

cases:                       ## Block 1: build the firm-quarter case set
	uv run forecast cases

backtest:                    ## THE GATE: score consensus x 1.02 on those cases
	uv run forecast backtest

fit:                         ## fit beta and replace the FITTED_BETA placeholders
	uv run forecast fit

fixture:                     ## a labelled synthetic run, for UI dev and make verify
	uv run python -m forecaster.tools.make_fixture --out out
	uv run forecast agents --json out/agents.json
	uv run forecast status --json out/build.json

verify:                      ## THE ONE THAT MATTERS
	uv run python -m forecaster.tools.make_fixture --out out
	uv run python -m forecaster.tools.diff_golden \
	  out/results.json tests/golden/fixture.json

# The UI polls /events.ndjson and /results.json from the directory it is served
# out of. Next copies public/ into out/ at build time, so the pipeline's output
# has to be staged into public/ BEFORE the build — otherwise the app builds
# fine, serves fine, and shows an empty state forever, which is a confusing
# thing to debug at 17:00.
ui-build:
	mkdir -p ui/public/replays
	cp -f out/results.json out/events.ndjson ui/public/ 2>/dev/null || true
	cp -f out/eval.json out/agents.json out/portfolio.json out/build.json out/model.json ui/public/ 2>/dev/null || true
	cd ui && npm run build

# NOTE: make is NOT a dependency of this project — it is not installed on every
# machine, including the demo one. Every target here has a `uv run` equivalent in
# the README, and `forecast ui` supersedes this one entirely: it stages, guards
# the port and serves in a single command.
serve:                       ## build, stage and serve — port-guarded
	uv run forecast ui --port 4321

# For a LIVE run whose events stream into an already-served page, point the
# pipeline at the served directory instead of copying after the fact:
#
#     FORECASTER_OUT_DIR=ui/out make run TICKER=NVDA ASOF=2026-08-16
#
ui: serve

test:
	uv run pytest -q
	uv run ruff check .
	node ui/scripts/check-layout.mjs

lint:
	uv run ruff check --fix . && uv run ruff format .
