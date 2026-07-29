# Pinned base, non-root, deps from the lockfile only.
# OpenStocks' verified tier means they run your agent in THEIR environment —
# this is the artifact that has to work on a machine you have never seen.
#
# The digest is pinned rather than the tag. `python:3.12-slim` is a moving
# target: it is rebuilt weekly, so a tag-only build is reproducible right up
# until the day someone else runs it and gets a different base. Re-pin
# deliberately with:
#
#   docker buildx imagetools inspect python:3.12-slim
#
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN useradd -m -u 1000 app
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

# Dependencies before source, so a code change does not re-resolve the
# environment. `--frozen` fails rather than silently updating the lockfile —
# an image that quietly resolved different versions is not the image you tested.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
COPY tests/golden/ tests/golden/
RUN uv sync --frozen --no-dev

USER app

# Deterministic by default: no network, cache only. A container that silently
# hits the network is a container whose output cannot be reproduced.
ENV FORECASTER_CACHE_DIR=/app/data/cache \
    FORECASTER_OUT_DIR=/app/out

ENTRYPOINT ["uv", "run", "forecast"]
CMD ["--help"]
