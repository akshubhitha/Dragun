"""Firestore client helpers."""

from __future__ import annotations

from google.auth.exceptions import DefaultCredentialsError
from google.cloud import firestore

from dragun.config import settings


def get_firestore_client() -> firestore.Client:
    """Return a Firestore client using ADC credentials."""
    try:
        return firestore.Client(
            project=settings.google_cloud_project,
            database=settings.firestore_database,
        )
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "Firestore credentials are not configured. Set ADC via "
            "`gcloud auth application-default login` for local development, "
            "or run with a Cloud Run service account in production."
        ) from exc
