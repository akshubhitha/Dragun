from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors_origins(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return value
    return [origin.strip() for origin in value.split(",") if origin.strip()]


class Settings(BaseSettings):
    """Runtime settings for local development and Cloud Run."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Dragun"
    environment: str = Field(default="local", validation_alias="DRAGUN_ENV")
    google_cloud_project: str | None = Field(default=None, validation_alias="GOOGLE_CLOUD_PROJECT")
    use_firestore: bool = Field(default=False, validation_alias="DRAGUN_USE_FIRESTORE")
    firestore_database: str = Field(default="(default)", validation_alias="FIRESTORE_DATABASE")
    firestore_emulator_host: str | None = Field(default=None, validation_alias="FIRESTORE_EMULATOR_HOST")
    adk_model: str = Field(default="gemini-2.5-flash", validation_alias="ADK_MODEL")
    # Cheaper / faster model used for pure JSON extraction — no voice, just structure
    gemini_extraction_model: str = Field(default="gemini-2.0-flash-lite", validation_alias="GEMINI_EXTRACTION_MODEL")
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    arize_api_key: str | None = Field(default=None, validation_alias="ARIZE_API_KEY")
    session_secret: str | None = Field(default=None, validation_alias="DRAGUN_SESSION_SECRET")
    resend_api_key: str | None = Field(default=None, validation_alias="RESEND_API_KEY")
    email_from: str = Field(default="support@mydragun.com", validation_alias="EMAIL_FROM")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        validation_alias="CORS_ORIGINS",
    )

    @property
    def gemini_model(self) -> str:
        return self.adk_model

    @property
    def extraction_model(self) -> str:
        """Cheap flash-lite model for deterministic JSON extraction."""
        return self.gemini_extraction_model

    @property
    def allowed_origins(self) -> list[str]:
        return self.cors_origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
