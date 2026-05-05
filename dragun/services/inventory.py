from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from dragun.models import Event, EventType, InputSource, InventoryRow, ParsedInput, User
from dragun.storage.base import DragunRepository


ADDITIVE_EVENT_TYPES = {EventType.PURCHASE, EventType.MANUAL_INVENTORY, EventType.GIFT}
SUBTRACTIVE_EVENT_TYPES = {EventType.CONSUMPTION, EventType.RETURN, EventType.DISCARD}


@dataclass(frozen=True)
class VelocityMetric:
    item_normalized: str
    purchase_count: int
    recent_purchase_count: int
    message: str | None = None


@dataclass(slots=True)
class InventoryService:
    repository: DragunRepository

    def log_items(
        self,
        user: User,
        parsed: ParsedInput,
        input_source: InputSource = InputSource.TEXT,
    ) -> list[Event]:
        event_type = (
            EventType.MANUAL_INVENTORY
            if parsed.intent == "manual_inventory"
            else EventType.PURCHASE
        )
        events: list[Event] = []
        for item in parsed.items:
            event = Event(
                event_id=str(uuid4()),
                user_id=user.user_id,
                event_type=event_type,
                item_description=item.description,
                item_normalized=item.item_normalized,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                total_cost=item.total_cost,
                lifespan_type=item.lifespan_type,
                input_source=input_source,
                raw_input=parsed.raw,
                event_timestamp=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            events.append(self.repository.create_event(event, item.suggested_tags))
        return events

    def query_inventory(self, user_id: str, item_filter: str | None = None) -> list[InventoryRow]:
        events = self.repository.list_events(user_id)
        tags_by_event = self.repository.list_event_tags([event.event_id for event in events])
        return compute_inventory(events, tags_by_event, item_filter=item_filter)

    def velocity_notes(self, user_id: str, new_events: list[Event]) -> list[str]:
        all_events = self.repository.list_events(user_id)
        notes: list[str] = []
        for event in new_events:
            if event.event_type != EventType.PURCHASE:
                continue
            recent_count = sum(
                previous.quantity
                for previous in all_events
                if previous.event_type == EventType.PURCHASE
                and previous.item_normalized == event.item_normalized
                and previous.event_timestamp >= datetime.now(UTC) - timedelta(days=60)
            )
            if recent_count >= 3:
                notes.append(
                    f"You've bought {recent_count:g} {event.item_normalized} in the last 60 days. The hoard is growing fast."
                )
        return notes


def compute_inventory(
    events: list[Event],
    tags_by_event: dict[str, list[str]],
    *,
    item_filter: str | None = None,
) -> list[InventoryRow]:
    grouped: dict[tuple[str | None, str], dict] = {}
    for event in sorted(events, key=lambda e: e.event_timestamp):
        if item_filter and item_filter.lower() not in event.item_normalized:
            continue
        key = (event.family_member_id, event.item_normalized)
        entry = grouped.setdefault(
            key,
            {
                "user_id": event.user_id,
                "family_member_id": event.family_member_id,
                "item_normalized": event.item_normalized,
                "tags": set(),
                "quantity": 0,
                "lifespan_type": event.lifespan_type,
                "costs": [],
                "last_purchased": None,
                "first_seen": event.event_timestamp,
            },
        )
        entry["tags"].update(tags_by_event.get(event.event_id, []))
        entry["first_seen"] = min(entry["first_seen"], event.event_timestamp)
        entry["lifespan_type"] = event.lifespan_type
        if event.unit_cost is not None:
            entry["costs"].append(event.unit_cost)
        if event.event_type in ADDITIVE_EVENT_TYPES:
            entry["quantity"] += event.quantity
            if event.event_type == EventType.PURCHASE:
                entry["last_purchased"] = event.event_timestamp
        elif event.event_type in SUBTRACTIVE_EVENT_TYPES:
            entry["quantity"] -= event.quantity

    inventory: list[InventoryRow] = []
    for entry in grouped.values():
        costs = entry["costs"]
        inventory.append(
            InventoryRow(
                user_id=entry["user_id"],
                family_member_id=entry["family_member_id"],
                item_normalized=entry["item_normalized"],
                tags=sorted(entry["tags"]),
                current_quantity=entry["quantity"],
                lifespan_type=entry["lifespan_type"],
                avg_unit_cost=round(sum(costs) / len(costs), 2) if costs else None,
                last_purchased=entry["last_purchased"],
                first_seen=entry["first_seen"],
            )
        )
    return sorted(inventory, key=lambda row: row.item_normalized)


def find_inventory_item(
    inventory: list[InventoryRow], item_name: str, family_member_id: str | None = None
) -> InventoryRow | None:
    normalized = item_name.lower().strip()
    for entry in inventory:
        if entry.item_normalized == normalized and entry.family_member_id == family_member_id:
            return entry
    return None


def compute_velocity(events: list[Event], item_name: str | None = None) -> list[VelocityMetric]:
    purchase_events = [
        event
        for event in events
        if event.event_type == "purchase"
        and (item_name is None or event.item_normalized == item_name.lower().strip())
    ]
    by_item: dict[str, list[Event]] = defaultdict(list)
    for event in purchase_events:
        by_item[event.item_normalized].append(event)

    metrics: list[VelocityMetric] = []
    now = datetime.now(UTC)
    for normalized, item_events in by_item.items():
        ordered = sorted(item_events, key=lambda e: e.event_timestamp)
        recent_count = sum(1 for event in ordered if (now - event.event_timestamp).days <= 60)
        message = None
        if recent_count >= 3:
            message = f"You've bought {recent_count} {normalized} in the last 60 days. The hoard is growing fast."
        metrics.append(
            VelocityMetric(
                item_normalized=normalized,
                purchase_count=len(ordered),
                recent_purchase_count=recent_count,
                message=message,
            )
        )
    return metrics
