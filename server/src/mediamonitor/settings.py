"""Настройки сервера. Всё — из переменных окружения (или файла `.env` рядом с запуском).

Ключи площадок и нейросети хранятся только здесь, в `SecretStr`: в логи, ответы API
и страницу стенда они не попадают (НТ-15). Полный список — `server/.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mediamonitor import __version__

DEFAULT_DATABASE_URL = "postgresql+psycopg://mediamonitor@localhost:5432/mediamonitor"
DEFAULT_LLM_MODEL = "hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:Q6_K"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- общее
    app_version: str = __version__
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = DEFAULT_DATABASE_URL
    # Адрес интерфейса: из него строится ссылка-ключ рабочего места (Р8).
    public_app_url: str = "http://localhost:5173/"
    # Откуда разрешены запросы браузера: сайт и расширение (chrome-extension://<id>).
    cors_origins: str = "http://localhost:5173"

    # ---------------------------------------------------------------- данные площадок
    # fixtures — записанные примеры (разработка, тесты); live — настоящие площадки.
    data_source: Literal["fixtures", "live"] = "fixtures"
    # Сбои для FixtureAdapter: «max:unavailable,ok:slow». Режимы — adapters/fixture.py.
    fixture_failures: str = ""
    # Пауза между шагами хода в FixtureAdapter, мс: чтобы ход поиска был виден.
    fixture_step_delay_ms: int = Field(default=120, ge=0, le=10_000)
    # Сдвинуть даты записанных примеров к «сейчас» (их «сегодня» — 19.10.2026), чтобы
    # период по умолчанию «7 дней» находил их и через неделю. Только для разработки.
    fixture_shift_to_now: bool = False
    vk_service_token: SecretStr | None = None
    vk_api_version: str = "5.199"
    vk_monthly_quota: int = 10_000
    maxstat_token: SecretStr | None = None
    maxstat_credits: int = 1_000
    # Сколько ждём одну площадку целиком, секунд; дольше — статус «не уложилась во время».
    platform_timeout_sec: float = Field(default=90.0, gt=0)

    # ---------------------------------------------------------------- нейросеть (Р5–Р6)
    # Адрес Ollama на другом компьютере, например http://10.0.0.5:11434.
    # Не задан — смысловая проверка недоступна, спорные получают «не проверено ИИ».
    ollama_url: str | None = None
    # Q6_K: почти как Q8_0 по качеству и с запасом видеопамяти на RTX 5080 (gpu-node/README.md).
    llm_model: str = DEFAULT_LLM_MODEL
    # То же имя модели, как его называют gpu-node и mm_matching; LLM_MODEL важнее.
    ollama_model: str | None = None
    llm_model_label: str = "GigaChat 3.1 Lightning, локально (Ollama)"
    llm_api_key: SecretStr | None = None
    llm_timeout_sec: float = Field(default=60.0, gt=0)
    llm_concurrency: int = Field(default=1, ge=1, le=16)
    llm_batch_size: int = Field(default=8, ge=1, le=32)
    llm_warmup: bool = True
    # Как воронка обращается к нейросети: ollama — /api/chat, openai — /v1/chat/completions.
    llm_api: Literal["ollama", "openai"] = "ollama"
    # Сколько спорных публикаций проверяет нейросеть за один поиск и сколько секунд всего (НТ-6).
    llm_max_gray: int = Field(default=60, ge=0)
    llm_deadline_sec: float = Field(default=300.0, gt=0)
    # Контекст запросов к Ollama — как OLLAMA_CONTEXT_LENGTH на компьютере с видеокартой.
    llm_num_ctx: int = 8192

    # ---------------------------------------------------------------- отбор
    # Фабрика воронки отбора «модуль:функция». Воронка «Э-Отбор» — mediamonitor.matcher.funnel,
    # простая заглушка без моделей — mediamonitor.matcher.simple.
    matcher: str = "mediamonitor.matcher.funnel:create_matcher"
    # Сколько постов отбирается за один шаг: результаты уходят в поток после каждого шага (НТ-2).
    match_batch_size: int = Field(default=16, ge=1, le=512)
    # Загрузить модели воронки при старте, а не при первом поиске (НТ-18).
    matcher_warmup: bool = True

    # ---------------------------------------------------------------- модель смысла (эмбеддинги)
    embedding_model: str = "sergeyzh/BERTA"
    # Версия векторов в кэше: поменяйте, если поменялся способ подсчёта, — старые не используются.
    embedding_version: str = "1"
    # Сервис эмбеддингов на компьютере с видеокартой (gpu-node). Не задан — модель на CPU сервера.
    embeddings_url: str | None = None
    embeddings_token: SecretStr | None = None
    embeddings_timeout_sec: float = Field(default=30.0, gt=0)
    embeddings_batch_size: int = Field(default=256, ge=1, le=256)
    # После сбоя сервиса столько секунд считаем на CPU, потом пробуем сервис снова.
    embeddings_retry_after_sec: float = Field(default=60.0, ge=0)

    # ---------------------------------------------------------------- проверка текста на ИИ
    # auto — сервис детектора на компьютере с видеокартой, если задан AI_DETECT_URL; без него
    # при разработке на записанных примерах (DATA_SOURCE=fixtures, ENVIRONMENT не production) —
    # демо-оценка из хеша текста, иначе выключено («проверка недоступна»): ложная метка — это
    # обвинение. Демо на стенде — только явно: AI_DETECT_PROVIDER=fixture.
    ai_detect_provider: Literal["auto", "gigacheck", "fixture", "off"] = "auto"
    # Сервис детектора (gpu-node), тот же токен EMBEDDINGS_TOKEN.
    ai_detect_url: str | None = None
    # Какую модель ждём от сервиса: другая — «проверка недоступна» и предупреждение на стенде.
    ai_detect_model: str = "iitolstykh/GigaCheck-Classifier-Multi"
    ai_detect_timeout_sec: float = Field(default=60.0, gt=0)
    ai_detect_batch_size: int = Field(default=16, ge=1, le=64)
    ai_detect_concurrency: int = Field(default=1, ge=1, le=8)
    # После сбоя сервиса столько секунд отвечаем «недоступно» без вызова, потом пробуем снова.
    ai_detect_retry_after_sec: float = Field(default=60.0, ge=0)
    # Сколько секунд событие «поиск закончен» ждёт фоновую проверку постов (остальное
    # досчитается после и будет видно в подборке).
    ai_detect_finish_wait_sec: float = Field(default=20.0, ge=0)
    # Пороги уровней по оценке модели (0…1) и минимум слов — одни для всех мест.
    ai_check_likely_threshold: float = Field(default=0.85, gt=0, le=1)
    ai_check_signs_threshold: float = Field(default=0.60, gt=0, le=1)
    ai_check_min_words: int = Field(default=40, ge=1)
    # Отдельных проверок с одного IP в минуту.
    ai_check_rate_limit_per_minute: int = Field(default=30, ge=1)

    # ---------------------------------------------------------------- лимиты стенда (НТ-6)
    max_query_length: int = 20_000
    max_period_days: int = 183
    active_searches_per_workspace: int = 1
    max_running_searches: int = Field(default=4, ge=1)
    rate_limit_per_minute: int = Field(default=240, ge=1)
    search_rate_limit_per_minute: int = Field(default=12, ge=1)
    workspace_rate_limit_per_minute: int = Field(default=20, ge=1)
    max_body_bytes: int = 1_000_000
    max_import_bytes: int = 5_000_000
    max_import_rows: int = 1_000
    quota_warn_ratio: float = Field(default=0.8, gt=0, le=1)
    # Удалённый источник можно вернуть в течение этого времени (НТ-7).
    source_restore_minutes: int = 60

    @field_validator("ollama_url", "embeddings_url", "ai_detect_url")
    @classmethod
    def _blank_url_is_none(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value.strip().rstrip("/")

    @field_validator(
        "vk_service_token", "maxstat_token", "llm_api_key", "embeddings_token", mode="before"
    )
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        """Пустая строка в .env — «ключ не задан», а не пустой ключ."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_database_is_default(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_DATABASE_URL
        return value

    @model_validator(mode="after")
    def _ollama_model_alias(self) -> Settings:
        if self.ollama_model and self.llm_model == DEFAULT_LLM_MODEL:
            self.llm_model = self.ollama_model.strip()
        return self

    @model_validator(mode="after")
    def _ai_thresholds(self) -> Settings:
        if self.ai_check_signs_threshold > self.ai_check_likely_threshold:
            raise ValueError("AI_CHECK_SIGNS_THRESHOLD больше AI_CHECK_LIKELY_THRESHOLD")
        return self

    @property
    def ai_detect_kind(self) -> Literal["gigacheck", "fixture", "off"]:
        """Какой провайдер проверки на ИИ работает при этих настройках."""
        if self.ai_detect_provider != "auto":
            if self.ai_detect_provider == "gigacheck" and not self.ai_detect_url:
                return "off"
            return self.ai_detect_provider
        if self.ai_detect_url:
            return "gigacheck"
        # Демо-оценка из хеша — только для разработки на записанных примерах: на стенде её
        # легко принять за настоящую (правый клик по живому тексту), поэтому там — явно.
        if self.data_source == "fixtures" and self.environment != "production":
            return "fixture"
        return "off"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
