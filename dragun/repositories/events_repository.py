"""Repository for append-only event log operations."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from google.cloud import firestore


class EventsRepository:
    def __init__(self, db: firestore.Client) -> None:
        self._db = db

    def create_event(
        self,
        *,
        user_id: str,
        event_type: str,
        item_description: str,
        item_normalized: str,
        quantity: int,
        unit_cost: float | None,
        total_cost: float | None,
        lifespan_type: str,
        input_source: str,
        raw_input: str,
        family_member_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc)
        event_id = str(uuid.uuid4())
        payload = {
            "event_id": event_id,
            "user_id": user_id,
            "event_type": event_type,
            "item_description": item_description,
            "item_normalized": item_normalized,
            "quantity": quantity,
            "unit_cost": unit_cost,
            "total_cost": total_cost,
            "lifespan_type": lifespan_type,
            "input_source": input_source,
            "raw_input": raw_input,
            "family_member_id": family_member_id,
            "event_timestamp": now,
            "created_at": now,
            "tags": [tag.lower().strip() for tag in (tags or []) if tag.strip()],
        }
        self._db.collection("events").document(event_id).set(payload)
        return payload

    def list_events_for_user(self, user_id: str, limit: int = 500) -> list[dict]:
        query = (
            self._db.collection("events")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .limit(limit)
        )
        rows = [doc.to_dict() for doc in query.stream()]
        rows.sort(key=lambda row: row.get("event_timestamp") or datetime.min.replace(tzinfo=timezone.utc))
        return rows

