"""LLM provider settings, persisted to ``data/llm_settings.json`` (gitignored).

The API key lives here rather than in the environment so the admin panel can
update it at runtime; ``data/`` is already excluded from git.
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from src.config import settings as app_settings


class LLMSettings(BaseModel):
    """Runtime-configurable LLM settings.

    ``provider`` selects the backend; the other fields configure it.
    """

    provider: str = Field("local", pattern="^(local|external)$")

    # Local (llama-cpp-python / GGUF)
    model_path: str = "./data/models/qwen3-1.7b-instruct.Q4_K_M.gguf"
    n_ctx: int = 4096
    n_threads: int = 4
    temperature: float = 0.1
    max_tokens: int = 128
    # Qwen3-style models emit a <think> reasoning block by default. When
    # enabled, the local provider appends /no_think and strips any leftover
    # <think> blocks so only the final answer reaches the user.
    no_think: bool = True

    # External (OpenAI-compatible)
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"

    # Retrieval guardrail (FR-009)
    min_relevance_score: float = 0.3


def _settings_file() -> Path:
    return app_settings.data_dir / "llm_settings.json"


def load_settings() -> LLMSettings:
    """Load settings from disk, falling back to defaults on any error."""
    path = _settings_file()
    if path.exists():
        try:
            return LLMSettings(**json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            # Corrupt/missing file → fall through to defaults
            pass
    return LLMSettings()


def save_settings(settings: LLMSettings) -> None:
    """Persist settings to disk (creating ``data/`` if needed)."""
    app_settings.data_dir.mkdir(parents=True, exist_ok=True)
    _settings_file().write_text(settings.model_dump_json(indent=2), encoding="utf-8")
