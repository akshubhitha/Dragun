"""ADK multi-agent graph for Dragun."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from dragun.agents.toolkit import DragunToolkit
from dragun.config import settings


def build_dragun_agent(toolkit: DragunToolkit) -> LlmAgent:
    """Create the Dragun coordinator with Phase 1 sub-agents."""
    input_parser = LlmAgent(
        model=settings.model_name,
        name="input_parser",
        description=(
            "Parses raw user input into structured items with quantity, pricing, "
            "normalized names, lifespan type, and suggested tags."
        ),
        instruction=(
            "You parse user shopping input into structured JSON.\n"
            "Use parse_input for all extraction tasks.\n"
            "Output concise structured results and do not invent fields."
        ),
        tools=[toolkit.parse_input],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )

    inventory_agent = LlmAgent(
        model=settings.model_name,
        name="inventory_agent",
        description=(
            "Manages append-only event logging and inventory calculations. "
            "Answers what the user currently owns and baseline updates."
        ),
        instruction=(
            "Use write_event to log purchases/baselines. "
            "Use query_inventory for current counts. "
            "Use query_velocity for purchase cadence when relevant. "
            "Use update_inventory_baseline for manual inventory dumps."
        ),
        tools=[
            toolkit.write_event,
            toolkit.query_inventory,
            toolkit.query_velocity,
            toolkit.update_inventory_baseline,
        ],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )

    budget_agent = LlmAgent(
        model=settings.model_name,
        name="budget_agent",
        description=(
            "Creates budgets, evaluates purchase impact, and checks active "
            "constraints such as inventory caps and hard budget limits."
        ),
        instruction=(
            "Use create_budget and get_budget_status for budget management. "
            "Use evaluate_purchase to project impact of a proposed purchase. "
            "Use create_constraint and check_constraints to enforce user-defined guardrails."
        ),
        tools=[
            toolkit.create_budget,
            toolkit.get_budget_status,
            toolkit.evaluate_purchase,
            toolkit.create_constraint,
            toolkit.check_constraints,
        ],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )

    insight_agent = LlmAgent(
        model=settings.model_name,
        name="insight_agent",
        description=(
            "Produces trend and summary insights: spending changes, inventory "
            "accumulation, and velocity anomalies."
        ),
        instruction=(
            "Use get_spending_trends, get_inventory_trends, get_velocity_anomalies, "
            "compare_periods, and generate_summary to produce concise insights."
        ),
        tools=[
            toolkit.get_spending_trends,
            toolkit.get_inventory_trends,
            toolkit.get_velocity_anomalies,
            toolkit.compare_periods,
            toolkit.generate_summary,
        ],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )

    coordinator_instruction = """
You are Dragun, a personal consumption intelligence agent. You guard the user's hoard.

Tone and personality:
- Warm, direct, occasionally blunt, never judgmental.
- Concise. No filler. No corporate language.
- Never block purchases. Never moralize. Show the truth and let the user decide.
- Ask at most one clarifying question when input is ambiguous.

Routing rules:
- For item logging or proposed purchases, use inventory_agent and budget_agent tools.
- For parsing tricky natural language lists, use input_parser.
- For trend or pacing context, use insight_agent when relevant.

Response rules for purchase logs:
- Always include: (1) what they now own, (2) budget standing, and (3) relevant patterns.
- If constraints trigger, surface them clearly and neutrally.
"""

    return LlmAgent(
        model=settings.model_name,
        name="dragun_coordinator",
        description=(
            "Root Dragun agent. Routes user intents to specialized sub-agents and "
            "synthesizes concise decision-support responses."
        ),
        instruction=coordinator_instruction.strip(),
        sub_agents=[input_parser, inventory_agent, budget_agent, insight_agent],
    )

