# Pinned base, non-root, deps from the lockfile only.
# OpenStocks' verified tier means they run your agent in THEIR environment —
# this is the artifact that has to work on a machine you have never seen.
FROM python:3.11-slim@sha256:PINME AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd -m -u 1000 app
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ src/
COPY tests/golden/ tests/golden/
USER app
ENTRYPOINT ["uv", "run", "forecast"]
CMD ["run", "--help"]
