from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True)

    QDRANT_URL: str = "http://qdrant:6333"
    QDRANT_COLLECTION: str = "docs"
    QDRANT_VECTOR_SIZE: int = 1024
    QDRANT_DISTANCE: str = "Cosine"

    EMBED_URL: str = "http://tei-embed:80"
    RERANK_URL: str = "http://tei-rerank:80"

    OLLAMA_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "rollama3.1:8b-instruct-q4_k_m"
    OLLAMA_NUM_CTX: int = 8192

    INGEST_CHUNK_TOKENS: int = 512
    INGEST_CHUNK_OVERLAP: int = 64
    INGEST_TOP_K: int = 20
    INGEST_TOP_N: int = 5
    INGEST_SYSTEM_PROMPT_RO: str = (
        "Ești un asistent care răspunde exclusiv în limba română, "
        "bazându-te strict pe contextul furnizat. "
        "Dacă răspunsul nu se află în context, spune clar că nu știi."
    )

    UPLOAD_DIR: str = "/uploads"
    MAX_UPLOAD_BYTES: int = 100 * 1024 * 1024


settings = Settings()
