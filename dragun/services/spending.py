"""Spending aggregation service — summary and daily breakdown."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from dragun.models import EventType
from dragun.storage.base import DragunRepository


def _period_bounds(period: str) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    if period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    else:  # default: month
        start = today.replace(day=1)
        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    return start, end


@dataclass
class CategoryBreakdown:
    category: str
    amount: float
    pct: float


@dataclass
class SpendingSummary:
    total_spent: float
    by_category: list[CategoryBreakdown]
    period_start: str   # ISO date string
    period_end: str


@dataclass
class DailyAmount:
    date: str           # ISO date string
    amount: float


@dataclass
class SpendingDaily:
    days: list[DailyAmount]
    period_start: str
    period_end: str


def get_spending_summary(repo: DragunRepository, user_id: str, period: str) -> SpendingSummary:
    start, end = _period_bounds(period)
    events = repo.list_events(user_id, start=start, end=end)
    purchase_events = [e for e in events if e.event_type == EventType.PURCHASE]

    if not purchase_events:
        return SpendingSummary(
            total_spent=0.0,
            by_category=[],
            period_start=start.isoformat(),
            period_end=end.isoformat(),
        )

    # Resolve tags for each event
    event_ids = [e.event_id for e in purchase_events]
    tags_by_event = repo.list_event_tags(event_ids)

    # Aggregate by primary tag (first tag), falling back to "uncategorized"
    by_category: dict[str, float] = defaultdict(float)
    total_spent = 0.0
    for event in purchase_events:
        cost = event.total_cost or 0.0
        total_spent += cost
        tags = tags_by_event.get(event.event_id, [])
        category = tags[0] if tags else "uncategorized"
        by_category[category] += cost

    total_spent = round(total_spent, 2)
    breakdown = sorted(
        [
            CategoryBreakdown(
                category=cat,
                amount=round(amt, 2),
                pct=round(amt / total_spent, 4) if total_spent else 0.0,
            )
            for cat, amt in by_category.items()
        ],
        key=lambda c: c.amount,
        reverse=True,
    )

    return SpendingSummary(
        total_spent=total_spent,
        by_category=breakdown,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
    )


def get_spending_daily(repo: DragunRepository, user_id: str, period: str) -> SpendingDaily:
    start, end = _period_bounds(period)
    events = repo.list_events(user_id, start=start, end=end)
    purchase_events = [e for e in events if e.event_type == EventType.PURCHASE]

    # Build a zero-filled map for every day in the period
    daily: dict[date, float] = {}
    cursor = start
    while cursor <= end:
        daily[cursor] = 0.0
        cursor += timedelta(days=1)

    for event in purchase_events:
        day = event.event_timestamp.date()
        if day in daily:
            daily[day] += event.total_cost or 0.0

    days = [
        DailyAmount(date=d.isoformat(), amount=round(amt, 2))
        for d, amt in sorted(daily.items())
    ]

    return SpendingDaily(
        days=days,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
    )
