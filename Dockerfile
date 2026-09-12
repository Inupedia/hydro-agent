# Hydro-Agent workbench: Archify UI + FastAPI (real SiliconFlow + XAJ)
# Base-image ARGs default to a Docker Hub mirror; override to docker.io if you prefer.
ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-bookworm
ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim-bookworm

FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY web/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HYDRO_AGENT_HOST=0.0.0.0 \
    HYDRO_AGENT_PORT=8000 \
    HYDRO_AGENT_DB=/data/hydro.db \
    HYDRO_AGENT_REPORTS=/data/reports \
    HYDRO_AGENT_STATIC=/app/web/dist \
    HYDRO_AGENT_MODE=real \
    HYDRO_WORKFLOW_DIR=/app/workflow

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|https\?://deb.debian.org|http://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|https\?://deb.debian.org|http://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      curl ca-certificates build-essential git; \
    rm -rf /var/lib/apt/lists/*; \
    pip install --no-cache-dir "uv==0.8.4"

COPY pyproject.toml uv.lock README.md ./
# Install third-party deps first so editing src/workflow does not re-download packages.
RUN uv sync --frozen --no-install-project --extra api --extra data --extra xaj --extra xaj-dem --no-dev

COPY src ./src
COPY workflow ./workflow
COPY scripts ./scripts
COPY data/academy ./data/academy
COPY tests/fixtures/lowman_reanalysis_source ./tests/fixtures/lowman_reanalysis_source
COPY tests/fixtures/xaj/lowman_scheme.json ./tests/fixtures/xaj/lowman_scheme.json

RUN uv sync --frozen --extra api --extra data --extra xaj --extra xaj-dem --no-dev \
    && mkdir -p /data/reports /data/runtime

COPY --from=web /web/dist /app/web/dist

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${HYDRO_AGENT_PORT}/api/health" || exit 1

CMD ["uv", "run", "python", "scripts/run_workbench_api.py"]
