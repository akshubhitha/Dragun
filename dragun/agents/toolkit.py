"""ADK tool functions mapped to Dragun domain services."""

from __future__ import annotations

from datetime import date
from typing import Any

from google.adk.tools import ToolContext

from dragun.services.engine import DragunEngine


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


class DragunToolkit:
    """Collection of callable ADK tools used by Dragun sub-agents."""

    def __init__(self, engine: DragunEngine) -> None:
        self.engine = engine

    def _user_id(self, tool_context: ToolContext) -> str:
        user_id = tool_context.state.get("user_id")
        if not user_id:
            raise ValueError("No authenticated user in session state.")
        return str(user_id)

    def parse_input(self, raw_input: str, tool_context: ToolContext) -> dict:
        """
        Parse user text into structured item data.

        Args:
            raw_input: Free-form text such as "3 shirts, 2 dresses, 50 bucks".
            tool_context: ADK tool context.
        """
        _ = self._user_id(tool_context)
        parsed = self.engine.parse_input(raw_input)
        return {"status": "success", **parsed}

    def write_event(self, raw_input: str, tool_context: ToolContext) -> dict:
        """
        Persist purchase or manual inventory events from text input.

        Args:
            raw_input: User message containing items.
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        logged = self.engine.log_text_input(user_id=user_id, raw_input=raw_input, input_source="text")
        inventory = self.engine.compute_inventory_state(user_id=user_id)
        budget_status = self.engine.get_budget_status(user_id=user_id)
        alerts = self.engine.check_constraints(user_id=user_id, proposed_items=logged["items"])
        return {
            "status": "success",
            "logged": logged,
            "inventory": inventory[:10],
            "budget_status": budget_status,
            "alerts": alerts,
        }

    def query_inventory(
        self,
        item_name: str | None = None,
        tags: list[str] | None = None,
        tool_context: ToolContext | None = None,
    ) -> dict:
        """
        Query inventory state for the authenticated user.

        Args:
            item_name: Optional normalized item name filter.
            tags: Optional list of tag filters.
            tool_context: ADK tool context.
        """
        if tool_context is None:
            raise ValueError("tool_context is required.")
        user_id = self._user_id(tool_context)
        rows = self.engine.compute_inventory_state(user_id=user_id, item_name=item_name, tags=tags or [])
        return {"status": "success", "inventory": rows}

    def query_velocity(self, item_name: str, tool_context: ToolContext) -> dict:
        """
        Compute purchase velocity metrics for one item.

        Args:
            item_name: Item name to analyze.
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        velocity = self.engine.query_velocity(user_id=user_id, item_name=item_name)
        return {"status": "success", "velocity": velocity}

    def update_inventory_baseline(self, raw_input: str, tool_context: ToolContext) -> dict:
        """
        Record a manual inventory baseline from free-form text.

        Args:
            raw_input: Baseline text like "I have 12 shirts, 6 pants".
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        if not raw_input.strip().lower().startswith(("i have", "we have")):
            raw_input = f"I have {raw_input.strip()}"
        logged = self.engine.log_text_input(user_id=user_id, raw_input=raw_input, input_source="manual")
        return {"status": "success", "logged": logged}

    def create_budget(
        self,
        budget_scope: str,
        budget_amount: float,
        period_type: str = "monthly",
        scope_tags: list[str] | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        rollover_enabled: bool = False,
        tool_context: ToolContext | None = None,
    ) -> dict:
        """
        Create a budget rule.

        Args:
            budget_scope: Budget scope, e.g. "all" or "clothing".
            budget_amount: Total budget amount for the period.
            period_type: weekly, monthly, or custom.
            scope_tags: Optional tag IDs/names covered by budget.
            period_start: Optional ISO date for custom period start.
            period_end: Optional ISO date for custom period end.
            rollover_enabled: Whether rollover is enabled.
            tool_context: ADK tool context.
        """
        if tool_context is None:
            raise ValueError("tool_context is required.")
        user_id = self._user_id(tool_context)
        budget = self.engine.create_budget(
            user_id=user_id,
            budget_scope=budget_scope,
            scope_tags=scope_tags or [],
            budget_amount=budget_amount,
            period_type=period_type,
            period_start=_parse_date(period_start),
            period_end=_parse_date(period_end),
            rollover_enabled=rollover_enabled,
        )
        return {"status": "success", "budget": budget}

    def get_budget_status(self, tool_context: ToolContext) -> dict:
        """
        Return computed budget status for active budgets.

        Args:
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        return {"status": "success", "budgets": self.engine.get_budget_status(user_id=user_id)}

    def evaluate_purchase(self, raw_input: str, tool_context: ToolContext) -> dict:
        """
        Evaluate a proposed purchase against active budgets.

        Args:
            raw_input: Text describing a proposed purchase.
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        parsed = self.engine.parse_input(raw_input)
        impacts = self.engine.evaluate_purchase(user_id=user_id, proposed_items=parsed["items"])
        return {"status": "success", "parsed": parsed, "budget_impacts": impacts}

    def create_constraint(
        self,
        constraint_type: str,
        threshold_value: float,
        operator: str = "exceeds",
        scope_tags: list[str] | None = None,
        message_template: str | None = None,
        tool_context: ToolContext | None = None,
    ) -> dict:
        """
        Create a new user constraint rule.

        Args:
            constraint_type: hard_budget_limit, inventory_cap, trend_alert, velocity_warning, pace_alert.
            threshold_value: Threshold value for evaluation.
            operator: Comparison operator label.
            scope_tags: Optional applicable tag scope.
            message_template: Optional custom output template.
            tool_context: ADK tool context.
        """
        if tool_context is None:
            raise ValueError("tool_context is required.")
        user_id = self._user_id(tool_context)
        constraint = self.engine.create_constraint(
            user_id=user_id,
            constraint_type=constraint_type,
            scope_tags=scope_tags or [],
            operator=operator,
            threshold_value=threshold_value,
            message_template=message_template,
        )
        return {"status": "success", "constraint": constraint}

    def check_constraints(self, raw_input: str, tool_context: ToolContext) -> dict:
        """
        Check proposed purchase against all active constraints.

        Args:
            raw_input: Text describing a proposed purchase.
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        parsed = self.engine.parse_input(raw_input)
        alerts = self.engine.check_constraints(user_id=user_id, proposed_items=parsed["items"])
        return {"status": "success", "parsed": parsed, "alerts": alerts}

    def get_spending_trends(self, tool_context: ToolContext) -> dict:
        """
        Analyze high-level spending trends.

        Args:
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        return {"status": "success", "trends": self.engine.get_spending_trends(user_id=user_id)}

    def get_inventory_trends(self, tool_context: ToolContext) -> dict:
        """
        Analyze inventory accumulation trends by item.

        Args:
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        inventory = self.engine.compute_inventory_state(user_id=user_id)
        sorted_inventory = sorted(inventory, key=lambda row: row.get("current_quantity", 0), reverse=True)
        return {"status": "success", "inventory_trends": sorted_inventory[:10]}

    def get_velocity_anomalies(self, tool_context: ToolContext) -> dict:
        """
        Identify items with accelerating/decelerating purchase cadence.

        Args:
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        inventory = self.engine.compute_inventory_state(user_id=user_id)
        anomalies: list[dict[str, Any]] = []
        for row in inventory:
            velocity = self.engine.query_velocity(user_id=user_id, item_name=row["item_normalized"])
            if velocity["trend_direction"] in {"accelerating", "decelerating"}:
                anomalies.append(velocity)
        return {"status": "success", "velocity_anomalies": anomalies}

    def compare_periods(
        self,
        period_a_start: str,
        period_a_end: str,
        period_b_start: str,
        period_b_end: str,
        tool_context: ToolContext,
    ) -> dict:
        """
        Compare total spending between two periods.

        Args:
            period_a_start: First period start date (ISO).
            period_a_end: First period end date (ISO).
            period_b_start: Second period start date (ISO).
            period_b_end: Second period end date (ISO).
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        events = self.engine.events_repo.list_events_for_user(user_id=user_id)

        a_start = date.fromisoformat(period_a_start)
        a_end = date.fromisoformat(period_a_end)
        b_start = date.fromisoformat(period_b_start)
        b_end = date.fromisoformat(period_b_end)

        period_a_total = self.engine._sum_spend(events, a_start, a_end)  # noqa: SLF001
        period_b_total = self.engine._sum_spend(events, b_start, b_end)  # noqa: SLF001
        delta = period_b_total - period_a_total
        pct = (delta / period_a_total * 100.0) if period_a_total else 0.0
        return {
            "status": "success",
            "period_a_total": round(period_a_total, 2),
            "period_b_total": round(period_b_total, 2),
            "delta": round(delta, 2),
            "pct_change": round(pct, 2),
        }

    def generate_summary(self, tool_context: ToolContext) -> dict:
        """
        Generate a compact periodic summary.

        Args:
            tool_context: ADK tool context.
        """
        user_id = self._user_id(tool_context)
        return {"status": "success", "summary": self.engine.generate_summary(user_id=user_id)}

