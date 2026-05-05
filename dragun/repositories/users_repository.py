"""Repository for user registration and authentication."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import uuid

from google.cloud import firestore


class UsersRepository:
    def __init__(self, db: firestore.Client) -> None:
        self._db = db

    @staticmethod
    def _hash_passkey(passkey: str) -> str:
        return hashlib.sha256(passkey.encode("utf-8")).hexdigest()

    def create_user(self, *, handle: str, passkey: str, zip_code: str) -> dict:
        handle_norm = handle.strip().lower()
        existing = (
            self._db.collection("users")
            .where(filter=firestore.FieldFilter("handle", "==", handle_norm))
            .limit(1)
            .stream()
        )
        if any(existing):
            raise ValueError(f"Handle '{handle_norm}' already exists.")

        now = datetime.now(timezone.utc)
        user_id = str(uuid.uuid4())
        payload = {
            "user_id": user_id,
            "handle": handle_norm,
            "passkey_hash": self._hash_passkey(passkey),
            "zip_code": zip_code,
            "currency": "USD",
            "created_at": now,
        }
        self._db.collection("users").document(user_id).set(payload)
        return payload

    def get_user_by_handle(self, handle: str) -> dict | None:
        handle_norm = handle.strip().lower()
        docs = (
            self._db.collection("users")
            .where(filter=firestore.FieldFilter("handle", "==", handle_norm))
            .limit(1)
            .stream()
        )
        for doc in docs:
            return doc.to_dict()
        return None

    def verify_user(self, *, handle: str, passkey: str) -> dict:
        user = self.get_user_by_handle(handle)
        if not user:
            raise ValueError("Unknown handle.")

        provided_hash = self._hash_passkey(passkey)
        if not hmac.compare_digest(provided_hash, user["passkey_hash"]):
            raise ValueError("Invalid passkey.")
        return user
