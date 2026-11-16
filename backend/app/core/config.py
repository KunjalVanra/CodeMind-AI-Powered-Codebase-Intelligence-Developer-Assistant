
from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    APP_NAME: str = "CodeMind"
    DEBUG: bool = False

    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str
    MYSQL_DATABASE: str = "codemind_db"

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5181,http://127.0.0.1:5181"
    )

    CODEMIND_STORAGE_DIR: Path = Path.home() / "CodeMind" / "storage"
    MAX_CLONE_SIZE_BYTES: int = 500 * 1024 * 1024
    MAX_CLONE_FILE_COUNT: int = 100_000
    MAX_SCAN_FILE_SIZE_BYTES: int = 5 * 1024 * 1024
    MAX_SCAN_FILE_COUNT: int = 100_000
    MAX_SCAN_DIRECTORY_DEPTH: int = 30
    MAX_CODE_CHUNK_CHARS: int = 12_000
    MAX_CODE_CHUNKS_PER_REPOSITORY: int = 20_000
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_BATCH_SIZE: int = 32
    VECTOR_INDEX_BATCH_SIZE: int = 32
    VECTOR_DB_DIR: Path = Path.home() / "CodeMind" / "vectors"
    VECTOR_COLLECTION_NAME: str = "codemind_code_chunks"
    GROQ_API_KEY: SecretStr | None = None
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    MAX_RAG_CONTEXT_CHARS: int = 12_000

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
