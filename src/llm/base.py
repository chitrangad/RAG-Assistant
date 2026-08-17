"""Abstract interface for LLM providers."""

from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    """A text-generation backend used to synthesize grounded answers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.1,
    ) -> str:
        """Generate a completion for ``prompt``.

        Returns the generated text. Raises an exception on failure so callers
        can degrade gracefully (e.g. fall back to evidence-only responses).
        """
        ...
