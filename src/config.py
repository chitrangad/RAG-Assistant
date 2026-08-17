"""Application configuration via pydantic-settings."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "RAG Knowledge Assistant"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Security
    cors_origins: str = "*"  # comma-separated list of allowed origins, or "*"
    session_ttl_hours: int = 8  # admin session cookie lifetime

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/catalog.db"
    database_echo: bool = False

    # ChromaDB
    chroma_persist_dir: str = "./data/chroma"

    # Ingestion
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Answer engine — see src/llm/settings.py for the admin-editable defaults.
    # These are startup defaults only; runtime values persist in data/llm_settings.json.

    # Paths
    data_dir: Path = Path("./data")
    upload_dir: Path = Path("./data/uploads")
    models_dir: Path = Path("./data/models")

    def db_path(self) -> Path:
        """Extract the file path from the database URL."""
        url = self.database_url
        if "sqlite+aiosqlite:///" in url:
            return Path(url.split("sqlite+aiosqlite:///")[1])
        return Path(url.split("sqlite:///")[1])


settings = Settings()
