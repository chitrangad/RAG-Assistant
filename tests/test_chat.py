"""Tests for /api/chat/query — catalog listing intent vs semantic search."""

from datetime import datetime

import pytest

from src.models.document import Document
from src.models.source import DataSource, SourceDocument


async def _seed_docs(folders: dict[str, int]) -> None:
    """Insert documents with folder-style paths into the test DB.

    ``folders`` maps folder name → document count, e.g.
    ``{"/share/project-alpha": 2, "/share/project-beta": 1}``.
    """
    from src.database import async_session_factory

    async with async_session_factory() as db:
        ds = DataSource(
            name="seed-source",
            source_type="network_share",
            connection_details={"path": "/share"},
        )
        db.add(ds)
        await db.flush()
        for folder, count in folders.items():
            for i in range(count):
                doc = Document(
                    file_name=f"{folder.rsplit('/', 1)[-1]}_{i}.txt",
                    file_path=f"{folder}/file_{i}.txt",
                    file_type="txt",
                    file_size_bytes=100,
                    last_modified=datetime.now(),
                )
                db.add(doc)
                await db.flush()
                db.add(SourceDocument(source_id=ds.id, document_id=doc.id))
        await db.commit()


@pytest.mark.asyncio
async def test_listing_query_returns_folders(client, setup_db):
    """'list all documents' returns the folder catalog, not top-k chunks."""
    await _seed_docs({"/share/project-alpha": 2, "/share/project-beta": 1})

    r = await client.post(
        "/api/chat/query",
        json={"question": "List all the project documents", "top_k": 5},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["intent"] == "listing"
    assert data["results"] == []
    folders = {f["folder"]: f["document_count"] for f in data["folders"]}
    assert folders == {"/share/project-alpha": 2, "/share/project-beta": 1}
    # Sorted by count desc
    assert data["folders"][0]["folder"] == "/share/project-alpha"
    # Source name is attached
    assert data["folders"][0]["sources"] == ["seed-source"]


@pytest.mark.asyncio
async def test_listing_query_returns_documents(client, setup_db):
    """'list all documents' also returns a flat document list with link ids."""
    await _seed_docs({"/share/project-alpha": 2, "/share/project-beta": 1})

    r = await client.post(
        "/api/chat/query",
        json={"question": "Show all documents in the repo"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["intent"] == "listing"
    docs = data["documents"]
    assert len(docs) == 3
    names = sorted(d["file_name"] for d in docs)
    assert names == ["project-alpha_0.txt", "project-alpha_1.txt", "project-beta_0.txt"]
    for d in docs:
        assert d["document_id"]
        assert d["folder"] in {"/share/project-alpha", "/share/project-beta"}
        assert d["source"] == "seed-source"


@pytest.mark.asyncio
async def test_listing_query_empty_catalog(client, setup_db):
    """Listing with no documents returns an empty folder list (200, not 404)."""
    r = await client.post(
        "/api/chat/query",
        json={"question": "List all documents in the repository"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["intent"] == "listing"
    assert data["folders"] == []


@pytest.mark.asyncio
async def test_targeted_query_is_not_listing(client, setup_db, monkeypatch):
    """A question with a topic ('about X') must stay on the semantic path."""
    await _seed_docs({"/share/project-alpha": 2})

    # Stub the vector store + embedder so the semantic path runs offline
    class _FakeEmbedder:
        async def embed_single(self, text):
            return [0.1] * 8

    class _FakeChroma:
        def count(self):
            return 1

        def query(self, query_embedding, n_results=10, where=None):
            return {
                "ids": [["c1"]],
                "documents": [["some evidence text"]],
                "metadatas": [
                    [{"document_id": "d1", "file_name": "alpha_0.txt", "file_type": "txt"}]
                ],
                "distances": [[0.2]],
            }

    monkeypatch.setattr("src.api.chat._get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr("src.api.chat._get_chroma_store", lambda: _FakeChroma())

    r = await client.post(
        "/api/chat/query",
        json={"question": "What documents mention the payment gateway?"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["intent"] == "semantic"
    assert data["folders"] == []
    assert len(data["results"]) == 1
    assert data["results"][0]["document_name"] == "alpha_0.txt"


@pytest.mark.asyncio
async def test_listing_with_topic_stays_semantic(client, setup_db, monkeypatch):
    """'list all documents for project X' is a targeted lookup, not a listing."""
    await _seed_docs({"/share/project-alpha": 2})

    class _FakeEmbedder:
        async def embed_single(self, text):
            return [0.1] * 8

    class _FakeChroma:
        def count(self):
            return 1

        def query(self, query_embedding, n_results=10, where=None):
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }

    monkeypatch.setattr("src.api.chat._get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr("src.api.chat._get_chroma_store", lambda: _FakeChroma())

    r = await client.post(
        "/api/chat/query",
        json={"question": "List all documents for the Q1 audit report"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["intent"] == "semantic"
