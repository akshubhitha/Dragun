"""Application configuration for Dragun."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("DRAGUN_APP_NAME", "dragun")
    model_name: str = os.getenv("DRAGUN_MODEL", "gemini-flash-latest")
    google_cloud_project: str | None = os.getenv("GOOGLE_CLOUD_PROJECT")
    firestore_database: str | None = os.getenv("FIRESTORE_DATABASE")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8080"))


settings = Settings()
