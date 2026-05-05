"""Core domain logic for Dragun Phase 1."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any

from dragun.repositories.budgets_repository import BudgetsRepository
from dragun.repositories.events_repository import EventsRepository
from dragun.repositories.users_repository import UsersRepository
from dragun.services.parsing import infer_tags, parse_purchase_text


_INVENTORY_ADD_EVENT_TYPES = {"purchase", "manual_inventory", "gift"}
_INVENTORY_SUBTRACT_EVENT_TYPES = {"consumption", "return", "discard"}


def _to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


class DragunEngine:
    def __init__(
        self,
        *,
        users_repo: UsersRepository,
        events_repo: EventsRepository,
        budgets_repo: BudgetsRepository,
    ) -> None:
        self.users_repo = users_repo
        self.events_repo = events_repo
        self.budgets_repo = budgets_repo

    def register_user(self, *, handle: str, passkey: str, zip_code: str) -> dict:
        return self.users_repo.create_user(handle=handle, passkey=passkey, zip_code=zip_code)

    def authenticate(self, *, handle: str, passkey: str) -> dict:
        return self.users_repo.verify_user(handle=handle, passkey=passkey)

    def parse_input(self, raw_input: str) -> dict:
        lowered = raw_input.strip().lower()
        is_manual_inventory = lowered.startswith("i have") or lowered.startswith("we have")
        parsed = parse_purchase_text(raw_input)
        if is_manual_inventory:
            for item in parsed:
                item["unit_cost"] = None
                item["total_cost"] = None
        return {
            "raw_input": raw_input,
            "is_manual_inventory": is_manual_inventory,
            "items": parsed,
        }

    def log_text_input(self, *, user_id: str, raw_input: str, input_source: str = "text") -> dict:
        parsed = self.parse_input(raw_input)
        event_type = "manual_inventory" if parsed["is_manual_inventory"] else "purchase"
        created_events: list[dict] = []
        for item in parsed["items"]:
            created_events.append(
                self.events_repo.create_event(
                    user_id=user_id,
                    event_type=event_type,
                    item_description=item["description"],
                    item_normalized=item["item_normalized"],
                    quantity=item["quantity"],
                    unit_cost=item.get("unit_cost"),
                    total_cost=item.get("total_cost"),
                    lifespan_type=item["lifespan_type"],
                    input_source=input_source,
                    raw_input=raw_input,
                    tags=item.get("suggested_tags") or infer_tags(item["item_normalized"]),
                )
            )
        return {"event_type": event_type, "items": parsed["items"], "events": created_events}

    def compute_inventory_state(
        self,
        *,
        user_id: str,
        item_name: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict]:
        events = self.events_repo.list_events_for_user(user_id=user_id)
        rows: dict[str, dict] = {}

        for event in events:
            key = event.get("item_normalized")
            if not key:
                continue
            row = rows.setdefault(
                key,
                {
                    "item_normalized": key,
                    "current_quantity": 0,
                    "lifespan_type": event.get("lifespan_type"),
                    "avg_unit_cost": None,
                    "last_purchased": None,
                    "first_seen": event.get("event_timestamp"),
                    "tags": set(),
                    "_unit_cost_values": [],
                },
            )
            qty = int(event.get("quantity") or 0)
            event_type = event.get("event_type")
            if event_type in _INVENTORY_ADD_EVENT_TYPES:
                row["current_quantity"] += qty
            elif event_type in _INVENTORY_SUBTRACT_EVENT_TYPES:
                row["current_quantity"] -= qty

            event_tags = event.get("tags") or []
            row["tags"].update(tag for tag in event_tags if isinstance(tag, str))
            unit_cost = event.get("unit_cost")
            if unit_cost is not None and event_type in {"purchase", "manual_inventory"}:
                row["_unit_cost_values"].append(float(unit_cost))

            event_ts = _to_datetime(event.get("event_timestamp"))
            if event_type == "purchase" and (
                row["last_purchased"] is None or (event_ts and event_ts > row["last_purchased"])
            ):
                row["last_purchased"] = event_ts
            if event_ts and (row["first_seen"] is None or event_ts < _to_datetime(row["first_seen"])):
                row["first_seen"] = event_ts

        normalized_item_name = item_name.strip().lower() if item_name else None
        tag_filter = {tag.strip().lower() for tag in (tags or []) if tag.strip()}
        result: list[dict] = []

        for row in rows.values():
            row["current_quantity"] = max(0, row["current_quantity"])
            if row["_unit_cost_values"]:
                row["avg_unit_cost"] = round(mean(row["_unit_cost_values"]), 2)
            row["tags"] = sorted(row["tags"])
            row.pop("_unit_cost_values", None)

            if normalized_item_name and row["item_normalized"] != normalized_item_name:
                continue
            if tag_filter and not tag_filter.intersection(set(row["tags"])):
                continue
            result.append(row)

        result.sort(key=lambda item: item["item_normalized"])
        return result

    def create_budget(
        self,
        *,
        user_id: str,
        budget_scope: str,
        scope_tags: list[str],
        budget_amount: float,
        period_type: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        rollover_enabled: bool = False,
    ) -> dict:
        start, end = self._resolve_budget_window(period_type, period_start, period_end)
        return self.budgets_repo.create_budget(
            user_id=user_id,
            budget_scope=budget_scope,
            scope_tags=scope_tags,
            budget_amount=budget_amount,
            period_type=period_type,
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            rollover_enabled=rollover_enabled,
        )

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
        return self.budgets_repo.create_constraint(
            user_id=user_id,
            constraint_type=constraint_type,
            scope_tags=scope_tags,
            operator=operator,
            threshold_value=threshold_value,
            message_template=message_template,
        )

    def get_budget_status(self, *, user_id: str) -> list[dict]:
        budgets = self.budgets_repo.list_active_budgets(user_id)
        events = self.events_repo.list_events_for_user(user_id)
        today = _today_utc()
        statuses: list[dict] = []

        for budget in budgets:
            start = date.fromisoformat(budget["period_start"])
            end = date.fromisoformat(budget["period_end"])
            spent = self._compute_spend_for_scope(
                events=events,
                scope_tags=budget.get("scope_tags") or [],
                budget_scope=budget.get("budget_scope", "all"),
                period_start=start,
                period_end=end,
            )
            remaining = round(float(budget["budget_amount"]) - spent, 2)
            days_remaining = max((end - today).days + 1, 0)
            daily_pace = round(remaining / days_remaining, 2) if days_remaining else 0.0
            budget_amount = float(budget["budget_amount"])
            statuses.append(
                {
                    "budget_id": budget["budget_id"],
                    "budget_scope": budget["budget_scope"],
                    "scope_tags": budget.get("scope_tags") or [],
                    "period_start": budget["period_start"],
                    "period_end": budget["period_end"],
                    "amount_spent": round(spent, 2),
                    "amount_remaining": remaining,
                    "days_remaining": days_remaining,
                    "daily_pace": daily_pace,
                    "pct_consumed": round((spent / budget_amount) * 100, 2) if budget_amount else 0.0,
                }
            )

        return statuses

    def evaluate_purchase(self, *, user_id: str, proposed_items: list[dict]) -> list[dict]:
        statuses = self.get_budget_status(user_id=user_id)
        impacts: list[dict] = []
        for status in statuses:
            proposed_spend = self._proposed_cost_for_scope(
                scope_tags=status.get("scope_tags") or [],
                budget_scope=status.get("budget_scope", "all"),
                proposed_items=proposed_items,
            )
            projected_remaining = round(status["amount_remaining"] - proposed_spend, 2)
            impacts.append(
                {
                    **status,
                    "proposed_spend": round(proposed_spend, 2),
                    "projected_remaining": projected_remaining,
                    "would_exceed_budget": projected_remaining < 0,
                }
            )
        return impacts

    def check_constraints(self, *, user_id: str, proposed_items: list[dict]) -> list[dict]:
        constraints = self.budgets_repo.list_active_constraints(user_id)
        inventory = {
            row["item_normalized"]: row
            for row in self.compute_inventory_state(user_id=user_id)
        }
        budget_impacts = self.evaluate_purchase(user_id=user_id, proposed_items=proposed_items)
        now = _today_utc()
        alerts: list[dict] = []

        for constraint in constraints:
            ctype = constraint["constraint_type"]
            scope_tags = set(constraint.get("scope_tags") or [])
            threshold = float(constraint["threshold_value"])
            template = constraint.get("message_template")

            if ctype == "inventory_cap":
                for item in proposed_items:
                    item_tags = set(item.get("suggested_tags") or [])
                    if scope_tags and not scope_tags.intersection(item_tags):
                        continue
                    current = inventory.get(item["item_normalized"], {}).get("current_quantity", 0)
                    projected = current + int(item["quantity"])
                    if projected > threshold:
                        message = template or (
                            f"You already have {current} {item['item_normalized']}. "
                            f"Buying {item['quantity']} puts you at {projected}, above your cap of {int(threshold)}."
                        )
                        alerts.append(
                            {
                                "constraint_type": ctype,
                                "item": item["item_normalized"],
                                "triggered": True,
                                "message": message,
                            }
                        )

            elif ctype == "hard_budget_limit":
                month_start = now.replace(day=1)
                month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                events = self.events_repo.list_events_for_user(user_id=user_id)
                spent = self._compute_spend_for_scope(
                    events=events,
                    scope_tags=list(scope_tags),
                    budget_scope="all" if not scope_tags else "tag_scoped",
                    period_start=month_start,
                    period_end=month_end,
                )
                proposed = self._proposed_cost_for_scope(
                    scope_tags=list(scope_tags),
                    budget_scope="all" if not scope_tags else "tag_scoped",
                    proposed_items=proposed_items,
                )
                if spent + proposed > threshold:
                    message = template or (
                        f"This purchase adds ${proposed:.2f}. "
                        f"You're at ${spent:.2f} and would exceed your ${threshold:.2f} limit."
                    )
                    alerts.append(
                        {
                            "constraint_type": ctype,
                            "triggered": True,
                            "message": message,
                        }
                    )

            elif ctype == "pace_alert":
                for impact in budget_impacts:
                    if scope_tags and not scope_tags.intersection(set(impact.get("scope_tags") or [])):
                        continue
                    days_remaining = max(impact["days_remaining"], 1)
                    projected_pace = impact["projected_remaining"] / days_remaining
                    if projected_pace < threshold:
                        message = template or (
                            f"Budget pace drops to ${projected_pace:.2f}/day for {impact['budget_scope']}."
                        )
                        alerts.append(
                            {
                                "constraint_type": ctype,
                                "budget_scope": impact["budget_scope"],
                                "triggered": True,
                                "message": message,
                            }
                        )

        return alerts

    def query_velocity(self, *, user_id: str, item_name: str) -> dict:
        events = self.events_repo.list_events_for_user(user_id=user_id)
        item = item_name.strip().lower()
        purchases = [
            _to_datetime(event.get("event_timestamp"))
            for event in events
            if event.get("event_type") == "purchase"
            and event.get("item_normalized") == item
            and _to_datetime(event.get("event_timestamp")) is not None
        ]
        purchases = sorted([ts for ts in purchases if ts is not None])
        if len(purchases) < 2:
            return {
                "item_normalized": item,
                "purchase_count": len(purchases),
                "avg_restock_days": None,
                "trend_direction": "stable",
                "predicted_next": None,
            }

        intervals = [
            (purchases[idx] - purchases[idx - 1]).days for idx in range(1, len(purchases))
        ]
        avg_interval = float(mean(intervals))
        latest = intervals[-1]
        if latest < avg_interval * 0.85:
            trend = "accelerating"
        elif latest > avg_interval * 1.15:
            trend = "decelerating"
        else:
            trend = "stable"
        predicted_next = purchases[-1] + timedelta(days=round(avg_interval))
        return {
            "item_normalized": item,
            "purchase_count": len(purchases),
            "avg_restock_days": round(avg_interval, 2),
            "trend_direction": trend,
            "predicted_next": predicted_next.isoformat(),
        }

    def get_spending_trends(self, *, user_id: str) -> dict:
        events = self.events_repo.list_events_for_user(user_id=user_id)
        today = _today_utc()
        this_month_start = today.replace(day=1)
        last_month_end = this_month_start - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        this_month = self._sum_spend(events, this_month_start, today)
        last_month = self._sum_spend(events, last_month_start, last_month_end)
        pct = ((this_month - last_month) / last_month * 100.0) if last_month else 0.0
        return {
            "this_month_spend": round(this_month, 2),
            "last_month_spend": round(last_month, 2),
            "month_over_month_pct": round(pct, 2),
        }

    def generate_summary(self, *, user_id: str) -> dict:
        inventory = self.compute_inventory_state(user_id=user_id)
        budgets = self.get_budget_status(user_id=user_id)
        trends = self.get_spending_trends(user_id=user_id)
        return {
            "inventory_top": inventory[:5],
            "budgets": budgets,
            "trends": trends,
        }

    def _resolve_budget_window(
        self,
        period_type: str,
        period_start: date | None,
        period_end: date | None,
    ) -> tuple[date, date]:
        if period_start and period_end:
            return period_start, period_end
        today = _today_utc()
        if period_type == "weekly":
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            return start, end
        if period_type == "custom":
            start = period_start or today
            end = period_end or (start + timedelta(days=30))
            return start, end
        # monthly default
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return start, end

    def _sum_spend(self, events: list[dict], start: date, end: date) -> float:
        total = 0.0
        for event in events:
            ts = _to_datetime(event.get("event_timestamp"))
            if not ts:
                continue
            d = ts.date()
            if start <= d <= end:
                total += float(event.get("total_cost") or 0.0)
        return total

    def _compute_spend_for_scope(
        self,
        *,
        events: list[dict],
        scope_tags: list[str],
        budget_scope: str,
        period_start: date,
        period_end: date,
    ) -> float:
        normalized_scope_tags = {tag.lower().strip() for tag in scope_tags if tag.strip()}
        total = 0.0
        for event in events:
            ts = _to_datetime(event.get("event_timestamp"))
            if not ts:
                continue
            d = ts.date()
            if not (period_start <= d <= period_end):
                continue
            cost = float(event.get("total_cost") or 0.0)
            if cost <= 0:
                continue

            tags = {tag.lower().strip() for tag in (event.get("tags") or []) if isinstance(tag, str)}
            if normalized_scope_tags:
                if normalized_scope_tags.intersection(tags):
                    total += cost
            elif budget_scope and budget_scope.lower() not in {"all", "tag_scoped"}:
                if budget_scope.lower() in tags:
                    total += cost
            else:
                total += cost
        return total

    def _proposed_cost_for_scope(
        self,
        *,
        scope_tags: list[str],
        budget_scope: str,
        proposed_items: list[dict],
    ) -> float:
        normalized_scope_tags = {tag.lower().strip() for tag in scope_tags if tag.strip()}
        total = 0.0
        for item in proposed_items:
            item_tags = {tag.lower().strip() for tag in (item.get("suggested_tags") or [])}
            cost = float(item.get("total_cost") or 0.0)
            if normalized_scope_tags:
                if normalized_scope_tags.intersection(item_tags):
                    total += cost
            elif budget_scope and budget_scope.lower() not in {"all", "tag_scoped"}:
                if budget_scope.lower() in item_tags:
                    total += cost
            else:
                total += cost
        return total
