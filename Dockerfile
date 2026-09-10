# Hydro-Agent workbench: Archify UI + FastAPI (real SiliconFlow + XAJ)
FROM node:22-bookworm AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HYDRO_AGENT_HOST=0.0.0.0 \
    HYDRO_AGENT_PORT=8000 \
    HYDRO_AGENT_DB=/data/hydro.db \
    HYDRO_AGENT_REPORTS=/data/reports \
    HYDRO_AGENT_STATIC=/app/web/dist \
    HYDRO_AGENT_MODE=real

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts ./scripts
COPY data/academy ./data/academy
COPY tests/fixtures/lowman_reanalysis_source ./tests/fixtures/lowman_reanalysis_source
COPY tests/fixtures/xaj/lowman_scheme.json ./tests/fixtures/xaj/lowman_scheme.json

# Prefer a reachable index when building behind unstable PyPI routes.
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN uv sync --frozen --extra api --extra data --extra xaj --extra xaj-dem --no-dev \
    && mkdir -p /data/reports /data/runtime

COPY --from=web /web/dist /app/web/dist

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${HYDRO_AGENT_PORT}/api/health" || exit 1

CMD ["uv", "run", "python", "scripts/run_workbench_api.py"]
