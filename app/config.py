from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Storage ---
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/youtube_ai_search"

    # --- LLM (used for the final RAG answer) ---
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"

    # --- Embeddings (local, free, no API key needed) ---
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
    EMBEDDING_BATCH_SIZE: int = 32

    # --- Whisper fallback (used only if YouTube has no transcript) ---
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"

    # --- Chunking (semantic chunks, sentence-boundary aware) ---
    CHUNK_MIN_CHARS: int = 300
    CHUNK_MAX_CHARS: int = 700
    CHUNK_MIN_SECONDS: float = 20.0
    CHUNK_MAX_SECONDS: float = 45.0

    # --- Search ---
    DEFAULT_TOP_K: int = 5
    FIND_ALL_TOP_K: int = 30
    FIND_ALL_DEDUP_WINDOW_SECONDS: float = 8.0

    # --- Background worker ---
    WORKER_POLL_INTERVAL_SECONDS: float = 2.0
    WORKER_MAX_ATTEMPTS: int = 2

    class Config:
        env_file = ".env"


settings = Settings()
