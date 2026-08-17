"""External LLM provider for any OpenAI-compatible chat-completions API."""

from src.llm.base import BaseLLMProvider
from src.logging_config import get_logger

logger = get_logger(__name__)


class ExternalLLMProvider(BaseLLMProvider):
    """Call a remote OpenAI-compatible endpoint (OpenAI, Anthropic proxy,
    Ollama, LM Studio, vLLM, etc.).

    Everything speaks the ``/chat/completions`` protocol with Bearer auth, so
    one adapter covers the common providers.
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or "gpt-4o-mini"

    async def generate(self, prompt, system=None, max_tokens=512, temperature=0.1):
        import httpx

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]["content"]
