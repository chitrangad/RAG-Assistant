# Installation & Deployment Guide

This guide covers installing and deploying the **RAG Knowledge Assistant** — a local-first retrieval-augmented assistant that answers questions from your documents. Everything runs on your machine; documents and queries never leave it (an external AI API is optional and opt-in).

- **Stack:** Python 3.11+ (FastAPI), SQLite, ChromaDB, local embedding model, local answer LLM (Qwen3-1.7B)
- **Deployment model:** Local-first. No cloud services required.

There are **two supported deployment methods**:

| Method | When to use | How |
|--------|-------------|-----|
| **[A. Bare metal](#method-a-bare-metal-installsh)** | Single laptop / server, want direct control, no Docker | One `install.sh` script |
| **[B. Docker Compose](#method-b-docker-compose-pre-built-image)** | Any machine with Docker, reproducible, low-maintenance | `docker compose up -d` (pre-built GHCR image) |

---

## Prerequisites

| Requirement | Version / size | Notes |
|-------------|----------------|-------|
| Python (Method A only) | 3.11+ | Tested on 3.12 |
| Docker + Compose v2 (Method B only) | recent | `docker compose` plugin required |
| smbclient (optional) | recent | Needed to connect to remote **UNC shares without mounting them** (direct SMB mode). Mounted network shares work without it. Installed automatically by `install.sh` / included in the Docker image |
| Disk space | ~4 GB | Python/ML stack + ~80 MB embedding model + ~1.1 GB answer LLM |
| RAM | 8 GB+ | Embedding model + answer LLM both load into memory |

---

## Method A: Bare metal (`install.sh`)

A single script creates the virtualenv, installs all dependencies (CPU-only PyTorch, llama-cpp-python from a prebuilt wheel, and the app), downloads the answer LLM, and creates the admin account.

```bash
git clone https://github.com/chitrangad/RAG-Assistant.git
cd RAG-Assistant

./install.sh                       # interactive: prompts for the admin password
# or, non-interactive:
#   ADMIN_PASSWORD=your-strong-password ./install.sh
# skip the ~1.1 GB model download:
#   SKIP_MODEL=1 ./install.sh
```

What it does:

1. Checks for Python 3.11+.
2. Creates `.venv` and installs CPU-only PyTorch → llama-cpp-python (prebuilt CPU wheel) → the app.
3. Creates `data/` (SQLite + ChromaDB + uploads + models).
4. Downloads **Qwen3-1.7B** (unless `SKIP_MODEL=1`).
5. Creates `data/.credentials` for the admin user.

Environment overrides: `PYTHON`, `VENV_DIR`, `DATA_DIR`, `ADMIN_USER`, `ADMIN_PASSWORD`, `SKIP_MODEL`, `PORT`.

### Run it

```bash
.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

- Query page: `http://127.0.0.1:8000`
- Admin dashboard: `http://127.0.0.1:8000/admin`
- API docs: `http://127.0.0.1:8000/docs`

### Keep it running (systemd)

Register a **system-level** unit (runs at boot and survives logout — unlike a
`systemctl --user` service, which needs a lingering login session to do the same):

```ini
# /etc/systemd/system/rag-assistant.service
[Unit]
Description=RAG Knowledge Assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=USER                      # ← account that owns data/ (not root)
WorkingDirectory=/home/USER/RAG-Assistant   # ← where data/ lives
ExecStart=/home/USER/RAG-Assistant/.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=3
Environment=LOG_LEVEL=INFO

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rag-assistant
sudo systemctl status rag-assistant
```

> The `User=` account must own the `data/` directory so the service can read
> and write it. Logs: `journalctl -u rag-assistant -f`.

### Manual install (reference)

`install.sh` automates this, but the steps are:

```bash
python3 -m venv .venv
.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch
.venv/bin/pip install "llama-cpp-python>=0.3.35" \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
.venv/bin/pip install .
```

---

## Method B: Docker Compose (pre-built image)

A pre-built image is published to **GitHub Container Registry (GHCR)** at `ghcr.io/chitrangad/rag-assistant` (see [§Image hosting](#image-hosting)). Deploy with no local build:

```bash
git clone https://github.com/chitrangad/RAG-Assistant.git
cd RAG-Assistant

cp .env.example .env     # optional: change PORT, DATA_DIR, network-share path
docker compose up -d     # pulls the pre-built image and starts
```

- Query page: `http://127.0.0.1:8000`
- Logs: `docker compose logs -f`
- Stop: `docker compose down` (data persists in the host data directory)

### Persistent data

`docker-compose.yml` bind-mounts the host data directory into the container:

```yaml
volumes:
  - "${DATA_DIR:-./data}:/app/data"
```

This holds SQLite (`catalog.db`), ChromaDB, uploads, LLM settings, and the answer model (`<DATA_DIR>/models`). Back up by copying that directory.

### Change the port

Set `PORT` in `.env`:

```bash
# .env
PORT=8080
```

The host port changes; the container keeps listening on 8000 internally. `docker compose up -d` re-applies the mapping.

### Network shares / local folders

Two ways to add a network share in **Admin → Add Source**:

1. **Mounted path** — bind-mount the share at the same path you'll enter in the UI, e.g.:

    ```yaml
    volumes:
      - "/mnt/omv-share:/mnt/omv-share:ro"
    ```

2. **Direct SMB (no mount)** — enter a UNC path like `\\server\share\folder` (or `//server/share`, `smb://server/share`) plus credentials when the share is password-protected. The app reaches the share itself via `smbclient` (installed in the image); anonymous/guest shares work with no credentials.

```yaml
volumes:
  - "/mnt/omv-share:/mnt/omv-share:ro"
```

> **GVFS auto-mounts** (`/run/user/UID/gvfs/smb-share:server=…,share=…`) contain a colon that breaks the `host:container` syntax. Mount the share at a clean path on the host first — e.g. `mount -t cifs //server/share /mnt/omv-share` — then bind that clean path here (uncomment the `NETWORK_SHARE_PATH` line in `docker-compose.yml` and set it in `.env`).

### Download the answer LLM (Docker)

The ~1.1 GB Qwen3-1.7B model is **not** baked into the image (keeps it lean). Download it into the host data directory once:

```bash
mkdir -p data/models
curl -L -o data/models/qwen3-1.7b-instruct.Q4_K_M.gguf \
  "https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf"
```

Then in **Admin → AI Answer Engine**, confirm the model path is `./data/models/qwen3-1.7b-instruct.Q4_K_M.gguf` and click **Test Provider**. Until it's present, answers fall back to evidence-only.

### Building the image locally (optional)

```bash
docker build -t ghcr.io/chitrangad/rag-assistant:latest .
docker compose up -d
```

---

## Image hosting

The pre-built image is published to **GitHub Container Registry (GHCR)** — chosen over Docker Hub (anonymous-pull rate limits) and LinuxServer.io (a curated team's registry, not a self-publish target).

- Workflow: `.github/workflows/docker-publish.yml` runs the test suite, builds, and pushes on every push to `main` and on `v*` tags.
- Tags: `latest` (main), `vX.Y.Z` (semver), `sha-<short>` (every build).
- **GHCR visibility:** packages are private by default after the first CI push. For unauthenticated `docker compose up -d` pulls, open the package settings — `github.com/users/chitrangad/packages/container/package/rag-assistant` → **Package settings** → *Change visibility* → **Public**. (Or keep it private and `docker login ghcr.io` with a `read:packages` token.)

---

## Post-deploy: admin account & content

### Admin credentials

`install.sh` creates the admin account automatically. To do it manually (or add users):

```bash
mkdir -p data
.venv/bin/python -c "from src.auth import generate_credential_line; print(generate_credential_line('admin', 'your-strong-password'))" > data/.credentials
chmod 600 data/.credentials
```

Append more `username:hash` lines to add users.

### Ingest content

1. Open **Admin** → **Add Data Source**.
2. Choose **Network Share** — a mounted path (GVFS, UNC, `/Volumes`) or a remote UNC entered as `\\server\share\folder` (reached directly via SMB, no mount required) — or **Local Folder**.
3. Enter the path; click **Test**, then **Scan**. Ingestion runs in the background with live progress.

---

## Configuration reference

Settings default sensibly (see `src/config.py`). Override via environment variables or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Port |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/catalog.db` | Catalog DB |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | Vector store |
| `CHUNK_SIZE` | `1000` | Chunk size (chars) |
| `CHUNK_OVERLAP` | `200` | Chunk overlap (chars) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins (or `*`) |
| `SESSION_TTL_HOURS` | `8` | Admin session cookie lifetime |

Answer-engine settings (provider, model path, context, temperature, external API base URL / key / model, minimum relevance score) are managed at runtime via **Admin → AI Answer Engine** and persisted to `data/llm_settings.json` — no environment variables needed.

---

## Answer Engine (AI)

Two backends, selected in **Admin → AI Answer Engine**:

- **Local (default)** — Qwen3-1.7B via llama-cpp-python. Fully offline; no API key.
- **External** — any OpenAI-compatible `/chat/completions` API (OpenAI, Ollama, LM Studio, vLLM, …).

If no evidence clears the **minimum relevance score**, the assistant replies *"I do not have enough evidence to answer this question"* rather than guessing.

### Configure an external API (optional)

In **Admin → AI Answer Engine**: set **Provider → External API**, enter **Base URL** (e.g. `https://api.openai.com/v1`, `http://localhost:11434/v1`), **API Key** (stored in `data/llm_settings.json`, git-ignored), and **Model**. Click **Save**, then **Test Provider**.

---

## Backup & Restore

Everything that matters lives in the data directory:

```bash
# Backup (stop the service first for a consistent copy)
tar czf rag-backup.tar.gz data/

# Restore
tar xzf rag-backup.tar.gz
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No documents indexed` on query | Ingest content first (see Post-deploy) |
| Answers show only evidence, no natural-language answer | Local model missing — download it (Method A/B model step), or set an external API |
| `Test Provider` fails on local model | Check the model path in Admin → AI Answer Engine and that `llama-cpp-python` installed |
| `Test Provider` fails on external API | Check base URL, API key, and model name; ensure the endpoint is reachable |
| Query returns "insufficient evidence" too often | Lower the minimum relevance score in Admin → AI Answer Engine |
| Admin login fails | Recreate `data/.credentials` with `generate_credential_line` |
| Port in use | Set `PORT` (bare metal: `--port`; Docker: `.env`) |
| Container can't see a share | Bind-mount the share in `docker-compose.yml`, or enter it as a remote UNC (`\\server\share`) so the app connects via SMB — no mount needed (see Network shares) |
| Remote UNC share fails to connect | Ensure `smbclient` is installed on the machine running the app (`apt install smbclient` / included in the Docker image); check credentials and that the share allows SMB access |
