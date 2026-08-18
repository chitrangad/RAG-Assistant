"""Tests for the admin API — source updates and ingestion run progress."""

import pytest

from src.auth import create_session_token, generate_credential_line


@pytest.fixture
def admin_token(tmp_path, monkeypatch):
    """Return a valid admin session token with isolated credential files.

    Monkeypatches the auth module's credential/secret file paths to temp files
    so tests never touch the real ``data/.credentials``.
    """
    creds = tmp_path / ".credentials"
    secret = tmp_path / ".session_secret"
    monkeypatch.setattr("src.auth.CREDENTIALS_FILE", creds)
    monkeypatch.setattr("src.auth.SESSION_SECRET_FILE", secret)
    creds.write_text(generate_credential_line("admin", "testpass"))
    return create_session_token("admin")


def _auth(client, token):
    client.cookies.set("admin_session", token)


# ──────────────────────────────────────────────
# Source update persistence (regression: JSON mutation bug)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_source_path_persists(client, admin_token):
    """Editing a source's path must persist (was silently ignored)."""
    _auth(client, admin_token)

    r = await client.post(
        "/api/admin/sources",
        json={
            "name": "test-share",
            "source_type": "network_share",
            "path": "/old/path",
            "scan_mode": "incremental",
        },
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["path"] == "/old/path"

    # Update the path
    r2 = await client.patch(
        f"/api/admin/sources/{sid}",
        json={"path": "/new/path"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["path"] == "/new/path"

    # Fetch again — must come from the DB, not a stale response
    r3 = await client.get(f"/api/admin/sources/{sid}")
    assert r3.status_code == 200
    assert r3.json()["path"] == "/new/path"

    # Cleanup
    await client.delete(f"/api/admin/sources/{sid}")


@pytest.mark.asyncio
async def test_update_source_keeps_other_fields(client, admin_token):
    """Updating the path must not wipe other connection details."""
    _auth(client, admin_token)

    r = await client.post(
        "/api/admin/sources",
        json={
            "name": "auth-share",
            "source_type": "network_share",
            "path": "/share/root",
            "network_user": "svc_user",
            "network_pass": "secret",
            "network_domain": "CORP",
        },
    )
    sid = r.json()["id"]

    r2 = await client.patch(f"/api/admin/sources/{sid}", json={"path": "/share/other"})
    assert r2.status_code == 200
    data = r2.json()
    assert data["path"] == "/share/other"
    assert data["network_user"] == "svc_user"
    assert data["has_credentials"] is True

    await client.delete(f"/api/admin/sources/{sid}")


# ──────────────────────────────────────────────
# Ingestion run progress
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_run_reports_progress_fields(client, admin_token, setup_db):
    """The run detail endpoint exposes live progress counters."""
    _auth(client, admin_token)

    from src.database import async_session_factory
    from src.ingestion.registry import DocumentRegistry
    from src.models.ingestion import IngestionRun
    from sqlalchemy import select

    async with async_session_factory() as db:
        registry = DocumentRegistry(db)
        run = await registry.create_ingestion_run("manual")
        run.documents_discovered = 10
        run.documents_processed = 4
        run.documents_indexed = 3
        run.status = "running"
        await db.commit()
        run_id = run.id

    r = await client.get(f"/api/admin/runs/{run_id}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == run_id
    assert data["status"] == "running"
    assert data["documents_discovered"] == 10
    assert data["documents_processed"] == 4
    assert data["documents_indexed"] == 3
    assert data["source_id"] == "manual"


@pytest.mark.asyncio
async def test_get_run_not_found(client, admin_token):
    _auth(client, admin_token)
    r = await client.get("/api/admin/runs/nonexistent-id")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_scan_bad_path_fails_fast(client, admin_token):
    """Scanning a source with an inaccessible path returns 400 immediately."""
    _auth(client, admin_token)

    r = await client.post(
        "/api/admin/sources",
        json={
            "name": "bad-path-src",
            "source_type": "network_share",
            "path": "/nonexistent/definitely/missing",
        },
    )
    sid = r.json()["id"]

    r2 = await client.post(f"/api/admin/sources/{sid}/scan")
    assert r2.status_code == 400
    assert "does not exist" in r2.json()["detail"]

    await client.delete(f"/api/admin/sources/{sid}")


@pytest.mark.asyncio
async def test_scan_rejects_duplicate_running_scan(client, admin_token, setup_db):
    """A second scan on a source with an in-flight run is rejected (409).

    This is the guard that prevents two rapid Scan clicks from starting two
    concurrent ingestions of the same files.
    """
    _auth(client, admin_token)

    r = await client.post(
        "/api/admin/sources",
        json={
            "name": "dup-scan-src",
            "source_type": "network_share",
            "path": "/nonexistent/definitely/missing",
        },
    )
    sid = r.json()["id"]

    # Seed an in-flight (running) run for this source, as a hung scan leaves.
    from src.database import async_session_factory
    from src.ingestion.registry import DocumentRegistry

    async with async_session_factory() as db:
        registry = DocumentRegistry(db)
        run = await registry.create_ingestion_run(sid)
        run.status = "running"
        await db.commit()
        run_id = run.id

    r2 = await client.post(f"/api/admin/sources/{sid}/scan")
    assert r2.status_code == 409, r2.text
    data = r2.json()
    assert data["run_id"] == run_id
    assert "already running" in data["detail"]

    await client.delete(f"/api/admin/sources/{sid}")


@pytest.mark.asyncio
async def test_delete_running_run_cancels_and_removes(client, admin_token, setup_db, monkeypatch):
    """A hung/running run can be deleted via the Del action."""
    _auth(client, admin_token)

    r = await client.post(
        "/api/admin/sources",
        json={
            "name": "del-run-src",
            "source_type": "network_share",
            "path": "/share/root",
        },
    )
    sid = r.json()["id"]

    from src.database import async_session_factory
    from src.ingestion.registry import DocumentRegistry
    from src.models.ingestion import IngestionRun
    from sqlalchemy import select

    async with async_session_factory() as db:
        registry = DocumentRegistry(db)
        run = await registry.create_ingestion_run(sid)
        await db.commit()
        run_id = run.id

    # Avoid touching a real ChromaDB collection during the delete.
    class _FakeChroma:
        def delete_by_source(self, source_id):
            pass

    monkeypatch.setattr("src.api.admin._get_chroma", lambda: _FakeChroma())

    r2 = await client.delete(f"/api/admin/runs/{run_id}")
    assert r2.status_code == 200, r2.text

    async with async_session_factory() as db:
        gone = (
            await db.execute(select(IngestionRun).where(IngestionRun.id == run_id))
        ).scalar_one_or_none()
        assert gone is None

    await client.delete(f"/api/admin/sources/{sid}")


@pytest.mark.asyncio
async def test_list_source_documents(client, admin_token):
    """GET /api/admin/sources/{id}/documents lists files for that source."""
    _auth(client, admin_token)

    r = await client.post(
        "/api/admin/sources",
        json={
            "name": "files-src",
            "source_type": "network_share",
            "path": "/share/root",
        },
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    # Register two documents linked to this source
    from src.database import async_session_factory
    from src.ingestion.registry import DocumentRegistry
    from src.ingestion.connector import DocumentCandidate
    from datetime import datetime

    async with async_session_factory() as db:
        reg = DocumentRegistry(db)
        for i in range(2):
            cand = DocumentCandidate(
                file_name=f"file{i}.txt",
                file_path=f"/share/root/file{i}.txt",
                file_type="txt",
                file_size_bytes=100,
                last_modified=datetime.now(),
            )
            await reg.register_document(cand, source_id=sid)
        await db.commit()

    r2 = await client.get(f"/api/admin/sources/{sid}/documents")
    assert r2.status_code == 200, r2.text
    docs = r2.json()
    assert len(docs) == 2
    names = sorted(d["file_name"] for d in docs)
    assert names == ["file0.txt", "file1.txt"]
    assert all(d["file_type"] == "txt" for d in docs)
    assert all("/share/root/" in (d["file_path"] or "") for d in docs)

    # Unknown source → 404
    r3 = await client.get("/api/admin/sources/does-not-exist/documents")
    assert r3.status_code == 404

    await client.delete(f"/api/admin/sources/{sid}")


@pytest.mark.asyncio
async def test_list_source_documents_requires_auth(client):
    """Per-source file listing is admin-only."""
    r = await client.get("/api/admin/sources/any-id/documents")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_scan_requires_auth(client):
    """Admin endpoints reject unauthenticated requests."""
    r = await client.get("/api/admin/sources")
    assert r.status_code == 401


# ──────────────────────────────────────────────
# Orchestrator live-progress path (run_id)
# ──────────────────────────────────────────────


class _FakeEmbedder:
    """Stub embedding provider — no sentence-transformers model load."""

    async def embed(self, texts):
        return [[0.1] * 8 for _ in texts]

    async def embed_single(self, text):
        return [0.1] * 8

    @property
    def dimension(self):
        return 8


class _FakeChroma:
    """Stub vector store — records adds/deletes, no ChromaDB dependency."""

    def __init__(self):
        self.added = []
        self.deleted = []

    def add_chunks(self, ids, embeddings, documents, metadatas):
        self.added.extend(documents)

    def delete_by_document(self, document_id):
        self.deleted.append(document_id)

    def query(self, query_embedding, n_results=10, where=None):
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    def count(self):
        return len(self.added)


class _FakeConnector:
    """Stub source connector with three small text documents."""

    async def validate(self):
        return True

    async def discover_documents(self):
        from datetime import datetime
        from src.ingestion.connector import DocumentCandidate

        return [
            DocumentCandidate(
                file_name=f"doc{i}.txt",
                file_path=f"/virtual/doc{i}.txt",
                file_type="txt",
                file_size_bytes=100,
                last_modified=datetime.now(),
            )
            for i in range(3)
        ]

    async def read_content(self, file_path):
        return b"Project: Demo Project. Implements REQ-100 and CR-2001."


@pytest.mark.asyncio
async def test_orchestrator_writes_progress_to_existing_run(setup_db):
    """ingest_from_connector with run_id updates the pre-created run.

    Regression guard: the run_id code path uses the IngestionRun model, which
    was once missing an import — this test would have caught that NameError.
    """
    from src.database import async_session_factory
    from src.ingestion.registry import DocumentRegistry
    from src.ingestion.orchestrator import IngestionOrchestrator

    # Pre-create a run (as scan_source does), so we can verify progress flows into it
    async with async_session_factory() as db:
        registry = DocumentRegistry(db)
        run = await registry.create_ingestion_run("manual")
        await db.commit()
        run_id = run.id

    orch = IngestionOrchestrator(embedder=_FakeEmbedder(), chroma_store=_FakeChroma())
    result = await orch.ingest_from_connector(
        _FakeConnector(), source_id="manual", run_id=run_id
    )

    assert result["status"] == "completed"
    assert result["documents_discovered"] == 3
    assert result["documents_processed"] == 3
    assert result["documents_indexed"] == 3

    # Verify the pre-created run got the final progress + completion state
    from src.models.ingestion import IngestionRun
    from sqlalchemy import select

    async with async_session_factory() as db:
        loaded = (
            await db.execute(select(IngestionRun).where(IngestionRun.id == run_id))
        ).scalar_one()
        assert loaded.status == "completed"
        assert loaded.documents_discovered == 3
        assert loaded.documents_processed == 3
        assert loaded.documents_indexed == 3


@pytest.mark.asyncio
async def test_orchestrator_creates_run_without_run_id(setup_db):
    """Without run_id, ingest_from_connector still creates its own run."""
    from src.database import async_session_factory
    from src.ingestion.orchestrator import IngestionOrchestrator

    orch = IngestionOrchestrator(embedder=_FakeEmbedder(), chroma_store=_FakeChroma())
    result = await orch.ingest_from_connector(_FakeConnector(), source_id="manual")
    assert result["status"] == "completed"
    assert result["documents_indexed"] == 3

    from src.models.ingestion import IngestionRun
    from sqlalchemy import select

    async with async_session_factory() as db:
        runs = (await db.execute(select(IngestionRun))).scalars().all()
        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].documents_indexed == 3


# ──────────────────────────────────────────────
# Incremental re-scan merge (no duplicate chunks)
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rescan_skips_unchanged_documents(setup_db):
    """Re-scanning identical files merges: unchanged docs are skipped."""
    from src.database import async_session_factory
    from src.ingestion.orchestrator import IngestionOrchestrator
    from src.models.document import DocumentChunk
    from sqlalchemy import select, func

    chroma = _FakeChroma()
    orch = IngestionOrchestrator(embedder=_FakeEmbedder(), chroma_store=chroma)

    r1 = await orch.ingest_from_connector(_FakeConnector(), source_id="manual")
    assert r1["documents_indexed"] == 3
    assert len(chroma.added) == 3

    r2 = await orch.ingest_from_connector(_FakeConnector(), source_id="manual")
    assert r2["documents_indexed"] == 3
    # Unchanged docs are skipped — no new chunks added, nothing deleted.
    assert len(chroma.added) == 3
    assert chroma.deleted == []

    async with async_session_factory() as db:
        count = (
            await db.execute(select(func.count()).select_from(DocumentChunk))
        ).scalar()
        assert count == 3


@pytest.mark.asyncio
async def test_rescan_replaces_changed_documents(setup_db):
    """Changed documents are re-indexed in place (chunks replaced, not duplicated)."""
    from src.database import async_session_factory
    from src.ingestion.orchestrator import IngestionOrchestrator
    from src.models.document import DocumentChunk
    from sqlalchemy import select, func

    class _ChangingConnector(_FakeConnector):
        def __init__(self):
            self.content = b"Version one."

        async def read_content(self, file_path):
            return self.content

    connector = _ChangingConnector()
    chroma = _FakeChroma()
    orch = IngestionOrchestrator(embedder=_FakeEmbedder(), chroma_store=chroma)

    r1 = await orch.ingest_from_connector(connector, source_id="manual")
    assert len(chroma.added) == 3
    assert chroma.deleted == []

    connector.content = b"Version two, now changed."
    r2 = await orch.ingest_from_connector(connector, source_id="manual")
    # All three changed → old chunks deleted, new chunks added (net: no growth).
    assert len(chroma.added) == 6
    assert len(chroma.deleted) == 3

    async with async_session_factory() as db:
        count = (
            await db.execute(select(func.count()).select_from(DocumentChunk))
        ).scalar()
        assert count == 3
