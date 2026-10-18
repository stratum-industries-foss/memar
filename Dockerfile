# syntax=docker/dockerfile:1
# Zero-config image: nothing is required to start. On first start the container
# prints a one-time setup link (`docker logs memar`). All state lives in /app/data.
#
# Base images are pinned to minor tags. Bump them deliberately; CI builds weekly.

# Stage 1: build the frontend (runs on the build host, not emulated)
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --legacy-peer-deps
COPY frontend/ ./
RUN --mount=type=cache,target=/root/.cache npm run build
# Output lands at /build/frontend_dist/ (vite outDir: ../frontend_dist)

# Stage 2: Python dependencies into a venv (built for the target platform)
FROM python:3.13-slim AS python-builder
WORKDIR /build
RUN python3 -m venv /venv
COPY backend/requirements.txt ./
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# Stage 3: Rust CV tools. Runs on the build host and cross-compiles for
# TARGETARCH, so an arm64 image does not run cargo under QEMU.
FROM --platform=$BUILDPLATFORM rust:1.98-slim AS rust-builder
ARG TARGETARCH
WORKDIR /build
COPY tools/print-cv ./print-cv
COPY tools/spool-cv ./spool-cv
RUN --mount=type=cache,target=/usr/local/cargo/registry set -eux; \
    case "$TARGETARCH" in \
      amd64) T=x86_64-unknown-linux-gnu;  PKGS="gcc-x86-64-linux-gnu libc6-dev-amd64-cross";  LINKER=x86_64-linux-gnu-gcc ;; \
      arm64) T=aarch64-unknown-linux-gnu; PKGS="gcc-aarch64-linux-gnu libc6-dev-arm64-cross"; LINKER=aarch64-linux-gnu-gcc ;; \
      *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    HOST="$(rustc -vV | sed -n 's/^host: //p')"; \
    if [ "$T" != "$HOST" ]; then \
      apt-get update; \
      apt-get install -y --no-install-recommends $PKGS; \
      rm -rf /var/lib/apt/lists/*; \
      rustup target add "$T"; \
      export "CARGO_TARGET_$(echo "$T" | tr 'a-z-' 'A-Z_')_LINKER=$LINKER"; \
    fi; \
    for tool in print-cv spool-cv; do \
      (cd "$tool" && cargo build --release --target "$T"); \
    done; \
    mkdir -p /out; \
    cp "print-cv/target/$T/release/print-cv" "spool-cv/target/$T/release/spool-cv" /out/

# Stage 4: final image
FROM python:3.13-slim
WORKDIR /app

# Node.js runtime for the Higgsfield CLI (official Debian packages, no curl|bash)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Higgsfield CLI for 3D floor plan generation
RUN npm install -g @higgsfield/cli@1.1.20 && npm cache clean --force

COPY --from=python-builder /venv /venv
COPY --from=frontend-builder /build/frontend_dist/ ./frontend_dist/
COPY --from=rust-builder /out/print-cv /usr/local/bin/print-cv
COPY --from=rust-builder /out/spool-cv /usr/local/bin/spool-cv
COPY backend/ ./backend/
COPY config/ ./config/
# BUILD_ID is optional (it is not in the public repo); the glob lets COPY skip it.
COPY VERSION BUILD_I[D] ./
COPY scripts/memar /usr/local/bin/memar
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint

# Fixed uid/gid so volume ownership is predictable across hosts.
RUN groupadd -g 10001 memar \
    && useradd -u 10001 -g 10001 -r -m -d /home/memar -s /usr/sbin/nologin memar \
    && install -d -o memar -g memar -m 0750 /app/data /app/data/logs \
    && chmod 0755 /usr/local/bin/memar /usr/local/bin/docker-entrypoint

ENV PATH=/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    MEMAR_ENV=production \
    MEMAR_PORT=8000 \
    MEMAR_DATA_DIR=/app/data \
    MEMAR_DB_PATH=/app/data/memar.db \
    MEMAR_CONFIG_PATH=/app/data/devices.yaml \
    MEMAR_LOG_DIR=/app/data/logs \
    MEMAR_PRINT_CV_BIN=/usr/local/bin/print-cv

EXPOSE 8000
VOLUME ["/app/data"]

# Readiness probe checks the DB via /api/readyz. Python stdlib only.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python3", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/api/readyz' % os.environ.get('MEMAR_PORT', '8000'), timeout=4)"]

# The entrypoint fixes data-dir ownership as root, then drops to uid 10001
# (or MEMAR_UID/MEMAR_GID). Starting with --user skips that step.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]
CMD ["sh", "-c", "exec python3 -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port \"${MEMAR_PORT:-8000}\""]
