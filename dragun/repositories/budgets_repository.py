"""Repository for budget and constraint persistence."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from google.cloud import firestore


class BudgetsRepository:
    def __init__(self, db: firestore.Client) -> None:
        self._db = db

    def create_budget(
        self,
        *,
        user_id: str,
        budget_scope: str,
        scope_tags: list[str],
        budget_amount: float,
        period_type: str,
        period_start: str,
        period_end: str,
        rollover_enabled: bool = False,
    ) -> dict:
        now = datetime.now(timezone.utc)
        budget_id = str(uuid.uuid4())
        payload = {
            "budget_id": budget_id,
            "user_id": user_id,
            "budget_scope": budget_scope.lower().strip(),
            "scope_tags": [tag.lower().strip() for tag in scope_tags if tag.strip()],
            "budget_amount": budget_amount,
            "period_type": period_type,
            "period_start": period_start,
            "period_end": period_end,
            "rollover_enabled": rollover_enabled,
            "is_active": True,
            "created_at": now,
        }
        self._db.collection("budgets").document(budget_id).set(payload)
        return payload

    def list_active_budgets(self, user_id: str) -> list[dict]:
        query = (
            self._db.collection("budgets")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .where(filter=firestore.FieldFilter("is_active", "==", True))
        )
        return [doc.to_dict() for doc in query.stream()]

    def create_constraint(
        self,
        *,
        user_id: str,
        constraint_type: str,
        scope_tags: list[str],
        operator: str,
        threshold_value: float,
        message_template: str | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc)
        constraint_id = str(uuid.uuid4())
        payload = {
            "constraint_id": constraint_id,
            "user_id": user_id,
            "constraint_type": constraint_type,
            "scope_tags": [tag.lower().strip() for tag in scope_tags if tag.strip()],
            "operator": operator,
            "threshold_value": threshold_value,
            "message_template": message_template,
            "is_active": True,
            "created_at": now,
        }
        self._db.collection("constraints").document(constraint_id).set(payload)
        return payload

    def list_active_constraints(self, user_id: str) -> list[dict]:
        query = (
            self._db.collection("constraints")
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
            .where(filter=firestore.FieldFilter("is_active", "==", True))
        )
        return [doc.to_dict() for doc in query.stream()]
