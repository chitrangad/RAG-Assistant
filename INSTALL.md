# Installation & Deployment Guide

This guide walks through installing and deploying the Project Knowledge Assistant on a laptop or server, and distributing the browser extension.

- **Version:** 0.1.0
- **Stack:** Python 3.11+ (FastAPI), SQLite, ChromaDB, local embedding model, Manifest V3 browser extension
- **Deployment model:** Local-first. No cloud services required.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Tested on 3.12 |
| pip | modern | Included with Python |
| Chrome / Edge | — | Only needed for the browser extension |
| Disk space | ~2 GB | 1.3 GB for the Python/ML stack + ~80 MB embedding model |
| RAM | 4 GB+ | Embedding model loads into memory at first use |

Optional but recommended:

- `git` — to clone the repository
- A mounted network share (GVFS/UNC/NFS) or local folder to ingest

---

## 2. Install the Backend

### 2.1 Get the code

```bash
git clone https://github.com/chitrangad/RAG-Assistant.git
cd RAG-Assistant
```

### 2.2 Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows
```

### 2.3 Install dependencies

```bash
pip install -e ".[dev]"
```

This installs the runtime stack (FastAPI, SQLAlchemy, ChromaDB, sentence-transformers, PyMuPDF, python-docx) and the dev/test tools.

> **First run note:** the `all-MiniLM-L6-v2` embedding model (~80 MB) downloads from Hugging Face the first time you ingest a document. Offline installs must pre-cache it (`python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"`).

### 2.4 Verify the install

```bash
.venv/bin/python3 -m pytest tests/ -q
```

Expect **36 passed**.

---

## 3. Configuration

### 3.1 Admin credentials

The admin dashboard is protected by a file-based credential store (`data/.credentials`). Create the first admin user:

```bash
mkdir -p data
.venv/bin/python3 -c "from src.auth import generate_credential_line; print(generate_credential_line('admin', 'your-strong-password'))" > data/.credentials
chmod 600 data/.credentials
```

Add more users by appending more `username:hash` lines.

### 3.2 Environment variables (optional)

All settings have sensible defaults (see `src/config.py`). Override via a `.env` file in the project root or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Port |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/catalog.db` | Catalog DB |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | Vector store |
| `CHUNK_SIZE` | `1000` | Chunk size (chars) |
| `CHUNK_OVERLAP` | `200` | Chunk overlap (chars) |
| `LOG_LEVEL` | `INFO` | Logging |

---

## 4. Run the Backend

### 4.1 Quick start (development / single laptop)

```bash
.venv/bin/python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Then open:

- Query page: `http://127.0.0.1:8000`
- Admin dashboard: `http://127.0.0.1:8000/admin`
- API docs: `http://127.0.0.1:8000/docs`

### 4.2 Production-style run (systemd — Linux)

For a machine that should always have the assistant running (e.g. a work laptop or small server), install a user systemd service:

```ini
# ~/.config/systemd/user/rag-assistant.service
[Unit]
Description=RAG Knowledge Assistant
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/USER/RAG-Assistant   # <-- replace USER with the real username
ExecStart=/home/USER/RAG-Assistant/.venv/bin/python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=3
Environment=LOG_LEVEL=INFO

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now rag-assistant
systemctl --user status rag-assistant
```

### 4.3 Expose beyond localhost (optional)

To let other machines on the LAN reach the backend (needed if the extension points at a shared server):

```bash
.venv/bin/python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

> **Security:** the query API is public by design; the admin API requires the session cookie. Do not expose `0.0.0.0` to the public internet without a reverse proxy + TLS (e.g. Caddy/nginx).

---

## 5. Load Content (Ingestion)

1. Open **Admin** → **Add Data Source**.
2. Choose **Network Share** (any mounted path — GVFS, UNC, `/Volumes`) or **Local Folder**.
3. Enter the path; click **Test** to verify connectivity.
4. Click **Scan** — ingestion runs in the background with a live progress bar in the UI.
5. Query the content at `/`.

Sources are stored in `data/catalog.db`; the index lives in `data/chroma`. Both are git-ignored and safe to back up by copying the `data/` directory.

---

## 6. Deploy the Browser Extension

The extension is a **Manifest V3** Chrome/Edge extension in the `extension/` directory. It intercepts queries in AI chat pages (Copilot, Gemini, ChatGPT, Claude), calls the local backend, and injects a grounding prompt.

### 6.1 Load it (developer mode — personal use)

1. Open `chrome://extensions` (or `edge://extensions`).
2. Toggle **Developer mode** on (top-right).
3. Click **Load unpacked**.
4. Select the `extension/` folder inside the project.
5. Pin the extension icon to the toolbar.

> Icons are git-ignored; if the badge icon is missing, generate it: `python3 extension/generate_icons.py`.

### 6.2 Configure it

Click the extension icon → popup:

- **AI Provider** — Auto-detect (recommended) or force one.
- **Backend URL** — default `http://localhost:8000`. Change this if the backend runs on another machine (`http://192.168.x.x:8000`).
- **Enable/Disable** — toggle grounding on/off.

### 6.3 Package it for distribution (work laptops / team)

To distribute to a team without "Developer mode":

**Option A — ZIP (load unpacked on each machine):**

```bash
cd extension
zip -r ../rag-extension.zip . -x "icons/icon*.png"
# recipient: chrome://extensions → Developer mode → Load unpacked → unzip → select folder
```

**Option B — CRX (packed, Chrome Web Store style):**

1. `chrome://extensions` → Developer mode → **Pack extension**.
2. Select the `extension/` folder.
3. Chrome produces a `.crx` (installable by dragging into `chrome://extensions`) and a `.pem` private key (keep safe — needed for signed updates).
4. For organization-wide install, publish the CRX to the **Chrome Web Store** or distribute via policy (ADMX/GPO or MDM).

### 6.4 Supported providers

| Provider | URL | Status |
|----------|-----|--------|
| Google Gemini | `gemini.google.com` | Tested |
| ChatGPT | `chat.openai.com`, `chatgpt.com` | Tested |
| Microsoft Copilot | `*.cloud.microsoft`, `copilot.microsoft.com`, `bing.com/chat` | Best-effort selectors |
| Anthropic Claude | `claude.ai` | Best-effort selectors |

> Provider DOM selectors may need recalibration if an AI service updates its UI. Use `extension/diagnose.js` in the DevTools console to re-detect selectors.

### 6.5 Verify end-to-end

1. Start the backend (section 4).
2. Ingest some content (section 5).
3. Open `https://chatgpt.com`, type *"list all the project documents"*.
4. The badge turns blue and the prompt is injected with the folder catalog; the AI answers from your documents.

---

## 7. Docker Deployment

Containerized deployment is supported: **`Dockerfile`** + **`docker-compose.yml`** in the repo root.

The image:
- Installs the CPU-only PyTorch build (keeps the image lean — no multi-GB CUDA deps)
- **Pre-caches the embedding model (`all-MiniLM-L6-v2`) at build time** — the container ingests and queries fully offline
- Persists everything in the bind-mounted `./data` directory (SQLite catalog + ChromaDB + uploads)

### 7.1 Build & run

> **Requires Docker with the Compose v2 plugin (`docker compose`).** The legacy standalone `docker-compose` v1 is not supported.

```bash
cd RAG-Assistant
cp -r <your existing data> ./data    # optional: migrate an existing install's data/
docker compose up -d --build
```

- Query page: `http://127.0.0.1:8000`
- Admin: `http://127.0.0.1:8000/admin`
- Logs: `docker compose logs -f` · Stop: `docker compose down` (data is kept in `./data`)

> The container runs as **root** so the host-mounted `./data` is always writable regardless of host UID (see the Dockerfile comment for a stricter non-root option).

### 7.2 Fresh start

```bash
docker compose down
docker compose up -d --build
```

### 7.3 Manual build (no compose)

```bash
docker build -t rag-assistant:latest .
docker run -p 8000:8000 -v "$PWD/data:/app/data" rag-assistant:latest
```

### 7.4 Pre-built image on GitHub Container Registry (GHCR)

A **pre-built image** is published automatically to `ghcr.io/chitrangad/rag-assistant` by the GitHub Actions workflow `.github/workflows/docker-publish.yml`. It runs the test suite, builds the image, and pushes on every push to `main` and on `v*` tags:

| Tag | Trigger |
|-----|---------|
| `latest` | latest `main` |
| `vX.Y.Z` (e.g. `v0.1.0` → `0.1.0`) | semver release tags |
| `sha-<short>` | every build |

Deployments can then **skip the local build entirely** — just pull the image:

```yaml
services:
  rag-assistant:
    image: ghcr.io/chitrangad/rag-assistant:latest
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data          # SQLite + ChromaDB persistence
    environment:
      - HOST=0.0.0.0
      - PORT=8000
    restart: unless-stopped
```

```bash
docker compose up -d          # pulls the pre-built image — no local build
```

> **GHCR access:** packages are **private by default** after the first CI push. To allow unauthenticated pulls (the flow above), open the package settings — `github.com/users/chitrangad/packages/container/package/rag-assistant` → **Package settings** → **Danger Zone** → *Change visibility* → **Public**. Alternatively keep it private and `docker login ghcr.io` on each machine with a token that has `read:packages`.

Benefits: reproducible installs, no Python/venv management on the target machine, easier server/hosted deployment.

---

## 8. Backup & Restore

Everything that matters lives in `data/`:

```bash
# Backup (stop the service first for a consistent copy)
tar czf rag-backup.tar.gz data/

# Restore
tar xzf rag-backup.tar.gz
```

---

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No documents indexed` on query | Ingest content first (section 5) |
| Extension badge shows red / error | Backend not running, or `Backend URL` wrong in popup |
| Extension badge stays gray | Query classified as unrelated, or no evidence ≥ 30% match |
| Model download fails on first ingest | Pre-cache the model (section 2.3) or retry with internet access |
| Admin login fails | Recreate `data/.credentials` with `generate_credential_line` (section 3.1) |
| Port 8000 in use | Set `PORT` env var, or edit the systemd `ExecStart` |
