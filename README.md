# Project Knowledge & Requirement Traceability Assistant

A local-first **RAG (Retrieval-Augmented Generation)** backend that grounds AI chat answers in your organisation's documents. Users ask questions in their usual AI chat (Copilot, Gemini, ChatGPT, Claude) — a browser extension intercepts the query, retrieves ranked evidence from a local index, and injects it into the prompt so the AI answers **only from your documents, with citations**.

No cloud dependencies: everything runs on your laptop — SQLite catalog + ChromaDB vector store + a local embedding model.

---

## Features

- **Semantic search over your documents** — ask anything, get ranked evidence chunks with `relevance_score`, source file, path, and extracted metadata (project names, REQ IDs, CR numbers).
- **Catalog listing** — "list all the project documents" returns every folder/project with document counts (from SQLite, no top-k cutoff); per-source file listings in the admin UI.
- **Multi-source ingestion** — network shares (filesystem-mounted or SMB), local folders, and single-file uploads.
- **Live ingestion progress** — scans run in the background (`202` + `run_id`) with per-document progress bars in the admin UI.
- **Admin dashboard** — register/test/scan/edit/disable sources, per-source file inventory, run history, data cleanup.
- **Browser extension (Chrome/Edge, Manifest V3)** — auto-detects Copilot, Gemini, ChatGPT, and Claude; injects grounding prompts with evidence.
- **Admin auth** — signed session cookies over file-based credentials (SHA-256 + salt).
- **Extraction** — PDF, DOCX, Markdown, and TXT text extraction; deterministic metadata extraction; 1000-char chunks with 200-char overlap.

---

## Architecture

```
User asks question in AI Chat (Copilot / Gemini / ChatGPT / Claude)
  → Browser Extension detects provider by URL
  → Extension calls local RAG backend (http://localhost:8000)
  → Backend retrieves evidence from SQLite Catalog + ChromaDB
  → Backend returns ranked evidence package
  → Extension formats a grounding prompt and injects it into the chat
  → AI answers using only the provided evidence
```

| Component | Tech |
|-----------|------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2 |
| Catalog DB | SQLite via aiosqlite (authoritative traceability) |
| Vector DB | ChromaDB (persistent, local) |
| Embeddings | `all-MiniLM-L6-v2` via sentence-transformers (384-dim, CPU-friendly) |
| Extraction | PyMuPDF, python-docx, built-in text readers |
| Extension | Vanilla JS, Manifest V3 (Chrome/Edge) |
| Testing | pytest + pytest-asyncio + httpx |

```
src/
  main.py                 FastAPI app + HTML pages
  api/                    REST endpoints (chat, admin, ingestion, health)
  ingestion/              Connectors, extractor, chunker, embedder, orchestrator
  models/                 SQLAlchemy models (15+ tables)
  templates/              search.html, admin.html, login.html
  middleware/             Request ID, logging, error handling
extension/                Browser extension (providers, popup, content script)
alembic/                  Schema migrations
sample_docs/              Sample documents for trying ingestion
tests/                    pytest suite
```

---

## Quickstart

> **Full installation & deployment guide:** see [`INSTALL.md`](INSTALL.md) — backend setup, production run options (systemd), browser-extension distribution, backup/restore, and **Docker deployment** (build locally or pull the pre-built image from GHCR).

### 1. Prerequisites

- Python 3.11+
- Chrome or Edge (for the extension)

### 2. Install

```bash
cd project_rag
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The first ingestion will download the `all-MiniLM-L6-v2` embedding model (~80 MB) from Hugging Face.

### 3. Configure admin credentials

Create the admin user (the app reads `data/.credentials`):

```bash
mkdir -p data
.venv/bin/python3 -c "from src.auth import generate_credential_line; print(generate_credential_line('admin', 'your-password'))" > data/.credentials
chmod 600 data/.credentials
```

### 4. Run the server

```bash
.venv/bin/python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

- Query page: **http://127.0.0.1:8000**
- Admin dashboard: **http://127.0.0.1:8000/admin** (login required)
- API docs (Swagger): **http://127.0.0.1:8000/docs**

### 5. Ingest documents

1. Open the **Admin** page → **Add Data Source**.
2. Pick a **Network Share** (any mounted path — GVFS, UNC, /Volumes) or **Local Folder**.
3. Click **Test** to verify connectivity, then **Scan** — ingestion runs in the background with a live progress bar.
4. Ask questions on the query page, or load the extension and ask in any AI chat.

### 6. Run the tests

```bash
.venv/bin/python3 -m pytest tests/ -v
```

---

## Browser Extension

See [`extension/README.md`](extension/README.md) for full details, and [`INSTALL.md`](INSTALL.md) §6 for **deployment & distribution** (load unpacked, ZIP/CRX packaging, provider calibration).

1. Open `chrome://extensions` (or `edge://extensions`), enable **Developer mode**.
2. **Load unpacked** → select the `extension/` directory.
3. Open a supported AI chat — a "RAG Ready" badge appears. Ask a question and the extension injects grounded evidence automatically.

Supported providers: Microsoft Copilot, Google Gemini, ChatGPT, Claude (auto-detected by URL).

---

## API Overview

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Query web UI |
| `GET /admin`, `GET/POST /admin/login` | Admin UI + login |
| `POST /api/chat/query` | Semantic search → ranked evidence (`top_k` 1–20). Listing questions return `intent: "listing"` + folders |
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

---

## Security Notes

- Admin credentials are stored hashed (`sha256$salt$hash`) in `data/.credentials`; session tokens are HMAC-signed with a random secret in `data/.session_secret`.
- `data/` (credentials, DB, ChromaDB, uploads) is **git-ignored** — never commit it.
- The admin API requires the session cookie; the query endpoint is public by design.

---

## Project Status

**Verified live on 2026-08-17:** 36/36 tests passing; server running on `0.0.0.0:8000`; 59/59 documents from the `omv` network share re-indexed in ~22 s (246 chunks, zero errors); semantic search, catalog listing, live scan progress, and the full admin API confirmed working end-to-end.

Working features: the admin API (Bucket 4), the browser extension (Bucket 5), multi-source ingestion, live ingestion progress, catalog listing, Docker deployment + GHCR publishing.

Known gaps: Bucket 3 confidence scoring / formal citations (FR-008), insufficient-evidence enforcement (FR-009), admin metadata enrichment (FR-012), extension live calibration, and SMB connector tests.

### Deployment options

| Option | When | How |
|--------|------|-----|
| Bare metal | Dev / single laptop | `pip install -e ".[dev]"` then `uvicorn src.main:app` (INSTALL.md §4) |
| systemd | Always-on laptop/server | User service (INSTALL.md §4.2) |
| Docker (local build) | Any machine with Docker | `docker compose up -d --build` (INSTALL.md §7) |
| Docker (pre-built image) | No-build deployments | `docker compose up -d` → pulls `ghcr.io/chitrangad/rag-assistant:latest` (INSTALL.md §7.4; image published by GitHub Actions on `main` and `v*` tags) |
