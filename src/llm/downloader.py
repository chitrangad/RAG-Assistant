"""Answer-LLM downloader for the admin panel.

Downloads the default model (Qwen3-1.7B GGUF) to the configured model path so
the ~1.1 GB file never has to ship with the repo or the container image.
Runs in a background thread and exposes in-process progress for polling.
"""

import threading
import urllib.request
from pathlib import Path

from src.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL_URL = (
    "https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/"
    "Qwen3-1.7B-Q4_K_M.gguf"
)


class ModelDownloader:
    """Serialised background downloader with a simple progress state dict."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = {
            "status": "idle",  # idle | downloading | done | error
            "downloaded": 0,
            "total": 0,
            "path": "",
            "error": "",
        }

    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, dest_path: str, url: str = DEFAULT_MODEL_URL) -> dict:
        """Start a download (no-op if one is already running)."""
        with self._lock:
            if self._state["status"] == "downloading":
                return dict(self._state)
            self._state = {
                "status": "downloading",
                "downloaded": 0,
                "total": 0,
                "path": str(dest_path),
                "error": "",
            }
        thread = threading.Thread(
            target=self._run, args=(url, str(dest_path)), daemon=True
        )
        thread.start()
        return self.state()

    def _run(self, url: str, dest: str) -> None:
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest_path.with_name(dest_path.name + ".part")
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "rag-assistant/1.0"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                with self._lock:
                    self._state["total"] = total
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        with self._lock:
                            self._state["downloaded"] += len(chunk)
            tmp.replace(dest_path)
            with self._lock:
                self._state["status"] = "done"
            logger.info("model_download_complete", path=dest)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            with self._lock:
                self._state["status"] = "error"
                self._state["error"] = str(exc)
            logger.error("model_download_failed", path=dest, error=str(exc))
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


_downloader = ModelDownloader()


def get_downloader() -> ModelDownloader:
    return _downloader
