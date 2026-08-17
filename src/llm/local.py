"""Local LLM provider backed by llama-cpp-python (GGUF, CPU)."""

import asyncio
import re

from src.llm.base import BaseLLMProvider
from src.logging_config import get_logger

logger = get_logger(__name__)

# Qwen3-style models wrap their answer in a <think> reasoning block.
# Strip any such block so only the final answer is shown.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class LocalLLMProvider(BaseLLMProvider):
    """Run a GGUF model in-process via llama-cpp-python.

    The model is loaded lazily on first use to avoid paying the model load
    cost at import time. Generation runs in a thread pool because llama-cpp's
    API is blocking.
    """

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 4096,
        n_threads: int = 4,
        no_think: bool = True,
    ):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.no_think = no_think
        self._llm = None
        # llama.cpp is NOT thread-safe: concurrent create_chat_completion()
        # calls on one instance can segfault. Serialize generation across the
        # whole process (the provider is a singleton) with an async lock.
        self._lock = asyncio.Lock()

    def _load(self):
        if self._llm is None:
            from llama_cpp import Llama

            logger.info(
                "loading_local_llm",
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
            )
            self._llm = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                verbose=False,
            )
            logger.info("local_llm_loaded", model_path=self.model_path)
        return self._llm

    def _generate_sync(self, prompt, system, max_tokens, temperature):
        llm = self._load()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        user_content = prompt
        if self.no_think:
            user_content += " /no_think"
        messages.append({"role": "user", "content": user_content})
        out = llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.9,
        )
        content = out["choices"][0]["message"]["content"]
        if self.no_think:
            content = _THINK_BLOCK.sub("", content).strip()
        return content

    async def generate(self, prompt, system=None, max_tokens=512, temperature=0.1):
        loop = asyncio.get_running_loop()
        # Serialize: only one llama.cpp generation may run at a time.
        async with self._lock:
            return await loop.run_in_executor(
                None,
                lambda: self._generate_sync(prompt, system, max_tokens, temperature),
            )
