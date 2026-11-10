from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRIBUNAL_",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Path(".tribunal")

    sandbox_image: str = "python:3.12-slim"
    sandbox_require_digest: bool = False
    sandbox_timeout_s: int = 120
    sandbox_memory: str = "512m"
    sandbox_cpus: float = 1.0
    sandbox_pids_limit: int = 256
    sandbox_max_output_bytes: int = 65536

    llm_model: str = "claude-sonnet-5-5"
    llm_max_tokens: int = 4096
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TRIBUNAL_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )

    ledger_enabled: bool = True
    allowed_repo_roots: list[Path] = Field(default_factory=list)

    api_token: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tribunal.sqlite3"

    @property
    def key_path(self) -> Path:
        return self.data_dir / "signing_key.pem"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
