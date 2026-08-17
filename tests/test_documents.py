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
