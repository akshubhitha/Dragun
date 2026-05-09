"""
Dragun Gemini Agent — function-calling orchestrator.

The agent receives every chat message, decides which tools to call,
executes them against the real services, and generates the dragon reply.
No regex routing, no template strings — Gemini owns the whole flow.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from google import genai
from google.genai import types

from dragun.config import get_settings
from dragun.models import (
    BudgetCreateRequest,
    ConstraintCreateRequest,
    ConstraintOperator,
    ConstraintType,
    PeriodType,
    User,
)
from dragun.services.parser import parse_text_fallback

if TYPE_CHECKING:
    from dragun.services.budget import BudgetService
    from dragun.services.inventory import InventoryService

# Per-user conversation history (in-memory, resets on server restart)
_conversation_history: dict[str, list[types.Content]] = {}

SYSTEM_INSTRUCTION = """You are Dragun, a personal consumption intelligence dragon. You guard the user's hoard.

Personality:
- Warm, direct, occasionally blunt — never judgmental or preachy
- Protective, not controlling — you show truth and let the user decide
- Concise — no filler, no corporate language
- Casual conversation is fine — greet back, answer questions, stay in character

Your job:
- When the user mentions buying something → call log_purchase
- When the user says what they already own → call set_inventory_baseline
- When the user asks what they have → call get_inventory
- When the user sets a budget → call set_budget
- When the user sets an inventory cap or limit → call set_inventory_cap
- When the user asks about budgets → call get_budget_status
- For casual chat or questions → just reply, no tool needed

After calling tools, write a natural reply (2–4 sentences) as Dragun:
- Lead with what changed or what they now own
- Mention budget status if relevant
- Surface any patterns or alerts
- Never make up numbers not returned by the tools
- Never say "I recommend against" or moralize
"""


def _make_tools(
    user: User,
    inventory_service: "InventoryService",
    budget_service: "BudgetService",
) -> list[types.Tool]:
    """Build Gemini function tools wired to real services for this user."""

    def log_purchase(items_text: str, total_cost: float | None = None) -> dict[str, Any]:
        """Log items the user just bought. items_text is a plain description like '3 shirts, 2 dresses'.
        total_cost is the total spent in dollars (optional)."""
        text = items_text
        if total_cost is not None:
            text = f"{items_text} — ${total_cost}"
        parsed = parse_text_fallback(text)
        if not parsed.items:
            return {"status": "error", "message": "Could not parse items from description."}
        events = inventory_service.log_items(user, parsed, input_source="text")
        inventory = inventory_service.query_inventory(user.user_id)
        return {
            "status": "logged",
            "items_logged": [
                {"item": e.item_normalized, "quantity": e.quantity, "total_cost": e.total_cost}
                for e in events
            ],
            "current_inventory": [
                {"item": r.item_normalized, "quantity": r.current_quantity, "tags": r.tags}
                for r in inventory[:15]
            ],
        }

    def set_inventory_baseline(items_text: str) -> dict[str, Any]:
        """Record items the user already owns (not a purchase). items_text like 'I have 12 shirts, 6 pants'."""
        parsed = parse_text_fallback(items_text)
        if not parsed.items:
            return {"status": "error", "message": "Could not parse items."}
        parsed.intent = "manual_inventory"  # type: ignore[assignment]
        events = inventory_service.log_items(user, parsed, input_source="manual")
        inventory = inventory_service.query_inventory(user.user_id)
        return {
            "status": "baseline_set",
            "items_recorded": [{"item": e.item_normalized, "quantity": e.quantity} for e in events],
            "current_inventory": [
                {"item": r.item_normalized, "quantity": r.current_quantity} for r in inventory[:15]
            ],
        }

    def get_inventory(item_filter: str | None = None) -> dict[str, Any]:
        """Get the user's current inventory. Optionally filter by item name or tag."""
        rows = inventory_service.query_inventory(user.user_id)
        if item_filter:
            f = item_filter.lower()
            rows = [r for r in rows if f in r.item_normalized or any(f in t for t in r.tags)]
        if not rows:
            return {"inventory": [], "message": "The hoard is empty."}
        return {
            "inventory": [
                {
                    "item": r.item_normalized,
                    "quantity": r.current_quantity,
                    "tags": r.tags,
                    "avg_unit_cost": r.avg_unit_cost,
                    "last_purchased": r.last_purchased.isoformat() if r.last_purchased else None,
                }
                for r in rows
            ],
            "total_unique_items": len(rows),
        }

    def get_budget_status(scope: str | None = None) -> dict[str, Any]:
        """Get current budget status. Optionally filter by scope/category."""
        statuses = budget_service.get_budget_statuses(user.user_id)
        if scope:
            statuses = [s for s in statuses if scope.lower() in s.budget_scope.lower()]
        if not statuses:
            return {"budgets": [], "message": "No budgets set yet."}
        return {
            "budgets": [
                {
                    "scope": s.budget_scope,
                    "amount_remaining": round(s.amount_remaining, 2),
                    "amount_spent": round(s.amount_spent, 2),
                    "daily_pace": round(s.daily_pace, 2),
                    "days_remaining": s.days_remaining,
                    "pct_consumed": round(s.pct_consumed * 100, 1),
                }
                for s in statuses
            ]
        }

    def set_budget(scope: str, amount: float, period: str = "monthly") -> dict[str, Any]:
        """Create or update a spending budget. scope is the category (e.g. 'clothing', 'dining', 'all').
        amount is in dollars. period is 'monthly' or 'weekly'."""
        try:
            period_type = PeriodType.WEEKLY if period.lower() == "weekly" else PeriodType.MONTHLY
            budget = budget_service.create_budget(
                user.user_id,
                BudgetCreateRequest(
                    budget_scope=scope.lower(),
                    scope_tags=[] if scope.lower() == "all" else [scope.lower()],
                    budget_amount=float(amount),
                    period_type=period_type,
                ),
            )
            status = budget_service.get_budget_status(budget)
            return {
                "status": "created",
                "scope": budget.budget_scope,
                "amount": budget.budget_amount,
                "period": budget.period_type,
                "remaining": round(status.amount_remaining, 2),
                "days_remaining": status.days_remaining,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_inventory_cap(item: str, max_count: int) -> dict[str, Any]:
        """Set a cap on how many of an item the user wants to own. item is the item name, max_count is the limit."""
        try:
            item_normalized = item.lower().rstrip("s") if not item.lower().endswith("ss") else item.lower()
            constraint = budget_service.create_constraint(
                user.user_id,
                ConstraintCreateRequest(
                    constraint_type=ConstraintType.INVENTORY_CAP,
                    item_normalized=item_normalized,
                    operator=ConstraintOperator.COUNT_EXCEEDS,
                    threshold_value=float(max_count),
                    scope_tags=[],
                ),
            )
            return {
                "status": "guard_set",
                "item": item_normalized,
                "max_count": max_count,
                "constraint_id": constraint.constraint_id,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return [
        types.Tool(function_declarations=[
            _fn_to_declaration(log_purchase),
            _fn_to_declaration(set_inventory_baseline),
            _fn_to_declaration(get_inventory),
            _fn_to_declaration(get_budget_status),
            _fn_to_declaration(set_budget),
            _fn_to_declaration(set_inventory_cap),
        ])
    ], {
        "log_purchase": log_purchase,
        "set_inventory_baseline": set_inventory_baseline,
        "get_inventory": get_inventory,
        "get_budget_status": get_budget_status,
        "set_budget": set_budget,
        "set_inventory_cap": set_inventory_cap,
    }


def _fn_to_declaration(fn) -> types.FunctionDeclaration:
    """Build a Gemini FunctionDeclaration from a Python function's docstring and annotations."""
    import inspect
    sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        ann = param.annotation
        prop: dict[str, Any] = {}
        if ann in (str, str | None):
            prop["type"] = "STRING"
        elif ann in (float, float | None, int, int | None):
            prop["type"] = "NUMBER"
        elif ann is bool:
            prop["type"] = "BOOLEAN"
        else:
            prop["type"] = "STRING"
        if param.default is inspect.Parameter.empty:
            required.append(name)
        props[name] = prop

    schema = types.Schema(type="OBJECT", properties={k: types.Schema(**v) for k, v in props.items()})
    if required:
        schema.required = required

    return types.FunctionDeclaration(
        name=fn.__name__,
        description=(fn.__doc__ or "").strip().split("\n")[0],
        parameters=schema,
    )


async def run_agent(
    user_message: str,
    user: User,
    inventory_service: "InventoryService",
    budget_service: "BudgetService",
) -> str:
    """
    Run the Dragun Gemini agent for one turn.
    Maintains per-user conversation history in memory.
    Returns the agent's reply text.
    """
    settings = get_settings()
    if not settings.google_api_key:
        return None  # type: ignore[return-value]

    client = genai.Client(api_key=settings.google_api_key)
    tools, tool_fns = _make_tools(user, inventory_service, budget_service)

    # Build conversation history for this user
    history = _conversation_history.get(user.user_id, [])
    history.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

    # Agentic loop — Gemini may call multiple tools before replying
    MAX_TURNS = 5
    for _ in range(MAX_TURNS):
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=history,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=tools,
                temperature=0.7,
                max_output_tokens=512,
            ),
        )

        candidate = response.candidates[0]
        history.append(types.Content(role="model", parts=candidate.content.parts))

        # Check if Gemini wants to call any tools
        tool_calls = [p for p in candidate.content.parts if p.function_call is not None]
        if not tool_calls:
            # No tool calls — Gemini is done, return the text reply
            _conversation_history[user.user_id] = history[-20:]  # keep last 20 turns
            text = "".join(p.text for p in candidate.content.parts if p.text)
            return text.strip()

        # Execute all requested tool calls and feed results back
        tool_results = []
        for part in tool_calls:
            fn_name = part.function_call.name
            fn_args = dict(part.function_call.args or {})
            fn = tool_fns.get(fn_name)
            if fn:
                try:
                    result = fn(**fn_args)
                except Exception as e:
                    result = {"error": str(e)}
            else:
                result = {"error": f"Unknown tool: {fn_name}"}

            tool_results.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fn_name,
                        response={"result": result},
                    )
                )
            )

        history.append(types.Content(role="user", parts=tool_results))

    # Fallback if loop exhausted
    _conversation_history[user.user_id] = history[-20:]
    return "The hoard is updated. Ask me anything about your inventory or budgets."


def clear_history(user_id: str) -> None:
    """Clear conversation history for a user (e.g. on logout)."""
    _conversation_history.pop(user_id, None)
