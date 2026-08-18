"""Tests for the document-serving endpoint (clickable citations)."""

from datetime import datetime

import pytest

from src.models.document import Document


async def _seed_doc(file_path: str, file_name: str = "note.txt", file_type: str = ".txt") -> str:
    from src.database import async_session_factory

    async with async_session_factory() as db:
        doc = Document(
            file_name=file_name,
            file_path=file_path,
            file_type=file_type,
            file_size_bytes=100,
            last_modified=datetime.now(),
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc.id


async def _seed_doc_with_source(
    file_path: str, connection_details: dict | None = None
) -> str:
    """Seed a document linked to a data source (as SMB ingestion does)."""
    from src.database import async_session_factory
    from src.models.source import DataSource, SourceDocument

    async with async_session_factory() as db:
        doc = Document(
            file_name="spec.txt",
            file_path=file_path,
            file_type="txt",
            file_size_bytes=100,
            last_modified=datetime.now(),
        )
        db.add(doc)
        await db.flush()
        source = DataSource(
            name="smb-share",
            source_type="network_share",
            connection_details=connection_details or {"path": "//nasrv/docs"},
        )
        db.add(source)
        await db.flush()
        db.add(SourceDocument(source_id=source.id, document_id=doc.id))
        await db.commit()
        return doc.id


def _fake_smb_read(monkeypatch, content: bytes):
    """Monkeypatch helper: serve fake bytes for any smb:// read."""
    import src.ingestion.network_share as ns_mod

    async def fake_read_content(self, file_path: str) -> bytes:  # noqa: ANN001, ARG001
        return content

    monkeypatch.setattr(ns_mod.NetworkShareConnector, "read_content", fake_read_content)



@pytest.mark.asyncio
async def test_serve_text_document(client, setup_db, tmp_path):
    """A stored document is streamed back over HTTP."""
    p = tmp_path / "note.txt"
    p.write_text("hello from the document", encoding="utf-8")
    doc_id = await _seed_doc(str(p))

    r = await client.get(f"/api/documents/{doc_id}")
    assert r.status_code == 200, r.text
    assert "hello from the document" in r.text
    assert "text/plain" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_document_not_found(client, setup_db):
    r = await client.get("/api/documents/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_document_file_missing(client, setup_db, tmp_path):
    """A document whose file no longer exists returns 404, not a crash."""
    doc_id = await _seed_doc(str(tmp_path / "gone.txt"))
    r = await client.get(f"/api/documents/{doc_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_query_returns_document_ids(client, setup_db, monkeypatch):
    """Semantic results carry document_id so the UI can build links."""
    from src.database import async_session_factory

    async with async_session_factory() as db:
        doc = Document(
            file_name="alpha_0.txt",
            file_path="/share/alpha_0.txt",
            file_type="txt",
            file_size_bytes=100,
            last_modified=datetime.now(),
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        doc_id = doc.id

    class _FakeEmbedder:
        async def embed_single(self, text):
            return [0.1] * 8

    class _FakeChroma:
        def count(self):
            return 1

        def query(self, query_embedding, n_results=10, where=None):
            return {
                "ids": [["c1"]],
                "documents": [["evidence"]],
                "metadatas": [
                    [{"document_id": doc_id, "file_name": "alpha_0.txt", "file_type": "txt"}]
                ],
                "distances": [[0.2]],
            }

    monkeypatch.setattr("src.api.chat._get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr("src.api.chat._get_chroma_store", lambda: _FakeChroma())

    r = await client.post(
        "/api/chat/query",
        json={"question": "what mentions the gateway?"},
    )
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert results[0]["document_id"] == doc_id


@pytest.mark.asyncio
async def test_serve_smb_document(client, setup_db, monkeypatch):
    """A document from an SMB source is fetched via smbclient, not the filesystem."""
    doc_id = await _seed_doc_with_source("smb://nasrv/docs/spec.txt")
    _fake_smb_read(monkeypatch, b"content from the smb share")

    r = await client.get(f"/api/documents/{doc_id}")
    assert r.status_code == 200, r.text
    assert r.content == b"content from the smb share"
    assert "text/plain" in r.headers.get("content-type", "")
    assert "inline" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_smb_document_read_failure_is_404(client, setup_db, monkeypatch):
    """A failing smbclient read returns 404, not a crash."""
    doc_id = await _seed_doc_with_source("smb://nasrv/docs/spec.txt")

    import src.ingestion.network_share as ns_mod

    async def fail_read(self, file_path: str) -> bytes:  # noqa: ANN001, ARG001
        raise IOError("smbclient get failed: NT_STATUS_OBJECT_NAME_NOT_FOUND")

    monkeypatch.setattr(ns_mod.NetworkShareConnector, "read_content", fail_read)

    r = await client.get(f"/api/documents/{doc_id}")
    assert r.status_code == 404
    assert "not accessible" in r.json()["detail"]
