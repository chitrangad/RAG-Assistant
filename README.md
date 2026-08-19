# Project Knowledge & Requirement Traceability Assistant

A local-first **RAG (Retrieval-Augmented Generation)** assistant that answers project-knowledge questions from your documents — fully offline. It retrieves ranked evidence from a local index and synthesises a natural-language answer with citations using a **small local LLM (Qwen3-1.7B)**, with an optional external AI API for higher-quality answers.

No cloud dependencies: everything runs on your laptop — SQLite catalog + ChromaDB vector store + a local embedding model + a local LLM.

---

## Features

- **Grounded answers** — ask anything and get a natural-language answer with numbered citations, synthesised from the top evidence (not just raw snippets).
- **Local LLM baked in** — Qwen3-1.7B via llama-cpp-python (CPU-only, ~1.1 GB); answers work fully offline.
- **Optional external AI** — point the answer engine at any OpenAI-compatible API (OpenAI, Ollama, LM Studio, …) from the admin panel.
- **Insufficient-evidence handling (FR-009)** — if no evidence clears the relevance threshold, the assistant says it doesn't know instead of inventing an answer.
- **Semantic search + metadata** — ranked evidence chunks with `relevance_score`, source file, path, and extracted metadata (project names, REQ IDs, CR numbers).
- **Catalog listing** — "list all the project documents" returns every folder/project with document counts (from SQLite, no top-k cutoff).
- **Multi-source ingestion** — network shares (filesystem-mounted or SMB), local folders, and single-file uploads, with live per-document progress.
- **Per-source file-type exclusion** — skip specific extensions (e.g. `epub`, `docx`) per source during scans.
- **Admin dashboard** — register/test/scan/edit/disable sources, file inventory, run history, answer-engine settings, data cleanup.
- **Admin auth** — signed session cookies over file-based credentials (SHA-256 + salt); the first run prompts you to create the admin account in the browser.
- **Extraction** — PDF, DOCX, Markdown, and TXT text extraction; deterministic metadata extraction; 1000-char chunks with 200-char overlap.

---

## Architecture

```
User asks a question on the query page (or via the API)
  → Backend retrieves ranked evidence from SQLite Catalog + ChromaDB
  → Answer engine synthesises a grounded answer from the evidence:
      • local LLM (Qwen3-1.7B) by default — fully offline
      • or an external OpenAI-compatible API (configured in the admin panel)
  → Answer is returned with numbered citations + the evidence snippets
```

| Component | Tech |
|-----------|------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2 |
| Catalog DB | SQLite via aiosqlite (authoritative traceability) |
| Vector DB | ChromaDB (persistent, local) |
| Embeddings | `all-MiniLM-L6-v2` via sentence-transformers (384-dim, CPU-friendly) |
| Answer LLM | Qwen3-1.7B (1.7B, GGUF) via llama-cpp-python (local default); any OpenAI-compatible API (optional) |
| Extraction | PyMuPDF, python-docx, built-in text readers |
| Testing | pytest + pytest-asyncio + httpx |

```
src/
  main.py                 FastAPI app + HTML pages
  api/                    REST endpoints (chat, admin, ingestion, health)
  ingestion/              Connectors, extractor, chunker, embedder, orchestrator
  llm/                    LLM providers (local/external), prompts, settings
  models/                 SQLAlchemy models (15+ tables)
  templates/              search.html, admin.html, login.html, setup.html
  middleware/             Request ID, logging, error handling
alembic/                  Schema migrations
sample_docs/              Sample documents for trying ingestion
tests/                    pytest suite
```

---

## Quickstart

> **Full installation & deployment guide:** see [`INSTALL.md`](INSTALL.md) — two supported methods: bare metal (`install.sh`) or Docker Compose (pre-built GHCR image), plus systemd, network-share mounting, backup/restore, and configuration.

### 1. Prerequisites

- Python 3.11+ (bare metal) **or** Docker + Compose v2 (container)
- ~1.5 GB free disk/RAM for the local embedding + answer models

### 2. Deploy

**Bare metal — one script:**

```bash
./install.sh                      # prompts for the admin password
.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

**Docker Compose — pre-built image:**

```bash
cp .env.example .env
docker compose up -d              # pulls ghcr.io/chitrangad/rag-assistant:latest
```

- Query page: **http://127.0.0.1:8000**
- Admin dashboard: **http://127.0.0.1:8000/admin** (on first run you'll be prompted to create the admin account; login afterwards)
- API docs (Swagger): **http://127.0.0.1:8000/docs**

### 3. Ingest documents

1. Open the **Admin** page → **Add Data Source**.
2. Pick a **Network Share** (any mounted path — GVFS, UNC, /Volumes) or **Local Folder**. Optionally set **Exclude File Types** to skip extensions (e.g. `epub, docx`).
3. Click **Test** to verify connectivity, then **Scan** — ingestion runs in the background with a live progress bar.
4. Ask questions on the query page — you'll get a grounded answer with citations. Optionally switch the answer engine to an external AI API in **Admin → AI Answer Engine**.

### 4. Run the tests

```bash
.venv/bin/python3 -m pytest tests/ -v
```

---

## API Overview

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Query web UI |
| `GET /admin`, `GET/POST /admin/login`, `POST /admin/setup` | Admin UI + login + first-run account creation |
| `POST /api/chat/query` | Answer a question: ranked evidence + a synthesised `answer` with `citations` (`top_k` 1–20). Listing questions return `intent: "listing"` + folders |
| `POST /api/ingest/upload` | Ingest a single file |
| `POST /api/ingest/local-folder` | Ingest a local folder |
| `GET /api/ingest/stats` | Chunk count |
| `GET /api/health`, `GET /api/ready` | Health checks |
| `GET /api/admin/sources` | List sources (auth) |
| `POST /api/admin/sources` | Register a source (auth) |
| `GET /api/admin/sources/{id}/documents` | Files ingested for a source (auth) |
| `POST /api/admin/sources/{id}/scan` | Start background ingestion → `202` + `run_id` (auth) |
| `GET /api/admin/runs/{id}` | Poll live scan progress (auth) |
| `GET /api/admin/health` | Extended health: DB + Chroma + counts (auth) |
| `GET/PUT /api/admin/llm-settings` | Read/update answer-engine settings — provider, model, API key (auth) |
| `POST /api/admin/llm/test` | Send a trivial prompt to verify the configured provider (auth) |

Admin endpoints require the `admin_session` cookie (login at `/admin/login`).

---

## Configuration

All settings have defaults (see `src/config.py`); override via environment variables or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Port |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/catalog.db` | Catalog DB |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | Vector store location |
| `CHUNK_SIZE` | `1000` | Chunk size (chars) |
| `CHUNK_OVERLAP` | `200` | Chunk overlap (chars) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

Answer-engine settings (provider, model path, context, temperature, external API base URL / key / model, minimum relevance score) are **managed at runtime in the admin panel** (Admin → AI Answer Engine) and persisted to `data/llm_settings.json`. Environment variables are not needed for them.

---

## Security Notes

- Admin credentials are stored hashed (`sha256$salt$hash`) in `data/.credentials`; session tokens are HMAC-signed with a random secret in `data/.session_secret`.
- `data/` (credentials, DB, ChromaDB, uploads, LLM settings incl. any external API key) is **git-ignored** — never commit it.
- The admin API requires the session cookie; the query endpoint is public by design.

---

## Project Status

**Verified live on 2026-08-18:** 96/96 tests passing; server running on `0.0.0.0:8000`; 59/59 documents from the `omv` network share re-indexed in ~22 s (246 chunks, zero errors); semantic search, catalog listing, live scan progress, and the full admin API confirmed working end-to-end.

Working features: the admin API (Bucket 4), a local answer engine with natural-language answers + citations (Bucket 3 partial — FR-009 insufficient-evidence enforcement now included), multi-source ingestion, per-source file-type exclusion, first-run admin account creation, live ingestion progress, catalog listing, Docker deployment + GHCR publishing.

Known gaps: formal confidence scoring / structured citation objects (FR-008) and admin metadata enrichment (FR-012). The browser extension (former Bucket 5) has been removed — answer synthesis now happens in-app.

### Deployment options

| Option | When | How |
|--------|------|-----|
| Bare metal | Dev / single laptop | `pip install -e ".[dev]"` then `uvicorn src.main:app` (INSTALL.md §4) |
| systemd | Always-on laptop/server | System service (INSTALL.md §A) |
| Docker (local build) | Any machine with Docker | `docker compose up -d --build` (INSTALL.md §7) |
| Docker (pre-built image) | No-build deployments | `docker compose up -d` → pulls `ghcr.io/chitrangad/rag-assistant:latest` (INSTALL.md §7.4; image published by GitHub Actions on every push to `main`) |
