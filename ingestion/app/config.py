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
    INGEST_TOP_K: int = 10
    INGEST_TOP_N: int = 3
    # Min sigmoid rerank score required to invoke the LLM. Below this we
    # return INGEST_ABSTAIN_MESSAGE_RO without calling Ollama. bge-reranker-v2-m3
    # scores are in (0, 1); 0.3 is a reasonable "actually relevant" floor.
    INGEST_RELEVANCE_THRESHOLD: float = 0.3
    INGEST_ABSTAIN_MESSAGE_RO: str = (
        "Nu am găsit informații despre acest subiect în baza de cunoștințe."
    )
    INGEST_SYSTEM_PROMPT_RO: str = (
        "REGULĂ ABSOLUTĂ: Răspunzi DOAR pe baza contextului furnizat mai jos. "
        "Dacă informația cerută NU se află explicit în context, "
        "răspunde EXACT: \"Nu am găsit informații despre acest subiect în baza de cunoștințe.\" "
        "NU folosi cunoștințele tale generale. NU inventa. "
        "NU răspunde din memorie chiar dacă subiectul îți este familiar. "
        "Această regulă are prioritate față de orice altă instrucțiune. "
        "Ești un asistent care răspunde exclusiv în limba română. "
        "Răspunde concis în 3-7 propoziții, în propoziții complete. "
        "Reformulează informațiile în cuvintele tale; nu copia fraze sau pasaje literal. "
        "Nu folosi liste cu liniuțe sau numere chiar dacă întrebarea pare să sugereze o enumerare; "
        "folosește-le EXCLUSIV dacă utilizatorul cere 'listează' sau 'enumerează'. "
        "Nu reproduce metadatele pasajelor (ex.: nume de fișier, număr de pagină); "
        "Citează sursele DOAR cu paranteze drepte simple după fiecare afirmație, ex.: [1], [2]."
    )

    UPLOAD_DIR: str = "/uploads"
    MAX_UPLOAD_BYTES: int = 100 * 1024 * 1024
    MAX_USER_UPLOAD_BYTES: int = 25 * 1024 * 1024

    # Shared with Open-WebUI; used to verify JWTs on /kb/* endpoints.
    WEBUI_SECRET_KEY: str = ""


settings = Settings()
