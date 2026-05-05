"""FastAPI application for Dragun Phase 1."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dragun.agent_runtime import get_dragun_app
from dragun.schemas.models import (
    BudgetCreateRequest,
    ChatRequest,
    ChatResponse,
    ConstraintCreateRequest,
    RegisterRequest,
    RegisterResponse,
)

app = FastAPI(title="Dragun", version="0.1.0")
app.mount("/static", StaticFiles(directory="dragun/static"), name="static")
templates = Jinja2Templates(directory="dragun/templates")


def _fallback_dragon_reply(logged: dict, budget_preview: list[dict], alerts: list[dict]) -> str:
    items = logged.get("items") or []
    inventory_items = logged.get("inventory") or []
    inventory_bits = []
    for row in inventory_items[:5]:
        inventory_bits.append(f"{row['item_normalized']}: {row['current_quantity']}")

    budget_bits = []
    for budget in budget_preview[:3]:
        budget_bits.append(
            f"{budget['budget_scope']} has ${budget['amount_remaining']:.2f} left "
            f"({budget['daily_pace']:.2f}/day for {budget['days_remaining']} days)"
        )

    lines = []
    if items:
        lines.append(f"Logged {len(items)} item(s).")
    if inventory_bits:
        lines.append("Inventory now -> " + "; ".join(inventory_bits))
    if budget_bits:
        lines.append("Budget check -> " + "; ".join(budget_bits))
    if alerts:
        lines.append("Constraint flags -> " + "; ".join(alert["message"] for alert in alerts[:3]))
    if not lines:
        lines.append("I couldn't parse that cleanly. Give me a tighter item list and total.")
    return " ".join(lines)


def _message_looks_like_budget_setup(message: str) -> bool:
    lowered = message.lower()
    return ("budget" in lowered and "$" in lowered) or lowered.startswith("set budget")


def _message_looks_like_constraint_setup(message: str) -> bool:
    lowered = message.lower()
    return any(
        phrase in lowered
        for phrase in ["constraint", "cap", "don't let me", "do not let me", "warn me if"]
    )


def _message_looks_like_item_logging(message: str) -> bool:
    lowered = message.lower().strip()
    if lowered.startswith(("i have", "we have")):
        return True
    if any(token in lowered for token in ["$", "bucks", "dollars"]):
        return True
    import re

    return bool(re.search(r"\b\d+\s+[a-zA-Z]", lowered))


def _attempt_local_query_response(*, dragun, user_id: str, message: str) -> str | None:
    lowered = message.lower().strip()
    if "budget" in lowered and any(token in lowered for token in ["status", "left", "remaining", "pace"]):
        budgets = dragun.engine.get_budget_status(user_id=user_id)
        if not budgets:
            return "No active budgets yet. Set one and I’ll track your burn rate."
        lines = []
        for budget in budgets[:3]:
            lines.append(
                f"{budget['budget_scope']}: ${budget['amount_remaining']:.2f} left, "
                f"${budget['daily_pace']:.2f}/day for {budget['days_remaining']} days."
            )
        return " ".join(lines)

    if any(phrase in lowered for phrase in ["how many", "do i have", "inventory", "what do i own"]):
        import re

        match = re.search(r"how many\s+([a-zA-Z\s]+)\??", lowered)
        item_name = match.group(1).strip().rstrip("?") if match else None
        inventory = dragun.engine.compute_inventory_state(user_id=user_id, item_name=item_name)
        if not inventory:
            return "Hoard check: nothing logged for that item yet."
        lines = [f"{row['item_normalized']}: {row['current_quantity']}" for row in inventory[:5]]
        return "Hoard check -> " + "; ".join(lines)
    return None


def _attempt_inline_budget_setup(*, dragun, user_id: str, message: str) -> str | None:
    lowered = message.lower().strip()
    if not _message_looks_like_budget_setup(lowered):
        return None

    import re

    amount_match = re.search(r"\$?\s*(\d+(?:\.\d+)?)", lowered)
    if not amount_match:
        return None
    amount = float(amount_match.group(1))

    period_type = "monthly"
    if "weekly" in lowered:
        period_type = "weekly"
    elif "custom" in lowered:
        period_type = "custom"

    scope = "all"
    scope_tags: list[str] = []
    for candidate in ["clothing", "dining", "food", "groceries", "wellness"]:
        if candidate in lowered:
            scope = candidate
            scope_tags = [candidate]
            break

    budget = dragun.engine.create_budget(
        user_id=user_id,
        budget_scope=scope,
        scope_tags=scope_tags,
        budget_amount=amount,
        period_type=period_type,
        period_start=None,
        period_end=None,
        rollover_enabled=False,
    )
    return (
        f"Budget set. {budget['budget_scope']} gets ${budget['budget_amount']:.2f} "
        f"for {budget['period_type']} ({budget['period_start']} to {budget['period_end']})."
    )


def _attempt_inline_constraint_setup(*, dragun, user_id: str, message: str) -> str | None:
    lowered = message.lower().strip()
    if not _message_looks_like_constraint_setup(lowered):
        return None

    import re

    number_match = re.search(r"(\d+(?:\.\d+)?)", lowered)
    if not number_match:
        return None
    threshold = float(number_match.group(1))

    constraint_type = "inventory_cap"
    scope_tags: list[str] = []
    operator = "count_exceeds"
    if "budget" in lowered or "$" in lowered:
        constraint_type = "hard_budget_limit"
        operator = "exceeds"
    elif "pace" in lowered or "/day" in lowered:
        constraint_type = "pace_alert"
        operator = "falls_below"

    for candidate in ["clothing", "dining", "food", "groceries", "wellness", "shirts", "shoes"]:
        if candidate in lowered:
            normalized = "clothing" if candidate in {"shirts", "shoes"} else candidate
            scope_tags = [normalized]
            break

    constraint = dragun.engine.create_constraint(
        user_id=user_id,
        constraint_type=constraint_type,
        scope_tags=scope_tags,
        operator=operator,
        threshold_value=threshold,
        message_template=None,
    )
    return (
        f"Constraint set. {constraint['constraint_type']} with threshold "
        f"{constraint['threshold_value']} on {constraint.get('scope_tags') or ['all']}."
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/api/register", response_model=RegisterResponse)
async def register(payload: RegisterRequest) -> RegisterResponse:
    dragun = get_dragun_app()
    try:
        user = dragun.engine.register_user(
            handle=payload.handle,
            passkey=payload.passkey,
            zip_code=payload.zip_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RegisterResponse(
        user_id=user["user_id"],
        handle=user["handle"],
        created_at=user["created_at"],
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    dragun = get_dragun_app()
    try:
        user = dragun.engine.authenticate(handle=payload.handle, passkey=payload.passkey)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    session_id = await dragun.ensure_session(user_id=user["user_id"], session_id=payload.session_id)

    response_text = ""
    try:
        response_text = await dragun.run_chat(
            user_id=user["user_id"],
            session_id=session_id,
            message=payload.message,
        )
    except Exception:
        response_text = ""

    inventory_preview = dragun.engine.compute_inventory_state(user_id=user["user_id"])[:10]
    budget_preview = dragun.engine.get_budget_status(user_id=user["user_id"])

    if not response_text:
        inline_budget_response = _attempt_inline_budget_setup(
            dragun=dragun, user_id=user["user_id"], message=payload.message
        )
        inline_constraint_response = _attempt_inline_constraint_setup(
            dragun=dragun, user_id=user["user_id"], message=payload.message
        )
        query_response = _attempt_local_query_response(
            dragun=dragun, user_id=user["user_id"], message=payload.message
        )

        if inline_budget_response:
            response_text = inline_budget_response
        elif inline_constraint_response:
            response_text = inline_constraint_response
        elif query_response:
            response_text = query_response
        elif not _message_looks_like_item_logging(payload.message):
            response_text = (
                "I can log items, set budgets, and check constraints. "
                "Try: '3 shirts, 50 bucks' or 'set budget clothing 200 monthly'."
            )
        else:
            # Local fallback keeps the app usable if Gemini credentials are missing.
            logged = dragun.engine.log_text_input(
                user_id=user["user_id"],
                raw_input=payload.message,
                input_source="text",
            )
            inventory_preview = dragun.engine.compute_inventory_state(user_id=user["user_id"])[:10]
            budget_preview = dragun.engine.get_budget_status(user_id=user["user_id"])
            alerts = dragun.engine.check_constraints(user_id=user["user_id"], proposed_items=logged["items"])
            response_text = _fallback_dragon_reply(
                {
                    "items": logged["items"],
                    "inventory": inventory_preview,
                },
                budget_preview,
                alerts,
            )

    return ChatResponse(
        session_id=session_id,
        response=response_text,
        inventory_preview=inventory_preview,
        budget_preview=budget_preview,
    )


@app.post("/api/budgets")
async def create_budget(payload: BudgetCreateRequest) -> dict:
    dragun = get_dragun_app()
    try:
        user = dragun.engine.authenticate(handle=payload.handle, passkey=payload.passkey)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    budget = dragun.engine.create_budget(
        user_id=user["user_id"],
        budget_scope=payload.budget_scope,
        scope_tags=payload.scope_tags,
        budget_amount=payload.budget_amount,
        period_type=payload.period_type,
        period_start=payload.period_start,
        period_end=payload.period_end,
        rollover_enabled=payload.rollover_enabled,
    )
    status = dragun.engine.get_budget_status(user_id=user["user_id"])
    return {"status": "success", "budget": budget, "budget_status": status}


@app.post("/api/constraints")
async def create_constraint(payload: ConstraintCreateRequest) -> dict:
    dragun = get_dragun_app()
    try:
        user = dragun.engine.authenticate(handle=payload.handle, passkey=payload.passkey)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    constraint = dragun.engine.create_constraint(
        user_id=user["user_id"],
        constraint_type=payload.constraint_type,
        scope_tags=payload.scope_tags,
        operator=payload.operator,
        threshold_value=payload.threshold_value,
        message_template=payload.message_template,
    )
    return {"status": "success", "constraint": constraint}
