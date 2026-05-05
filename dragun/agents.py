"""Google Cloud ADK agent graph for Dragun.

The HTTP app uses deterministic service code for the Phase 1 write path so local
tests and demos are reliable. These ADK agents expose the same roles and tools
for Agent Engine / ADK runtimes and future conversational expansion.
"""

from __future__ import annotations

from typing import Any

try:
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool
except Exception:  # pragma: no cover - lets local tests run before deps install
    Agent = None  # type: ignore[assignment]
    FunctionTool = None  # type: ignore[assignment]

from dragun.config import get_settings


settings = get_settings()


def _tool_result(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"tool": name, "status": "available_via_http_service", "payload": payload}


def write_event(raw_input: str, user_id: str) -> dict[str, Any]:
    return _tool_result("write_event", {"raw_input": raw_input, "user_id": user_id})


def query_inventory(user_id: str, item_name: str | None = None) -> dict[str, Any]:
    return _tool_result("query_inventory", {"user_id": user_id, "item_name": item_name})


def query_velocity(user_id: str, item_name: str | None = None) -> dict[str, Any]:
    return _tool_result("query_velocity", {"user_id": user_id, "item_name": item_name})


def update_inventory_baseline(raw_input: str, user_id: str) -> dict[str, Any]:
    return _tool_result("update_inventory_baseline", {"raw_input": raw_input, "user_id": user_id})


def create_budget(user_id: str, scope: str, amount: float, period_type: str = "monthly") -> dict[str, Any]:
    return _tool_result(
        "create_budget",
        {"user_id": user_id, "scope": scope, "amount": amount, "period_type": period_type},
    )


def get_budget_status(user_id: str, scope: str | None = None) -> dict[str, Any]:
    return _tool_result("get_budget_status", {"user_id": user_id, "scope": scope})


def evaluate_purchase(user_id: str, raw_input: str) -> dict[str, Any]:
    return _tool_result("evaluate_purchase", {"user_id": user_id, "raw_input": raw_input})


def create_constraint(
    user_id: str,
    constraint_type: str,
    threshold_value: float,
    item_or_scope: str,
) -> dict[str, Any]:
    return _tool_result(
        "create_constraint",
        {
            "user_id": user_id,
            "constraint_type": constraint_type,
            "threshold_value": threshold_value,
            "item_or_scope": item_or_scope,
        },
    )


def check_constraints(user_id: str, raw_input: str) -> dict[str, Any]:
    return _tool_result("check_constraints", {"user_id": user_id, "raw_input": raw_input})


def get_spending_trends(user_id: str) -> dict[str, Any]:
    return _tool_result("get_spending_trends", {"user_id": user_id})


def get_inventory_trends(user_id: str) -> dict[str, Any]:
    return _tool_result("get_inventory_trends", {"user_id": user_id})


def get_velocity_anomalies(user_id: str) -> dict[str, Any]:
    return _tool_result("get_velocity_anomalies", {"user_id": user_id})


def compare_periods(user_id: str, scope: str) -> dict[str, Any]:
    return _tool_result("compare_periods", {"user_id": user_id, "scope": scope})


def generate_summary(user_id: str) -> dict[str, Any]:
    return _tool_result("generate_summary", {"user_id": user_id})


def build_agent_graph() -> Any:
    if Agent is None or FunctionTool is None:
        return None

    input_parser = Agent(
        name="input_parser",
        model=settings.gemini_model,
        description="Extracts item, cost, family member, and tag data from user input.",
        instruction=(
            "Parse raw text into strict JSON: items with description, quantity, unit_cost, "
            "total_cost, lifespan_type, suggested_tags, and family_member when present. "
            "Normalize shorthand like deo to deodorant. Infer per-item costs when only "
            "one total is provided."
        ),
    )

    inventory_agent = Agent(
        name="inventory_agent",
        model=settings.gemini_model,
        description="Records item events and answers inventory or velocity questions.",
        instruction=(
            "Manage the event-sourced inventory. Purchases, gifts, and manual inventory "
            "add quantity. Consumption, returns, and discards subtract quantity."
        ),
        tools=[
            FunctionTool(write_event),
            FunctionTool(query_inventory),
            FunctionTool(query_velocity),
            FunctionTool(update_inventory_baseline),
        ],
    )

    budget_agent = Agent(
        name="budget_agent",
        model=settings.gemini_model,
        description="Creates budgets and evaluates purchases against budgets and constraints.",
        instruction=(
            "Give direct budget status and constraint alerts. Never block purchases or "
            "moralize. Combine all triggered alerts in a concise response."
        ),
        tools=[
            FunctionTool(create_budget),
            FunctionTool(get_budget_status),
            FunctionTool(evaluate_purchase),
            FunctionTool(create_constraint),
            FunctionTool(check_constraints),
        ],
    )

    insight_agent = Agent(
        name="insight_agent",
        model=settings.gemini_model,
        description="Generates trend and pattern insights from event history.",
        instruction=(
            "Surface concise consumption patterns: spending trends, inventory accumulation, "
            "velocity changes, period comparisons, and summaries."
        ),
        tools=[
            FunctionTool(get_spending_trends),
            FunctionTool(get_inventory_trends),
            FunctionTool(get_velocity_anomalies),
            FunctionTool(compare_periods),
            FunctionTool(generate_summary),
        ],
    )

    return Agent(
        name="dragun_coordinator",
        model=settings.gemini_model,
        description="Root Dragun personal consumption intelligence agent.",
        instruction=(
            "You are Dragun, a personal consumption intelligence agent. You guard the "
            "user's hoard. Be warm, direct, occasionally blunt, never judgmental. Speak "
            "concisely. When the user tells you about a purchase, respond with what they "
            "now own, where their budget stands, and relevant patterns. Ask one clarifying "
            "question maximum for ambiguity."
        ),
        sub_agents=[input_parser, inventory_agent, budget_agent, insight_agent],
    )


root_agent = build_agent_graph()

