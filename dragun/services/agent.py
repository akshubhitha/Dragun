"""
Dragun Gemini Agent — function-calling orchestrator.

The agent receives every chat message, decides which tools to call,
executes them against the real services, and generates the dragon reply.
No regex routing, no template strings — Gemini owns the whole flow.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from google import genai
from google.genai import types

from dragun.config import get_settings
from dragun.models import (
    BudgetCreateRequest,
    ConstraintCreateRequest,
    ConstraintOperator,
    ConstraintType,
    Event,
    EventType,
    PeriodType,
    User,
)
from dragun.services.parser import parse_text_fallback

if TYPE_CHECKING:
    from dragun.services.budget import BudgetService
    from dragun.services.inventory import InventoryService

logger = logging.getLogger(__name__)

# Per-user conversation history (in-memory, resets on server restart)
_conversation_history: dict[str, list[types.Content]] = {}

# Cached context: system instruction + tool declarations uploaded once per server start.
# Cached tokens cost ~25% of normal input token price — no need to resend 2K tokens every turn.
_schema_cache_name: str | None = None

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
- When the user corrects a mistake or says "I actually have X" or "change it to X" → call correct_inventory
- When the user says an item has the wrong tag/category or asks to change its category → call retag_item
- When the user says they got rid of, donated, sold, returned, lost, or threw away something → call remove_items
- For casual chat or questions → just reply, no tool needed

Always correct spelling in tool arguments — if the user says "shrt", pass "shirt"; "pant" for "pnts"; "shoes" for "shoees", etc. Normalize before calling any tool.

After calling tools, write a natural reply (2–4 sentences) as Dragun:
- Lead with what changed or what they now own
- Mention budget status if relevant
- Surface any patterns or alerts
- Never make up numbers not returned by the tools
- Never say "I recommend against" or moralize
"""


def _tool_declarations() -> list[types.Tool]:
    """Static tool schemas — same for every user. Used for context caching."""
    # Minimal stubs so _fn_to_declaration can introspect signatures/docstrings.
    def log_purchase(items_text: str, total_cost: float | None = None) -> None:
        """Log items the user just bought. items_text is a plain description like '3 shirts, 2 dresses'.
        total_cost is the total spent in dollars (optional)."""
    def set_inventory_baseline(items_text: str) -> None:
        """Record items the user already owns (not a purchase). items_text like 'I have 12 shirts, 6 pants'."""
    def get_inventory(item_filter: str | None = None) -> None:
        """Get the user's current inventory. Optionally filter by item name or tag."""
    def get_budget_status(scope: str | None = None) -> None:
        """Get current budget status. Optionally filter by scope/category."""
    def set_budget(scope: str, amount: float, period: str = "monthly") -> None:
        """Create or update a spending budget. scope is the category (e.g. 'clothing', 'dining', 'all').
        amount is in dollars. period is 'monthly' or 'weekly'."""
    def set_inventory_cap(item: str, max_count: int) -> None:
        """Set a cap on how many of an item the user wants to own. item is the item name, max_count is the limit."""
    def correct_inventory(item: str, correct_quantity: int) -> None:
        """Correct the quantity of an item the user already owns. Use when the user says they made a mistake
        or wants to set the exact count of something. item is the item name, correct_quantity is the true count."""
    def retag_item(item: str, tags: str) -> None:
        """Change the category tags on an inventory item. tags is a comma-separated list like 'clothing' or 'clothing,essentials'.
        Use when the user says an item is tagged wrong or asks to change its category."""
    def remove_items(items_text: str, reason: str = "discard") -> None:
        """Log removal of items from the hoard. Use when the user says they got rid of, donated, returned, lost,
        sold, or threw away items. items_text is like '2 shirts, 1 pair of jeans'. reason is 'discard', 'return', or 'consumed'."""

    return [types.Tool(function_declarations=[
        _fn_to_declaration(log_purchase),
        _fn_to_declaration(set_inventory_baseline),
        _fn_to_declaration(get_inventory),
        _fn_to_declaration(get_budget_status),
        _fn_to_declaration(set_budget),
        _fn_to_declaration(set_inventory_cap),
        _fn_to_declaration(correct_inventory),
        _fn_to_declaration(retag_item),
        _fn_to_declaration(remove_items),
    ])]


async def _get_schema_cache(client: genai.Client, model_name: str) -> str | None:
    """Return cached content name, creating it on first call. Returns None on failure."""
    global _schema_cache_name
    if _schema_cache_name:
        return _schema_cache_name
    try:
        cache = await client.aio.caches.create(
            model=model_name,
            config=types.CreateCachedContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                tools=_tool_declarations(),
                ttl="3600s",  # 1 hour — refresh on next cold start
            ),
        )
        _schema_cache_name = cache.name
        logger.info("Created Gemini context cache: %s", cache.name)
        return _schema_cache_name
    except Exception:
        logger.warning("Context caching unavailable — sending full schema each turn", exc_info=True)
        return None


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

    def correct_inventory(item: str, correct_quantity: int) -> dict[str, Any]:
        """Correct the quantity of an item the user already owns. Use when the user says they made a mistake
        or wants to set the exact count of something. item is the item name, correct_quantity is the true count."""
        try:
            item_normalized = item.lower().rstrip("s") if not item.lower().endswith("ss") else item.lower()
            # Get current quantity
            rows = inventory_service.query_inventory(user.user_id)
            current = next((r.current_quantity for r in rows if r.item_normalized == item_normalized), 0)
            delta = correct_quantity - current
            if delta == 0:
                return {"status": "no_change", "item": item_normalized, "quantity": correct_quantity}
            # Log a correction event with the delta
            correction_text = f"{abs(delta)} {item_normalized}"
            parsed = parse_text_fallback(correction_text)
            if parsed.items:
                parsed.items[0].quantity = abs(delta)
                if delta < 0:
                    # Negative delta — log as a removal by setting quantity negative
                    parsed.items[0].quantity = delta
                parsed.intent = "manual_inventory"  # type: ignore[assignment]
                inventory_service.log_items(user, parsed, input_source="correction")
            inventory = inventory_service.query_inventory(user.user_id)
            return {
                "status": "corrected",
                "item": item_normalized,
                "previous_quantity": current,
                "corrected_quantity": correct_quantity,
                "current_inventory": [
                    {"item": r.item_normalized, "quantity": r.current_quantity} for r in inventory[:15]
                ],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def remove_items(items_text: str, reason: str = "discard") -> dict[str, Any]:
        """Log removal of items from the hoard."""
        parsed = parse_text_fallback(items_text)
        if not parsed.items:
            return {"status": "error", "message": "Could not parse items from description."}
        reason_map = {"return": EventType.RETURN, "consumed": EventType.CONSUMPTION}
        event_type = reason_map.get(reason.lower(), EventType.DISCARD)
        events = []
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
                input_source="text",
                raw_input=items_text,
                event_timestamp=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            inventory_service.repository.create_event(event, item.suggested_tags)
            events.append(event)
        inventory = inventory_service.query_inventory(user.user_id)
        return {
            "status": "removed",
            "items_removed": [{"item": e.item_normalized, "quantity": e.quantity} for e in events],
            "current_inventory": [
                {"item": r.item_normalized, "quantity": r.current_quantity} for r in inventory[:15]
            ],
        }

    def retag_item(item: str, tags: str) -> dict[str, Any]:
        """Change the category tags on an inventory item. tags is a comma-separated list like 'clothing' or 'clothing,essentials'.
        Use when the user says an item is tagged wrong or asks to change its category."""
        try:
            item_normalized = item.lower().rstrip("s") if not item.lower().endswith("ss") else item.lower()
            new_tags = [t.strip().lower() for t in tags.split(",") if t.strip()]
            # Try exact match first, then singular
            rows = inventory_service.query_inventory(user.user_id)
            matched = next((r.item_normalized for r in rows if r.item_normalized == item_normalized), None)
            if not matched:
                matched = next((r.item_normalized for r in rows if item_normalized in r.item_normalized), None)
            if not matched:
                return {"status": "error", "message": f"Item '{item}' not found in inventory."}
            updated = inventory_service.retag_item(user.user_id, matched, new_tags)
            return {
                "status": "retagged",
                "item": matched,
                "new_tags": new_tags,
                "events_updated": updated,
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
            _fn_to_declaration(correct_inventory),
            _fn_to_declaration(retag_item),
        ])
    ], {
        "log_purchase": log_purchase,
        "set_inventory_baseline": set_inventory_baseline,
        "get_inventory": get_inventory,
        "get_budget_status": get_budget_status,
        "set_budget": set_budget,
        "set_inventory_cap": set_inventory_cap,
        "correct_inventory": correct_inventory,
        "retag_item": retag_item,
        "remove_items": remove_items,
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

    try:
        # Always use AI Studio API key — Vertex AI requires project-level model access grants
        client = genai.Client(api_key=settings.google_api_key)
        model_name = settings.gemini_model
        _tools, tool_fns = _make_tools(user, inventory_service, budget_service)

        # Try to use cached schema (system instruction + tool declarations uploaded once).
        # Falls back to sending them inline if caching is unavailable.
        cache_name = await _get_schema_cache(client, model_name)

        # Build conversation history for this user
        history = _conversation_history.get(user.user_id, [])
        history.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

        # Agentic loop — Gemini may call multiple tools before replying
        MAX_TURNS = 5
        for _ in range(MAX_TURNS):
            if cache_name:
                # Cached path: schema tokens cost ~25% — no system_instruction or tools in config
                gen_config = types.GenerateContentConfig(
                    cached_content=cache_name,
                    temperature=0.7,
                    max_output_tokens=512,
                )
            else:
                # Fallback: send full schema every turn
                gen_config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=_tools,
                    temperature=0.7,
                    max_output_tokens=512,
                )
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=history,
                config=gen_config,
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

    except Exception:
        logger.exception("Gemini agent failed (model=%s) — falling back to deterministic path", settings.gemini_model)
        return None


def clear_history(user_id: str) -> None:
    """Clear conversation history for a user (e.g. on logout)."""
    _conversation_history.pop(user_id, None)
