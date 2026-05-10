from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from google.cloud import firestore

from dragun.models import Budget, Constraint, Event, EventTag, Tag, User
from dragun.storage.base import DragunRepository


class FirestoreRepository(DragunRepository):
    """Firestore-backed repository for Dragun's append-only event model."""

    def __init__(self, project_id: str | None = None, database: str | None = None) -> None:
        if database and database != "(default)":
            self.client = firestore.Client(project=project_id, database=database)
        else:
            self.client = firestore.Client(project=project_id)

    def create_user(self, user: User) -> User:
        if self.get_user_by_handle(user.handle):
            raise ValueError("That handle is already guarding a hoard.")
        self.client.collection("users").document(user.user_id).set(user.model_dump(mode="python"))
        return user

    def get_user_by_handle(self, handle: str) -> User | None:
        docs = (
            self.client.collection("users")
            .where(filter=firestore.FieldFilter("handle", "==", handle.strip().lower()))
            .limit(1)
            .stream()
        )
        for doc in docs:
            return User(**doc.to_dict())
        return None

    def get_user(self, user_id: str) -> User | None:
        doc = self.client.collection("users").document(user_id).get()
        return User(**doc.to_dict()) if doc.exists else None

    def create_event(self, event: Event, tag_names: Iterable[str]) -> Event:
        unique_tag_names = dict.fromkeys(tag_name.strip().lower() for tag_name in tag_names if tag_name)
        tags = [self.upsert_tag(tag_name, "agent_inferred") for tag_name in unique_tag_names]
        batch = self.client.batch()
        event_ref = self.client.collection("events").document(event.event_id)
        batch.set(event_ref, event.model_dump(mode="python"))
        for tag in tags:
            event_tag = EventTag(event_id=event.event_id, tag_id=tag.tag_id)
            tag_ref = self.client.collection("event_tags").document(
                f"{event.event_id}_{tag.tag_id}"
            )
            batch.set(tag_ref, event_tag.model_dump(mode="python"))
        batch.commit()
        return event

    def list_events(
        self,
        user_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Event]:
        query: Any = (
            self.client.collection("events")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .order_by("event_timestamp")
        )
        events = [Event(**doc.to_dict()) for doc in query.stream()]
        if start:
            events = [event for event in events if event.event_timestamp.date() >= start]
        if end:
            events = [event for event in events if event.event_timestamp.date() <= end]
        return events

    def upsert_tag(self, tag_name: str, tag_origin: str = "agent_inferred") -> Tag:
        normalized = tag_name.strip().lower()
        docs = (
            self.client.collection("tags")
            .where(filter=firestore.FieldFilter("tag_name", "==", normalized))
            .limit(1)
            .stream()
        )
        for doc in docs:
            return Tag(**doc.to_dict())
        tag = Tag(tag_name=normalized, tag_origin=tag_origin)  # type: ignore[arg-type]
        self.client.collection("tags").document(tag.tag_id).set(tag.model_dump(mode="python"))
        return tag

    def list_tags(self) -> list[Tag]:
        return [Tag(**doc.to_dict()) for doc in self.client.collection("tags").stream()]

    def list_event_tags(self, event_ids: Iterable[str]) -> dict[str, list[str]]:
        ids = list(event_ids)
        if not ids:
            return {}
        output: dict[str, list[str]] = {event_id: [] for event_id in ids}
        tags_by_id = {
            doc.id: Tag(**doc.to_dict()).tag_name
            for doc in self.client.collection("tags").stream()
        }
        for index in range(0, len(ids), 30):
            chunk = ids[index : index + 30]
            docs = (
                self.client.collection("event_tags")
                .where(filter=firestore.FieldFilter("event_id", "in", chunk))
                .stream()
            )
            for doc in docs:
                event_tag = EventTag(**doc.to_dict())
                tag_name = tags_by_id.get(event_tag.tag_id)
                if tag_name:
                    output.setdefault(event_tag.event_id, []).append(tag_name)
        return output

    def update_item_tags(self, user_id: str, item_normalized: str, new_tags: list[str]) -> int:
        """Replace tags on all events for this user+item."""
        events = (
            self.client.collection("events")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .where(filter=firestore.FieldFilter("item_normalized", "==", item_normalized))
            .stream()
        )
        event_ids = [doc.id for doc in events]
        if not event_ids:
            return 0
        # Upsert new tags
        tags = [self.upsert_tag(t) for t in new_tags if t]
        batch = self.client.batch()
        for event_id in event_ids:
            # Delete old event_tag docs for this event
            old_docs = (
                self.client.collection("event_tags")
                .where(filter=firestore.FieldFilter("event_id", "==", event_id))
                .stream()
            )
            for doc in old_docs:
                batch.delete(doc.reference)
            # Add new event_tag docs
            for tag in tags:
                event_tag = EventTag(event_id=event_id, tag_id=tag.tag_id)
                ref = self.client.collection("event_tags").document(f"{event_id}_{tag.tag_id}")
                batch.set(ref, event_tag.model_dump(mode="python"))
        batch.commit()
        return len(event_ids)

    def create_budget(self, budget: Budget) -> Budget:
        self.client.collection("budgets").document(budget.budget_id).set(
            budget.model_dump(mode="python")
        )
        return budget

    def list_active_budgets(self, user_id: str) -> list[Budget]:
        docs = (
            self.client.collection("budgets")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .where(filter=firestore.FieldFilter("is_active", "==", True))
            .stream()
        )
        return sorted((Budget(**doc.to_dict()) for doc in docs), key=lambda budget: budget.created_at)

    def create_constraint(self, constraint: Constraint) -> Constraint:
        self.client.collection("constraints").document(constraint.constraint_id).set(
            constraint.model_dump(mode="python")
        )
        return constraint

    def list_active_constraints(self, user_id: str) -> list[Constraint]:
        docs = (
            self.client.collection("constraints")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .where(filter=firestore.FieldFilter("is_active", "==", True))
            .stream()
        )
        return sorted(
            (Constraint(**doc.to_dict()) for doc in docs),
            key=lambda constraint: constraint.created_at,
        )

    def export_user_data(self, user_id: str) -> dict[str, Any]:
        user = self.get_user(user_id)
        events = self.list_events(user_id)
        event_ids = [event.event_id for event in events]
        event_tags = []
        if event_ids:
            for index in range(0, len(event_ids), 30):
                chunk = event_ids[index : index + 30]
                docs = (
                    self.client.collection("event_tags")
                    .where(filter=firestore.FieldFilter("event_id", "in", chunk))
                    .stream()
                )
                event_tags.extend(EventTag(**doc.to_dict()) for doc in docs)
        return {
            "user": user.model_dump(mode="json") if user else None,
            "events": [event.model_dump(mode="json") for event in events],
            "event_tags": [event_tag.model_dump(mode="json") for event_tag in event_tags],
            "tags": [
                Tag(**doc.to_dict()).model_dump(mode="json")
                for doc in self.client.collection("tags").stream()
            ],
            "budgets": [budget.model_dump(mode="json") for budget in self.list_active_budgets(user_id)],
            "constraints": [
                constraint.model_dump(mode="json")
                for constraint in self.list_active_constraints(user_id)
            ],
        }

    def delete_user_data(self, user_id: str) -> None:
        for collection_name, field_name in (
            ("events", "user_id"),
            ("budgets", "user_id"),
            ("constraints", "user_id"),
            ("family_members", "user_id"),
        ):
            docs = (
                self.client.collection(collection_name)
                .where(filter=firestore.FieldFilter(field_name, "==", user_id))
                .stream()
            )
            for doc in docs:
                doc.reference.delete()
        self.client.collection("users").document(user_id).delete()
