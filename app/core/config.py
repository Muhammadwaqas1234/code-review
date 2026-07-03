"""Application settings.

All configuration is loaded from environment variables (or a local `.env`
file) and validated at startup. Import `get_settings()` rather than reading
`os.environ` directly, so every module sees one consistent, typed view of
the configuration.
"""

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM provider -----------------------------------------------------
    # Which backend to send agent calls to: "openai", "openrouter", or
    # "anthropic".
    llm_provider: str = "openai"

    # Model for reviewers, scoring, and reporting (quality matters).
    smart_model: str = "gpt-4o"
    # Cheaper/faster model for planning and lightweight steps.
    fast_model: str = "gpt-4o-mini"

    # OpenAI (direct). Active provider.
    openai_api_key: str = ""

    # OpenRouter (OpenAI-compatible gateway to many models). Set
    # LLM_PROVIDER=openrouter to use. Note: ':free' models are heavily
    # rate-limited (~8 req/min) — fine for a light test, not for real use.
    openrouter_api_key: str = ""

    # Anthropic (Claude API direct). Set LLM_PROVIDER=anthropic to use.
    anthropic_api_key: str = ""

    @field_validator("openai_api_key", "openrouter_api_key", "anthropic_api_key")
    @classmethod
    def _strip_key(cls, value: str) -> str:
        return value.strip()

    _PROVIDERS = ("openai", "openrouter", "anthropic")

    # --- Embeddings (local, via fastembed) --------------------------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = 64

    # --- Upload limits -----------------------------------------------------
    max_upload_bytes: int = 10 * 1024 * 1024  # roles PDF upload cap
    max_roles_chars: int = 6_000  # roles text passed to agents

    # --- Repository ingestion ----------------------------------------------
    max_source_file_bytes: int = 200_000  # skip generated/huge files
    max_repo_files: int = 500

    # --- RAG parameters -----------------------------------------------------
    chunk_max_chars: int = 4_000  # ~1000 tokens per chunk
    max_chunks: int = 300  # global cap so huge repos stay bounded
    chunks_per_agent: int = 6  # top-k retrieved for each reviewer

    # --- Agent execution -----------------------------------------------------
    # Reviewers run in parallel up to this many at once. Lower it if your
    # provider tier rate-limits bursts of concurrent calls.
    agent_max_workers: int = 5
    agent_timeout_seconds: int = 600
    # Retry transient rate limits (429) with exponential backoff.
    agent_max_retries: int = 4
    agent_retry_base_seconds: float = 5.0
    agent_retry_max_seconds: float = 35.0

    @model_validator(mode="after")
    def _active_provider_has_a_key(self) -> "Settings":
        provider = self.provider
        if provider not in self._PROVIDERS:
            raise ValueError(
                f"LLM_PROVIDER must be one of {', '.join(self._PROVIDERS)}; "
                f"got '{self.llm_provider}'."
            )
        key = self.active_api_key
        if not key:
            env_var = f"{provider.upper()}_API_KEY"
            raise ValueError(
                f"{env_var} is not set. Copy .env.example to .env and add your "
                f"{provider} API key (or change LLM_PROVIDER)."
            )
        return self

    @property
    def active_api_key(self) -> str:
        return {
            "openai": self.openai_api_key,
            "openrouter": self.openrouter_api_key,
            "anthropic": self.anthropic_api_key,
        }[self.provider]

    @property
    def provider(self) -> str:
        return self.llm_provider.strip().lower()


@lru_cache
def get_settings() -> Settings:
    """Return the application settings singleton.

    Cached so the .env file is read once; call `get_settings.cache_clear()`
    in tests to reload with patched environment variables.
    """
    return Settings()
