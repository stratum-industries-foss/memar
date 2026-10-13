# syntax=docker/dockerfile:1

# Stage 1: Build frontend
FROM --platform=$BUILDPLATFORM node:20-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --legacy-peer-deps
COPY frontend/ ./
RUN --mount=type=cache,target=/root/.cache npm run build
# Output lands at /build/frontend_dist/ (vite outDir: ../frontend_dist)

# Stage 2: Install Python dependencies into a venv
FROM python:3.12-slim AS python-builder
WORKDIR /build
RUN python3 -m venv /venv
COPY backend/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip /venv/bin/pip install -r requirements.txt

# Stage 3: Build Rust CV tools
FROM rust:1.79-slim AS rust-builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*
COPY tools/print-cv ./print-cv
COPY tools/spool-cv ./spool-cv
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cd print-cv && cargo build --release
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    cd spool-cv && cargo build --release

# Stage 4: Final image
FROM python:3.12-slim
WORKDIR /app

# Install Node.js runtime from official Debian packages (no curl|bash)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Higgsfield CLI for 3D floor plan generation
RUN npm install -g @higgsfield/cli@1.1.20

COPY --from=python-builder /venv /venv
COPY --from=frontend-builder /build/frontend_dist/ ./frontend_dist/
COPY --from=rust-builder /build/print-cv/target/release/print-cv /usr/local/bin/print-cv
COPY --from=rust-builder /build/spool-cv/target/release/spool-cv /usr/local/bin/spool-cv
COPY backend/ ./backend/
COPY config/ ./config/
COPY VERSION BUILD_ID ./

# Create non-root user
RUN useradd -r memar

ENV PATH=/venv/bin:$PATH \
    MEMAR_DATA_DIR=/app/data \
    MEMAR_ENV=production \
    MEMAR_PRINT_CV_BIN=/usr/local/bin/print-cv

EXPOSE 9000

# Switch to non-root user
USER memar

CMD ["python3", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "9000"]
