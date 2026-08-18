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


# ── Count / enumeration queries (exact counts & complete lists) ──────


def test_is_enumeration_query():
    """Count/list questions are detected; plain lookups are not."""
    from src.api.chat import _is_enumeration_query

    enumeration = [
        "How many books did Agatha Christie write?",
        "Count the books by Isaac Asimov",
        "List all books written by H.G. Wells",
        "What is the total number of reports?",
        "Enumerate every document in the Q1 folder",
    ]
    non_enumeration = [
        "What did Asimov write about robots?",
        "Who is the author of this book?",
        "Summarize the meeting notes",
    ]
    for q in enumeration:
        assert _is_enumeration_query(q), q
    for q in non_enumeration:
        assert not _is_enumeration_query(q), q


@pytest.mark.asyncio
async def test_enumeration_query_retrieves_exhaustively(client, setup_db, monkeypatch):
    """Count questions fetch far beyond top-k and feed deduped evidence.

    The model gets one compact entry per distinct document so it can state an
    exact count / full list instead of a vague "several books".
    """
    await _seed_docs({"/share/lit": 1})
    captured = {}

    class _FakeEmbedder:
        async def embed_single(self, text):
            return [0.1] * 8

    class _FakeChroma:
        def count(self):
            return 250

        def query(self, query_embedding, n_results=10, where=None):
            captured["n_results"] = n_results
            # 4 chunks from 2 distinct books (author mentions spread across chunks)
            return {
                "ids": [["c1", "c2", "c3", "c4"]],
                "documents": [
                    [
                        "Foundation by Isaac Asimov ...",
                        "Foundation by Isaac Asimov (part 2)",
                        "Pebble in the Sky by Isaac Asimov ...",
                        "Pebble in the Sky by Isaac Asimov (part 2)",
                    ]
                ],
                "metadatas": [
                    [
                        {"document_id": "d1", "file_name": "foundation.txt", "file_type": "txt"},
                        {"document_id": "d1", "file_name": "foundation.txt", "file_type": "txt"},
                        {"document_id": "d2", "file_name": "pebble.txt", "file_type": "txt"},
                        {"document_id": "d2", "file_name": "pebble.txt", "file_type": "txt"},
                    ]
                ],
                "distances": [[0.1, 0.15, 0.2, 0.25]],
            }

    class _FakeLLM:
        async def generate(self, prompt, system, max_tokens, temperature):
            captured["system"] = system
            captured["max_tokens"] = max_tokens
            return "2 books: Foundation, Pebble in the Sky"

    def _spy_enumeration_prompt(question, evidence):
        captured["evidence_docs"] = [e["document_name"] for e in evidence]
        return "ENUM PROMPT"

    monkeypatch.setattr("src.api.chat._get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr("src.api.chat._get_chroma_store", lambda: _FakeChroma())
    monkeypatch.setattr("src.api.chat.get_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        "src.api.chat.build_enumeration_prompt", _spy_enumeration_prompt
    )

    r = await client.post(
        "/api/chat/query",
        json={"question": "How many books did Isaac Asimov write? List their titles"},
    )
    assert r.status_code == 200, r.text
    data = r.json()

    # 1) Broad retrieval: all 250 chunks requested (capped at the retrieval K).
    assert captured["n_results"] == 200  # min(chunk_count=250, cap=200)
    assert data["intent"] == "semantic"
    # 2) Evidence deduped per document: 2 distinct books, not 4 chunks.
    assert sorted(captured["evidence_docs"]) == ["foundation.txt", "pebble.txt"]
    # 3) Enumeration prompt + headroom for long lists.
    assert data["answer"] == "2 books: Foundation, Pebble in the Sky"
    assert captured["max_tokens"] >= 512
    # 4) Citations are the distinct documents.
    assert sorted(data["citations"]) == ["foundation.txt", "pebble.txt"]
