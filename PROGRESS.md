# Progress Checkpoint — Project Knowledge Assistant

**Date:** 2026-07-31 (evening session — closed out & published)
**Status:** ✅ 36/36 tests passing. ✅ Ingestion + Query working. ✅ Upload link removed from query page. ✅ Browser Extension (Bucket 5) built. ✅ Admin API (Bucket 4) implemented. ✅ Samba/network-share source working. ✅ Source path editing fixed (user-verified). ✅ Live ingestion progress (user-verified). ✅ Catalog listing (folders/projects) implemented. ✅ Published to GitHub (`chitrangad/RAG-Assistant`, branch `main`). ✅ Docker deployment (Dockerfile + compose + .dockerignore). ✅ GHCR publishing workflow (`.github/workflows/docker-publish.yml`). ✅ Release tag `v0.1.0` pushed. ✅ Server running.
**Server:** Running on PID 70628 (http://127.0.0.1:8000)

---

## Deployment & Publishing Session (2026-07-31, later)

### Repository published to GitHub

- Repo: **https://github.com/chitrangad/RAG-Assistant.git** (remote `origin`, branch `main`, SSH)
- Commit history on `main` (most recent first):
  1. `3c9e7f8` — Publish pre-built image to GHCR via GitHub Actions workflow; wire compose to `ghcr.io/chitrangad/rag-assistant`; update INSTALL.md §7.4
  2. `e43dc2e` — Add Docker deployment: Dockerfile (pre-cached embedding model), docker-compose.yml, .dockerignore; update INSTALL.md §7; declare `python-multipart`
  3. (initial) — Full project + README.md + INSTALL.md deployment guide
- Local git identity: `chitrangad` / `chitrangad@users.noreply.github.com`
- Secret-scan performed before each push (no `data/`, credentials, session secrets, venv, or zips staged).

### Docker deployment (implemented — was roadmap)

| File | Contents |
|------|----------|
| `Dockerfile` | `python:3.12-slim` + `libgomp1` (apt, needed by torch/onnxruntime), **CPU-only torch** from the PyTorch CPU index (single `--index-url` so the multi-GB CUDA wheel can never be pulled), `pip install .` from pyproject, **embedding model `all-MiniLM-L6-v2` pre-cached at build time** (container ingests/queries fully offline), `EXPOSE 8000`, `CMD uvicorn --host 0.0.0.0 --port 8000`. Runs as root (documented — keeps host-mounted `./data` writable). |
| `docker-compose.yml` | Service `rag-assistant`: `build: .` + `image: ghcr.io/chitrangad/rag-assistant:latest`, port `8000:8000`, volume `./data:/app/data`, env `HOST`/`PORT`/`ANONYMIZED_TELEMETRY=False`, urllib healthcheck, `restart: unless-stopped`. |
| `.dockerignore` | Excludes `data/`, `.venv`, `.git`, caches, `extension/`, `sample_docs/`, `tests/`, docs, db/log/zip files — everything the build needs survives (pyproject.toml, README.md, src/, alembic/). |
| `INSTALL.md` | New deployment guide: §1–6 backend/extension setup, §7 Docker deployment, §8 backup/restore, §9 troubleshooting. |
| `pyproject.toml` | **BUG FIX** — added `python-multipart>=0.0.9` (admin login `Form(...)` + uploads need it; host venv had it but it was undeclared, so the Docker image lacked it → FastAPI warned `pip install python-multipart` at startup). |

**Bugs caught during Docker validation (all fixed):**
1. `libgomp1` missing on Debian slim → runtime crash — added apt install.
2. `python-multipart` undeclared → admin login would fail in the container — declared in pyproject.
3. Invalid `torch==2.*+cpu` pin (PEP 440 wildcard + local label is a syntax error) → reverted to the proven single-index `pip install --index-url https://download.pytorch.org/whl/cpu torch` form.
4. `--extra-index-url` fallback could let pip resolve CUDA torch from PyPI → removed; single index keeps the CPU build deterministic.

**Validation:** real `docker build` succeeded (3×), `docker run` smoke printed `FINAL SMOKE OK` (torch, multipart, chromadb, `src.main`, pre-cached model all load), 36/36 host tests pass.

### GHCR publishing workflow (implemented — was roadmap)

`.github/workflows/docker-publish.yml` — **Build & Publish Docker Image**: triggers on push to `main`, `v*` tags, and `workflow_dispatch`.

- Permissions: `contents: read`, `packages: write`, `actions: write` (the last one required for the Buildx `type=gha` cache — an explicit permissions block sets all unlisted scopes to `none`).
- Job `test`: Python 3.12, CPU-only torch first, then `pip install ".[dev]"`, `pytest tests/ -q`.
- Job `docker` (needs `test`): buildx → `docker/login-action` to GHCR with `GITHUB_TOKEN` → `metadata-action` tags (`latest` on default branch, `semver` `v*` → e.g. `0.1.0`, `sha-<short>`) → `build-push-action push: true` with gha cache.
- `docker-compose.yml` `image:` wired to `ghcr.io/chitrangad/rag-assistant:latest` (keeping `build: .` so local `--build` still works and tags with the GHCR name).
- INSTALL.md §7.4 rewritten from roadmap to implemented: tag table, pull-only compose snippet, GHCR access note.

> **Post-push manual step:** GHCR packages are **private by default** after the first CI push. To allow unauthenticated pulls, set visibility → Public at `github.com/users/chitrangad/packages/container/package/rag-assistant` (or `docker login ghcr.io` with a `read:packages` token).

### Release tag

- Annotated tag **`v0.1.0`** created at `3c9e7f8` and pushed → triggers the GHCR workflow; publishes `ghcr.io/chitrangad/rag-assistant:0.1.0` (+ `sha-<short>`; no `latest` on tag pushes).

---

## What's Working Now

### Query Interface
Visit **http://127.0.0.1:8000** — a clean web UI where you type questions and get ranked evidence from your documents. **Upload controls removed** (admin-only via Swagger at `/docs`).

### Samba / Network-Share Source (NEW — WORKING)
A real SMB share is live and indexed:
- Source **"omv"** (`network_share`) → `gvfs/smb-share:server=omv.local,share=data/Backup/AWS Training`
- Mounted via GVFS (no credentials needed for this path — `has_user: false`)
- **21/21 documents discovered and indexed** (PDFs + TXT: AWS-SA-CertificationDump, WhiteBoard-*, notes-*)
- All ingestion runs `completed`; content is queryable via `/api/chat/query`

The `NetworkShareConnector` (`src/ingestion/network_share.py`) supports two modes:
1. **Filesystem mode** (mounted paths — GVFS/NFS/UNC) — used by the `omv` source
2. **SMB client mode** (smbclient with credentials) — `//server/share` UNC parsing, recursive `ls`, `get`-based reads (note: `smbclient` binary not currently installed on this machine — filesystem mode is the active path)

### Admin API (NEW — Bucket 4 implemented)
Full admin surface in `src/api/admin.py` (auth via signed session cookie, `require_admin` dependency):

| Endpoint | Purpose |
|----------|---------|
| `GET /api/admin/sources` | List all data sources |
| `POST /api/admin/sources` | Register a source (network_share, local_folder, sharepoint, upload) |
| `PATCH /api/admin/sources/{id}` | Update source (path, scan_mode, network creds) |
| `GET /api/admin/sources/{id}` | Get one source |
| `GET /api/admin/sources/{id}/documents` | List all files ingested for that source (admin UI "Files" button) |
| `DELETE /api/admin/sources/{id}` | Delete a source + history |
| `PATCH /api/admin/sources/{id}/toggle` | Enable/disable |
| `POST /api/admin/sources/{id}/test` | Test connectivity + count discoverable files |
| `POST /api/admin/sources/{id}/scan` | Start background ingestion → `202` + `run_id` (poll for progress) |
| `GET /api/admin/sources/{id}/runs` | Ingestion run history for a source |
| `GET /api/admin/runs` | Recent runs across all sources |
| `GET /api/admin/runs/{id}` | Single run — polled by the UI for live progress |
| `GET /api/admin/health` | DB + ChromaDB health, counts |
| `DELETE /api/admin/data` | Wipe all ingested data (keeps sources) |
| `DELETE /api/admin/runs/{id}` | Delete a run + its source's data |
| `POST /api/admin/scan` | Quick one-shot scan of any path (no persistent source) |

Admin web UI at **http://127.0.0.1:8000/admin** (`src/templates/admin.html`).

### Browser Extension (Bucket 5)
The `extension/` directory contains a full Manifest V3 Chrome/Edge extension:
- **Provider detection**: Auto-detects Copilot, Gemini, ChatGPT, Claude by URL
- **Query interception**: Captures user queries before they reach the AI
- **Evidence injection**: Calls `POST /api/chat/query`, formats grounding prompt per provider, injects into chat input
- **Settings popup**: Provider selection, backend URL config, enable/disable toggle
- **Status badge**: Floating indicator showing RAG pipeline state

### API Endpoints (full list)
| Endpoint | Purpose |
|----------|---------|
| `GET /` | Query web UI (HTML) |
| `GET /admin` | Admin dashboard (HTML, auth required) |
| `GET/POST /admin/login` | Admin login page / login form |
| `GET /api/info` | JSON API info |
| `GET /api/health` | Liveness check |
| `GET /api/ready` | DB readiness |
| `POST /api/chat/query` | Semantic search (`{"question":"...", "top_k":5}`) → ranked evidence with `relevance_score`, `project_names`, `requirement_ids`, `cr_numbers`. Listing intent (`"list all documents"`) → `intent: "listing"` + `folders` catalog |
| `POST /api/ingest/upload` | Upload single file |
| `POST /api/ingest/local-folder` | Ingest all docs from folder |
| `GET /api/ingest/stats` | Chunks indexed |
| `/api/admin/*` | See Admin API table above |

---

## Changes Today (2026-07-31)

| File | Change |
|------|--------|
| `src/main.py` | Removed "Upload Documents" link from `/` query page (DESIGN CORRECTION) |
| `src/api/admin.py` | **Bucket 4** — Admin API: source CRUD, test-connection, scan trigger, run history, health, data cleanup, quick scan |
| `src/api/admin.py` | **BUG FIX** — `update_source` now copies `connection_details` dict before mutating, so path edits persist (SQLAlchemy ignored in-place JSON mutation) |
| `src/api/admin.py` | **FEATURE** — Scan runs as background task, returns `202` + `run_id`; added `GET /api/admin/runs/{id}` for progress polling |
| `src/ingestion/orchestrator.py` | **FEATURE** — `ingest_from_connector` accepts `run_id`, commits live progress per document (discovered/processed/indexed), marks runs `failed` on error |
| `src/templates/admin.html` | **FEATURE** — Live scan progress note + progress bar, 1.5s polling, running/pending/completed_with_errors badges |
| `tests/test_admin.py` | **NEW** — 8 tests: path-edit persistence, field preservation, run progress endpoint, scan fast-fail, auth guard, orchestrator run_id paths |
| `tests/conftest.py` | Patch `src.api.admin.async_session_factory` so admin tests use the isolated test DB |
| `src/ingestion/network_share.py` | Network share connector: filesystem + SMB modes, UNC parsing, recursive discovery |
| `src/api/chat.py` | **FEATURE** — Catalog listing: intent detection for "list all documents/files" questions; returns folders/projects grouped by file path (doc count + source) instead of top-5 semantic chunks |
| `src/api/admin.py` | **FEATURE** — `GET /api/admin/sources/{id}/documents` per-source file inventory (admin-only) |
| `src/templates/search.html` | **FEATURE** — Folder-card rendering for listing responses; "No documents indexed" empty state |
| `src/templates/admin.html` | **FEATURE** — Per-source "Files" button + inline file list panel (name/type/size/modified/path) |
| `extension/content.js` + `providers/*.js` | **FEATURE** — Extension handles `intent: "listing"` responses; all 4 providers render the folder catalog in grounding prompts |
| `tests/test_chat.py` | **NEW** — 4 tests: listing returns folders, empty catalog, targeted queries stay semantic |
| `src/templates/admin.html` | Admin dashboard UI for sources/ingestion |
| `src/auth.py` | Session-cookie admin auth (`require_admin`, `require_admin_page`) |
| `extension/manifest.json` | **Bucket 5** — Manifest V3 with host_permissions for all providers |
| `extension/content.js` | Provider detection, query interception, RAG injection logic |
| `extension/content.css` | Floating badge styles with 6 states |
| `extension/popup.html` | Settings UI (provider, backend URL, toggle) |
| `extension/popup.js` | Settings management + backend health check |
| `extension/background.js` | Service worker (install defaults, message relay) |
| `extension/providers/registry.js` | Provider adapter registry |
| `extension/providers/copilot.js` | Microsoft Copilot adapter |
| `extension/providers/gemini.js` | Google Gemini adapter |
| `extension/providers/chatgpt.js` | ChatGPT adapter |
| `extension/providers/claude.js` | Anthropic Claude adapter |
| `extension/generate_icons.py` | PNG icon generator |
| `extension/README.md` | Loading and usage instructions |
| `PROGRESS.md` | Updated |

---

## Feature: Catalog Listing ("List All Documents")

**Problem:** Asking to "list all the project documents" returned at most 5 chunks with snippets — because `/api/chat/query` was pure top-k semantic search (UI hardcoded `top_k: 5`), so the vector store's most-similar chunks (often several from the same file) were shown instead of the full catalog.

**Design (confirmed with user):**
1. **Public** — listing-intent detection in `/api/chat/query`. Questions like "list all documents", "what files exist", "show me all files" return `intent: "listing"` + a `folders` array: each folder is a directory from document file paths (gvfs/share-noise stripped) with `document_count` and `sources`. Grouped by count desc. Targeted questions (containing *about/for/related/mention/contain/with*…) stay on the semantic path.
2. **Admin** — per-source **Files** button in the admin UI calls `GET /api/admin/sources/{id}/documents` (admin-only) → inline panel with name/type/size/modified/path for every file in that source.
3. **Extension** — `content.js` + all 4 provider adapters render the folder catalog in grounding prompts when `intent === "listing"`.

**Note:** a doc sitting directly in a share root keeps a raw `smb-share:server=...` folder name (cleaner regex needs a trailing segment) — acceptable for current data.

---

## Bug: Editing a Source Doesn't Update Its Path (FIXED)

**Problem:** Editing a registered source's path (or network creds) from the admin UI appeared to succeed but never persisted — a fresh page load showed the old path.

**Root cause:** `update_source` did `cd = ds.connection_details` — the *same* dict object the ORM holds. Mutating it in place and reassigning the identical object means SQLAlchemy's unit-of-work never sees a change, so the UPDATE was silently skipped.

**Fix:** Copy the dict first: `cd = dict(ds.connection_details or {})`. Now the reassignment registers as a change and the UPDATE is emitted. Verified with a live PATCH→GET round-trip and covered by `test_update_source_path_persists`.

---

## Feature: Live Ingestion Progress

Previously the Scan button blocked until the whole share finished ingesting. Now:

1. `POST /api/admin/sources/{id}/scan` validates synchronously (fast fail on bad paths), creates the ingestion-run row, then returns `202` immediately with a `run_id`.
2. A background asyncio task runs discovery + ingestion; the orchestrator commits progress counters (`documents_discovered` / `documents_processed` / `documents_indexed`) to the run row after each document.
3. The admin UI polls `GET /api/admin/runs/{id}` every 1.5s, showing a progress note ("Indexing X / Y documents") with a percentage bar, and a per-run progress column in the runs table.
4. On completion the poller stops and refreshes sources/health; failures mark the run `failed` (never stuck in `running`). Polling resumes automatically if the page is reloaded mid-scan.

---

## Live Verification (2026-07-31)

Both fixes from this session have been **user-verified end-to-end** through the admin UI at `http://127.0.0.1:8000/admin` (server PID 70628, health OK):

1. **Editing a source's path now persists** — PATCH → reload shows the new path; verified against the `omv` source.
2. **Live scan shows progress** — clicking Scan returns immediately, the runs table shows a live progress bar/note ("Indexing X / Y documents") while ingestion runs in the background, and the run completes without blocking the UI.

For the next agent: the two features below are done and verified — do not re-implement. Remaining gaps are in the "What's Still Missing" table.

---

## Bug: Recursive Injection (FIXED)

**Problem:** After injecting the augmented prompt, `simulateSubmit` would click the submit button, which re-triggered the interceptor, causing the full grounding prompt to be sent back to the RAG backend as a query — infinite loop.

**Fix:** Added `injectingPrompt` flag. When set, both the keydown and click interceptors skip processing entirely, letting the event pass through to the AI provider. Flag is reset 500ms after submit.

---

## Test Results

```
============================== 36 passed in 4.3s ==============================
├── test_health.py: 6/6 (root, api_info, health, readiness, request_id, 404)
├── test_ingestion.py: 16/16 (extractor, metadata, chunker)
├── test_admin.py: 10/10 (+ per-source file listing, auth guard)
└── test_chat.py: 4/4 (listing intent, empty catalog, targeted queries stay semantic)
```

---

## How to Load the Extension

1. Open `chrome://extensions` in Chrome/Edge
2. Enable **Developer mode**
3. Click **Load unpacked** → Select the `extension/` directory

---

## How to Restart Server

```bash
cd /home/chits/project_rag
.venv/bin/python3 -c "
import subprocess, sys
p = subprocess.Popen(
    [sys.executable, '-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', '8000'],
    stdout=open('/tmp/srv.log', 'w'),
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
print(f'PID={p.pid}')
"
```

Run tests: `.venv/bin/python3 -m pytest tests/ -v`

---

## What's Still Missing (from Specs)

| Bucket | Feature | Status |
|--------|---------|--------|
| Bucket 3 | Intent detection + entity extraction | ❌ |
| Bucket 3 | Confidence scoring (beyond raw `relevance_score`) + formal citation builder | ❌ (partial: query returns relevance score, doc name, file path, extracted IDs) |
| Bucket 3 | Insufficient-evidence enforcement (FR-009) | ❌ |
| Bucket 4 | **Admin API** | ✅ Implemented (CRUD, scan, test, runs, health, live progress) |
| Bucket 5 | **Browser Extension** | ✅ Built (needs calibration) |
| Bucket 5 | Provider adapter calibration (live testing) | ❌ |
| Bucket 6 | CI/CD, hardening, INSTALL.md | 🟡 Partial — INSTALL.md done; GitHub Actions CI + GHCR publishing done; Docker deployment done |
| — | Automated tests for network-share / SMB connector | ❌ (no tests yet) |
