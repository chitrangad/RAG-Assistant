# ── Project Knowledge Assistant — container image ──────────────────
# Build:   docker build -t rag-assistant:latest .
# Run:     docker compose up -d          (recommended)
#          docker run -p 8000:8000 -v "$PWD/data:/app/data" rag-assistant:latest
#
# Notes:
#  - The embedding model (all-MiniLM-L6-v2, ~80 MB) is downloaded and
#    cached INTO the image at build time, so the container can ingest and
#    query fully offline.
#  - The image installs the CPU-only build of PyTorch (~200 MB vs ~2.5 GB
#    for the CUDA build) — sentence-transformers runs fine on CPU.
#  - The container runs as root so the host-mounted ./data directory
#    (SQLite catalog + ChromaDB) is always writable regardless of host UID.
#    For a stricter setup, add `USER appuser` and chown the data dir.

FROM python:3.12-slim

# libgomp1 is required by torch / onnxruntime (chromadb dependency) at runtime;
# smbclient lets the app reach remote UNC shares directly (no mount required)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 smbclient && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Project metadata (pyproject.toml references README.md for package metadata)
COPY pyproject.toml README.md ./

# 1) CPU-only PyTorch first so sentence-transformers' dependency on torch
#    resolves to the small build instead of the multi-GB CUDA one.
#    A single --index-url keeps pip strictly on the CPU index, so the CUDA
#    wheel can never be pulled; the index serves torch's full dep tree.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

# 2) llama.cpp (local answer LLM) from the CPU wheel index so the image never
#    compiles it from source. Installed before `pip install .` so the main
#    install sees it already satisfied.
RUN pip install "llama-cpp-python>=0.3.35" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

# 3) The project itself (all runtime deps declared in pyproject.toml).
COPY . .
RUN pip install .

# 4) Pre-cache the embedding model into the image (cached under /root/.cache
#    at build time, so the root user finds it offline at runtime). If you
#    switch to a non-root USER, set HF_HOME to a writable path.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Data lives under /app/data (SQLite + ChromaDB + uploads). Bind-mount it:
#   -v "$PWD/data:/app/data"
RUN mkdir -p /app/data

EXPOSE 8000

# Bind 0.0.0.0 inside the container (compose maps 8000:8000).
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
