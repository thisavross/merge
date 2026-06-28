"""Environment-driven settings for the FastAPI RAG service."""

from bootstrap import ensure_local_packages

ensure_local_packages()

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration (same MySQL as Moodle / phpMyAdmin)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    host: str = Field(default="0.0.0.0", description="Bind address")
    port: int = Field(default=8787, description="Bind port")

    chatbot_secret: str = Field(
        default="", description="Must match Moodle X-Chatbot-Secret if set"
    )

    # ── MySQL (same as Moodle) ────────────────────────────────────────────────
    mysql_host: str = Field(default="127.0.0.1")
    mysql_port: int = Field(default=3306)
    mysql_user: str = Field(default="root")
    mysql_password: str = Field(default="")
    mysql_database: str = Field(default="moodle")
    mysql_prefix: str = Field(default="mdl_")
    mysql_unix_socket: str = Field(default="")

    moodle_dataroot: str = Field(
        default="",
        description="Moodle dataroot path (so service can read dataroot/filedir/<hash>).",
    )

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    ollama_embed_model: str = Field(default="bge-m3")
    ollama_chat_model: str = Field(default="smartbot")
    ollama_vision_model: str = Field(
        default="",
        description="Used when images are attached. Empty = same as chat model.",
    )

    # ── Sinarmas PDF (fallback: local file path if MinIO not used) ────────────
    sinarmas_pdf_path: str = Field(
        default="",
        description=(
            "Absolute path to rawinfosmart.pdf for local-file fallback. "
            "If empty, build_sinarmas_index.py looks next to the script."
        ),
    )

    # ── MinIO (local object storage for PDFs) ─────────────────────────────────
    # Run MinIO locally: minio server ~/minio-data --console-address :9001
    # Web UI: http://127.0.0.1:9001  (login: minioadmin / minioadmin)

    minio_endpoint: str = Field(
        default="minio:9000",
        description="MinIO server host:port (no http://).",
    )

    minio_access_key: str = Field(default="minioadmin")

    minio_secret_key: str = Field(default="minioadmin")

    minio_bucket: str = Field(
        default="smart-knowledge",
        description="Bucket name where PDFs are stored.",
    )

    minio_secure: bool = Field(
        default=False,
        description="Set True only if MinIO runs behind HTTPS. False for local dev.",
    )

    # ── Course file extraction limits ─────────────────────────────────────────
    course_file_max_files: int = Field(default=60)
    course_file_max_bytes: int = Field(default=8 * 1024 * 1024)
    course_file_max_chars_per_file: int = Field(default=40000)
    course_file_max_total_chars: int = Field(default=200000)
    course_pdf_ocr_max_pages: int = Field(default=2)

    # ── Chroma collections (one DB, three collections) ────────────────────────
    moodle_chat_collection: str = Field(default="moodle_chat")
    moodle_coursecontent_collection: str = Field(
        default="moodle_course",
        description=(
            "Learning-only course chunks (filtered at index). "
            "Used for quiz, summarization, and content-grounded tasks."
        ),
        validation_alias=AliasChoices(
            "MOODLE_COURSE_COLLECTION",
            "MOODLE_COURSECONTENT_COLLECTION",
            "MOODLE_QUIZ_COLLECTION",
            "moodle_course_collection",
            "moodle_coursecontent_collection",
            "moodle_quiz_collection",
        ),
    )

    # ── ChromaDB server ──────────────────────────────────────────────────────
    chroma_host: str = Field(
        default="chromadb",
        description="ChromaDB service hostname",
    )

    chroma_port: int = Field(
        default=8000,
        description="ChromaDB service port",
    )

    chroma_db_url: str = Field(
        default="http://chromadb:8000",
        description="ChromaDB HTTP endpoint",
    )

    # ── RAG / chunking ────────────────────────────────────────────────────────
    chunk_size: int = Field(
        default=800, description="Chat collection chunk size (chars)."
    )
    chunk_overlap: int = Field(
        default=100, description="Overlap between chat chunks (chars)."
    )
    max_chunks: int = Field(default=40)
    top_k: int = Field(
        default=5, description="Chat retrieval: chunks per course query."
    )

    quiz_chunk_size: int = Field(
        default=1200, description="Quiz collection chunk size (chars)."
    )
    quiz_chunk_overlap: int = Field(
        default=150, description="Overlap between quiz chunks (chars)."
    )
    quiz_max_chunks: int = Field(
        default=60, description="Max quiz chunks stored per course."
    )
    quiz_top_k: int = Field(
        default=20, description="Quiz retrieval: initial Chroma hits."
    )
    quiz_context_chunks: int = Field(
        default=10,
        description="Max deduplicated quiz chunks concatenated for the LLM prompt.",
    )
    summarize_context_chunks: int = Field(
        default=30,
        description="Max deduplicated chunks for course summarization prompt.",
    )
    ollama_summarize_num_predict: int = Field(
        default=2048,
        description="Max tokens for course summary generation.",
    )
    summarize_max_context_tokens: int = Field(
        default=0,
        description=(
            "Max tokens for summarize excerpts in the user message. "
            "0 = auto (ollama_chat_num_ctx minus reserve)."
        ),
    )
    ollama_quiz_num_predict: int = Field(
        default=12288,
        description="Minimum token budget for quiz JSON (actual = max(this, N * per_question + overhead)).",
    )
    quiz_tokens_per_question: int = Field(
        default=400,
        description="Estimated tokens per question (no explanation field) for num_predict scaling.",
    )

    # ── Generation controls ───────────────────────────────────────────────────
    ollama_chat_temperature: float = Field(
        default=0.0,
        description="0.0 = deterministic. Raise to 0.3 for slightly more natural replies.",
    )
    ollama_chat_top_p: float = Field(default=0.9)
    ollama_chat_num_ctx: int = Field(
        default=8192,
        description=(
            "Ollama context window (num_ctx). Must fit system + user + output. "
            "Match your model (e.g. qwen3:4b often 8192–16384)."
        ),
    )
    ollama_chat_num_predict: int = Field(
        default=4096,
        validation_alias="OLLAMA_CHAT_NUM_PREDICT",
        description="Max tokens generated per reply (lower = faster).",
    )
    sinarmas_top_k: int = Field(
        default=4, description="Chroma hits for Sinarmas knowledge."
    )

    # ── Adaptive-k retrieval (Taguchi et al.) ────────────────────────────────
    adaptive_k_enabled: bool = Field(
        default=True,
        description="Use adaptive-k retrieval: cut at largest similarity gap (argmax sᵢ-sᵢ₊₁).",
    )
    adaptive_k_max_multiplier: int = Field(
        default=3,
        description="Fetch pool = top_k * multiplier candidates before adaptive cut.",
    )
    adaptive_k_min_gap: float = Field(
        default=0.05,
        description="Minimum similarity gap to trigger an adaptive cut. Below this, keep all.",
    )
    cross_course_search_max: int = Field(
        default=12,
        description="Max enrolled courses to scan when course_id is 0 (global chat).",
    )
    global_lazy_index_max: int = Field(
        default=2,
        description="Max courses to index synchronously per global chat request when no hits yet.",
    )

    # ── Redis caches ──────────────────────────────────────────────────────────
    semantic_cache_threshold: float = Field(
        default=0.92,
        ge=0.5,
        le=1.0,
        description="Cosine similarity to reuse a cached reply.",
        validation_alias=AliasChoices(
            "SEMANTIC_CACHE_THRESHOLD", "semantic_cache_threshold"
        ),
    )
    max_history_tokens: int = Field(
        default=1200,  # 2400
        description="Token budget for Redis conversation history in the LLM prompt.",
        validation_alias=AliasChoices("REDIS_MAX_HISTORY_TOKENS", "max_history_tokens"),
    )
    embed_cache_enabled: bool = Field(default=True)
    embed_cache_ttl_seconds: int = Field(default=3600)
    background_course_index: bool = Field(
        default=True,
        description="Re-index stale courses in a background thread; serve stale vectors meanwhile.",
    )


settings = Settings()

