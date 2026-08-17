"""Tests for the LLM answer engine — synthesis, FR-009, settings, provider selection."""

import pytest

from src.auth import create_session_token, generate_credential_line
from src.llm.settings import LLMSettings


@pytest.fixture
def admin_token(tmp_path, monkeypatch):
    """Valid admin session token with isolated credential files."""
    creds = tmp_path / ".credentials"
    secret = tmp_path / ".session_secret"
    monkeypatch.setattr("src.auth.CREDENTIALS_FILE", creds)
    monkeypatch.setattr("src.auth.SESSION_SECRET_FILE", secret)
    creds.write_text(generate_credential_line("admin", "testpass"))
    return create_session_token("admin")


def _auth(client, token):
    client.cookies.set("admin_session", token)


class _FakeEmbedder:
    async def embed_single(self, text):
        return [0.1] * 8


class _FakeChroma:
    def __init__(self, score=0.8):
        self.score = score

    def count(self):
        return 1

    def query(self, query_embedding, n_results=10, where=None):
        return {
            "ids": [["c1"]],
            "documents": [["some evidence text about the payment gateway"]],
            "metadatas": [
                [{"document_id": "d1", "file_name": "alpha_0.txt", "file_type": "txt"}]
            ],
            "distances": [[1.0 - self.score]],
        }


class _FakeLLM:
    async def generate(self, prompt, system=None, max_tokens=512, temperature=0.1):
        return "The payment gateway uses Stripe. [1]"


class _BoomLLM:
    async def generate(self, prompt, system=None, max_tokens=512, temperature=0.1):
        raise RuntimeError("provider unavailable")


def _patch_semantic(monkeypatch, chroma, llm=None):
    monkeypatch.setattr("src.api.chat._get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr("src.api.chat._get_chroma_store", lambda: chroma)
    monkeypatch.setattr(
        "src.api.chat.load_settings",
        lambda: LLMSettings(provider="local", min_relevance_score=0.3),
    )
    if llm is not None:
        monkeypatch.setattr("src.api.chat.get_llm", lambda: llm)


@pytest.mark.asyncio
async def test_answer_synthesized_with_citations(client, setup_db, monkeypatch):
    """A strong match produces a natural-language answer + citation list."""
    _patch_semantic(monkeypatch, _FakeChroma(score=0.8), llm=_FakeLLM())

    r = await client.post(
        "/api/chat/query",
        json={"question": "What is the payment gateway about?"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["intent"] == "semantic"
    assert data["answer"] == "The payment gateway uses Stripe. [1]"
    assert data["citations"] == ["alpha_0.txt"]
    assert data["insufficient_evidence"] is False
    assert len(data["results"]) == 1


@pytest.mark.asyncio
async def test_insufficient_evidence_returns_fallback(client, setup_db, monkeypatch):
    """Weak evidence (below threshold) triggers the FR-009 fallback, no LLM call."""
    called = {"n": 0}

    class _SpyLLM:
        async def generate(self, *a, **k):
            called["n"] += 1
            return "should not be used"

    _patch_semantic(monkeypatch, _FakeChroma(score=0.1), llm=_SpyLLM())

    r = await client.post(
        "/api/chat/query",
        json={"question": "Totally unrelated question?"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["insufficient_evidence"] is True
    assert data["answer"] == "I do not have enough evidence to answer this question."
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_provider_failure_degrades_to_evidence_only(client, setup_db, monkeypatch):
    """A provider error must not fail the request — evidence is still returned."""
    _patch_semantic(monkeypatch, _FakeChroma(score=0.8), llm=_BoomLLM())

    r = await client.post(
        "/api/chat/query",
        json={"question": "What is the payment gateway about?"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["answer"] is None
    assert data["insufficient_evidence"] is False
    assert len(data["results"]) == 1


@pytest.mark.asyncio
async def test_admin_llm_settings_get_and_put(client, admin_token, monkeypatch):
    """Settings endpoint reads/writes config and masks the API key."""
    _auth(client, admin_token)
    monkeypatch.setattr(
        "src.api.admin.load_settings", lambda: LLMSettings(provider="local")
    )
    monkeypatch.setattr("src.api.admin.save_settings", lambda s: None)
    monkeypatch.setattr("src.api.admin.reset_llm_cache", lambda: None)

    r = await client.get("/api/admin/llm-settings")
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "local"
    assert r.json()["has_api_key"] is False

    r2 = await client.put(
        "/api/admin/llm-settings",
        json={
            "provider": "external",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-1234567890abcd",
            "model": "my-model",
        },
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["provider"] == "external"
    assert body["model"] == "my-model"
    assert body["has_api_key"] is True
    assert body["api_key_last4"] == "abcd"


@pytest.mark.asyncio
async def test_admin_llm_settings_requires_auth(client):
    """LLM settings endpoints are admin-only."""
    assert (await client.get("/api/admin/llm-settings")).status_code == 401
    assert (await client.put("/api/admin/llm-settings", json={})).status_code == 401


@pytest.mark.asyncio
async def test_admin_llm_test_endpoint(client, admin_token, monkeypatch):
    """POST /api/admin/llm/test reports success from the configured provider."""
    _auth(client, admin_token)
    monkeypatch.setattr(
        "src.api.admin.load_settings", lambda: LLMSettings(provider="local")
    )
    monkeypatch.setattr("src.llm.factory.get_llm", lambda: _FakeLLM())

    r = await client.post("/api/admin/llm/test")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True
    assert data["latency_ms"] >= 0
