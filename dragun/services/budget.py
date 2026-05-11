"""Budget and constraint evaluation services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from dragun.models import (
    Budget,
    BudgetCreateRequest,
    BudgetStatus,
    Constraint,
    ConstraintAlert,
    ConstraintCreateRequest,
    ConstraintOperator,
    ConstraintType,
    EventType,
    ParsedItem,
    PeriodType,
    PurchaseEvaluation,
)
from dragun.services.inventory import InventoryService
from dragun.storage.base import DragunRepository


@dataclass(frozen=True)
class BudgetPeriod:
    start: date
    end: date


@dataclass(slots=True)
class BudgetService:
    """Creates budgets/constraints and computes budget views from events."""

    repository: DragunRepository
    inventory_service: InventoryService

    def create_budget(self, user_id: str, request: BudgetCreateRequest) -> Budget:
        tag_names = request.scope_tags or (
            [request.budget_scope] if request.budget_scope and request.budget_scope != "all" else []
        )
        tags = [self.repository.upsert_tag(tag_name) for tag_name in tag_names]
        period = period_for(request.period_type)
        budget = Budget(
            budget_id=str(uuid4()),
            user_id=user_id,
            budget_scope=request.budget_scope.strip().lower() or "all",
            scope_tags=[tag.tag_id for tag in tags],
            budget_amount=round(float(request.budget_amount), 2),
            period_type=request.period_type,
            period_start=period.start,
            period_end=period.end,
            rollover_enabled=request.rollover_enabled,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        return self.repository.create_budget(budget)

    def create_constraint(self, user_id: str, request: ConstraintCreateRequest) -> Constraint:
        message_template = request.message_template or default_constraint_message(
            request.constraint_type
        )
        constraint = Constraint(
            constraint_id=str(uuid4()),
            user_id=user_id,
            constraint_type=request.constraint_type,
            scope_tags=[tag_name.strip().lower() for tag_name in request.scope_tags],
            item_normalized=request.item_normalized,
            operator=request.operator,
            threshold_value=float(request.threshold_value),
            message_template=message_template,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        return self.repository.create_constraint(constraint)

    def get_budget_status(self, budget: Budget) -> BudgetStatus:
        events = self.repository.list_events(budget.user_id)
        tags_by_event = self.repository.list_event_tags([event.event_id for event in events])
        amount_spent = sum(
            event.total_cost or 0
            for event in events
            if event.event_type == EventType.PURCHASE
            and budget.period_start <= event.event_timestamp.date() <= budget.period_end
            and budget_matches_event(budget, tags_by_event.get(event.event_id, []))
        )
        return status_from_spend(budget, amount_spent)

    def get_budget_statuses(self, user_id: str) -> list[BudgetStatus]:
        return [self.get_budget_status(budget) for budget in self.repository.list_active_budgets(user_id)]

    def evaluate_purchase(self, user_id: str, items: list[ParsedItem]) -> PurchaseEvaluation:
        statuses = self._statuses_after_purchase(user_id, items)
        alerts = self.check_constraints(user_id, items, statuses)
        return PurchaseEvaluation(budget_statuses=statuses, constraint_alerts=alerts)

    def check_constraints(
        self,
        user_id: str,
        items: list[ParsedItem],
        statuses_after_purchase: list[BudgetStatus] | None = None,
    ) -> list[ConstraintAlert]:
        constraints = self.repository.list_active_constraints(user_id)
        inventory = self.inventory_service.query_inventory(user_id)
        statuses = statuses_after_purchase or self._statuses_after_purchase(user_id, items)
        alerts: list[ConstraintAlert] = []

        for constraint in constraints:
            if constraint.constraint_type == ConstraintType.INVENTORY_CAP:
                for item in items:
                    if not constraint_applies_to_item(constraint, item):
                        continue
                    current_quantity = next(
                        (
                            row.current_quantity
                            for row in inventory
                            if row.item_normalized == item.item_normalized
                        ),
                        0,
                    )
                    after_quantity = current_quantity + item.quantity
                    if (
                        constraint.operator == ConstraintOperator.COUNT_EXCEEDS
                        and after_quantity > constraint.threshold_value
                    ):
                        alerts.append(
                            ConstraintAlert(
                                constraint_id=constraint.constraint_id,
                                constraint_type=constraint.constraint_type,
                                message=render_constraint_message(
                                    constraint.message_template,
                                    item=item.item_normalized,
                                    count=after_quantity,
                                    current=current_quantity,
                                    threshold=constraint.threshold_value,
                                    over=after_quantity - constraint.threshold_value,
                                ),
                            )
                        )
            elif constraint.constraint_type == ConstraintType.HARD_BUDGET_LIMIT:
                for status in statuses:
                    if constraint.scope_tags and not budget_scope_matches_constraint(
                        status.budget_scope, constraint
                    ):
                        continue
                    spent_after = status.amount_spent
                    if (
                        constraint.operator == ConstraintOperator.EXCEEDS
                        and spent_after > constraint.threshold_value
                    ):
                        alerts.append(
                            ConstraintAlert(
                                constraint_id=constraint.constraint_id,
                                constraint_type=constraint.constraint_type,
                                message=render_constraint_message(
                                    constraint.message_template,
                                    scope=status.budget_scope,
                                    threshold=constraint.threshold_value,
                                    over=spent_after - constraint.threshold_value,
                                ),
                            )
                        )
            elif constraint.constraint_type == ConstraintType.PACE_ALERT:
                for status in statuses:
                    if (
                        constraint.operator == ConstraintOperator.FALLS_BELOW
                        and status.daily_pace < constraint.threshold_value
                    ):
                        alerts.append(
                            ConstraintAlert(
                                constraint_id=constraint.constraint_id,
                                constraint_type=constraint.constraint_type,
                                message=render_constraint_message(
                                    constraint.message_template,
                                    scope=status.budget_scope,
                                    pace=status.daily_pace,
                                    threshold=constraint.threshold_value,
                                ),
                                severity="info",
                            )
                        )
        return alerts

    def _statuses_after_purchase(self, user_id: str, items: list[ParsedItem]) -> list[BudgetStatus]:
        budgets = self.repository.list_active_budgets(user_id)
        current_statuses = {status.budget_id: status for status in self.get_budget_statuses(user_id)}
        statuses: list[BudgetStatus] = []
        for budget in budgets:
            proposed = sum(
                item.total_cost or 0
                for item in items
                if budget_matches_item(budget, item)
            )
            amount_spent = current_statuses[budget.budget_id].amount_spent + proposed
            statuses.append(status_from_spend(budget, amount_spent))
        return statuses


def period_for(period_type: PeriodType, now: date | None = None) -> BudgetPeriod:
    today = now or datetime.now(UTC).date()
    if period_type == PeriodType.WEEKLY:
        start = today.fromordinal(today.toordinal() - today.weekday())
        end = start.fromordinal(start.toordinal() + 6)
        return BudgetPeriod(start=start, end=end)
    if period_type == PeriodType.MONTHLY:
        start = today.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = date.fromordinal(next_month.toordinal() - 1)
        return BudgetPeriod(start=start, end=end)
    return BudgetPeriod(start=today, end=today)


def status_from_spend(budget: Budget, amount_spent: float) -> BudgetStatus:
    today = datetime.now(UTC).date()
    days_remaining = max((budget.period_end - max(today, budget.period_start)).days + 1, 0)
    amount_remaining = round(budget.budget_amount - amount_spent, 2)
    daily_pace = round(amount_remaining / days_remaining, 2) if days_remaining else amount_remaining
    pct_consumed = round(amount_spent / budget.budget_amount, 4) if budget.budget_amount else 0
    return BudgetStatus(
        budget_id=budget.budget_id,
        budget_scope=budget.budget_scope,
        budget_amount=budget.budget_amount,
        period_type=budget.period_type,
        rollover_enabled=budget.rollover_enabled,
        amount_spent=round(amount_spent, 2),
        amount_remaining=amount_remaining,
        daily_pace=daily_pace,
        days_remaining=days_remaining,
        pct_consumed=pct_consumed,
    )


def budget_matches_event(budget: Budget, event_tags: list[str]) -> bool:
    if budget.budget_scope == "all":
        return True
    return budget.budget_scope in event_tags


def budget_matches_item(budget: Budget, item: ParsedItem) -> bool:
    if budget.budget_scope == "all":
        return True
    return budget.budget_scope in item.suggested_tags or budget.budget_scope == item.item_normalized


def constraint_applies_to_item(constraint: Constraint, item: ParsedItem) -> bool:
    if constraint.item_normalized and constraint.item_normalized != item.item_normalized:
        return False
    if not constraint.scope_tags:
        return True
    return bool(set(constraint.scope_tags).intersection(item.suggested_tags))


def budget_scope_matches_constraint(scope: str, constraint: Constraint) -> bool:
    return not constraint.scope_tags or scope in constraint.scope_tags


def default_constraint_message(constraint_type: ConstraintType) -> str:
    if constraint_type == ConstraintType.INVENTORY_CAP:
        return "You already had {current} {item}. This puts you at {count}, {over} over your line of {threshold}."
    if constraint_type == ConstraintType.PACE_ALERT:
        return "{scope} budget pace drops to ${pace}/day. Your line is ${threshold}/day."
    return "{scope} would cross your ${threshold} limit by ${over}."


def render_constraint_message(template: str, **values: object) -> str:
    safe_values = {key: format_value(value) for key, value in values.items()}
    try:
        return template.format(**safe_values)
    except KeyError:
        return template


def format_value(value: object) -> object:
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return round(value, 2)
    return value
