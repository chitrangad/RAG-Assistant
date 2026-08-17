"""Resolve the configured LLM provider, caching the instance."""

from src.llm.base import BaseLLMProvider
from src.llm.settings import load_settings

_provider = None
_provider_key = None


def _provider_cache_key(s) -> tuple:
    return (
        s.provider,
        s.model_path,
        s.n_ctx,
        s.n_threads,
        s.base_url,
        s.api_key,
        s.model,
    )


def get_llm() -> BaseLLMProvider:
    """Return the provider for the current settings, caching by config.

    Importing provider modules is deferred so the heavy llama-cpp / httpx
    imports only happen when that provider is actually selected.
    """
    global _provider, _provider_key

    s = load_settings()
    key = _provider_cache_key(s)
    if _provider is not None and _provider_key == key:
        return _provider

    if s.provider == "external":
        from src.llm.external import ExternalLLMProvider

        _provider = ExternalLLMProvider(base_url=s.base_url, api_key=s.api_key, model=s.model)
    else:
        from src.llm.local import LocalLLMProvider

        _provider = LocalLLMProvider(
            model_path=s.model_path,
            n_ctx=s.n_ctx,
            n_threads=s.n_threads,
            no_think=s.no_think,
        )

    _provider_key = key
    return _provider


def reset_llm_cache() -> None:
    """Drop the cached provider so the next call re-reads settings."""
    global _provider, _provider_key
    _provider = None
    _provider_key = None
