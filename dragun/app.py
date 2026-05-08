from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dragun.agents import root_agent
from dragun.config import Settings, get_settings
from dragun.models import (
    BudgetCreateRequest,
    ChatRequest,
    ChatResponse,
    ConstraintCreateRequest,
    ConstraintOperator,
    ConstraintType,
    PeriodType,
    PurchaseEvaluation,
    RegisterRequest,
    User,
)
from dragun.services.budget import BudgetService
from dragun.services.inventory import InventoryService
from dragun.services.parser import parse_text_input
from dragun.storage.base import DragunRepository
from dragun.storage.firestore import FirestoreRepository
from dragun.storage.memory import InMemoryDragunRepository

STATIC_DIR = Path(__file__).parent / "static"


def create_repository(settings: Settings) -> DragunRepository:
    if settings.use_firestore and (settings.firestore_emulator_host or settings.google_cloud_project):
        return FirestoreRepository(settings.google_cloud_project, settings.firestore_database)
    return InMemoryDragunRepository()


settings = get_settings()
repository = create_repository(settings)
inventory_service = InventoryService(repository)
budget_service = BudgetService(repository, inventory_service)

app = FastAPI(
    title="Dragun",
    description="Phase 1 personal consumption intelligence agent built with Google Cloud ADK.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_repo() -> DragunRepository:
    return repository


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    agent_name = root_agent.name if root_agent is not None else "dragun_coordinator"
    return {"status": "ok", "model": settings.gemini_model, "agent": agent_name}


@app.post("/api/register", response_model=User)
def register_user(request: RegisterRequest, repo: DragunRepository = Depends(get_repo)) -> User:
    existing = repo.get_user_by_handle(request.handle)
    if existing:
        raise HTTPException(status_code=409, detail="That handle is already guarding a hoard.")

    user = User(
        user_id=str(uuid4()),
        handle=request.handle,
        passkey_hash=hash_passkey(request.passkey),
        zip_code=request.zip_code,
        currency="USD",
        created_at=datetime.now(UTC),
    )
    repo.create_user(user)
    return user


@app.get("/api/users/{handle}", response_model=User)
def get_user(handle: str, repo: DragunRepository = Depends(get_repo)) -> User:
    user = repo.get_user_by_handle(handle)
    if not user:
        raise HTTPException(status_code=404, detail="No hoard found for that handle.")
    return user


@app.post("/api/users/{user_id}/budgets")
def create_budget(
    user_id: str,
    request: BudgetCreateRequest,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    user = require_user(repo, user_id)
    budget = budget_service.create_budget(user.user_id, request)
    status = budget_service.get_budget_status(budget)
    return {"budget": budget, "status": status}


@app.post("/api/users/{user_id}/constraints")
def create_constraint(
    user_id: str,
    request: ConstraintCreateRequest,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    user = require_user(repo, user_id)
    constraint = budget_service.create_constraint(user.user_id, request)
    return {"constraint": constraint}


@app.get("/api/users/{user_id}/inventory")
def inventory(user_id: str, repo: DragunRepository = Depends(get_repo)) -> dict:
    require_user(repo, user_id)
    return {"inventory": inventory_service.query_inventory(user_id)}


@app.get("/api/users/{user_id}/budgets/status")
def budget_status(user_id: str, repo: DragunRepository = Depends(get_repo)) -> dict:
    require_user(repo, user_id)
    return {"budgets": budget_service.get_budget_statuses(user_id)}


@app.get("/api/users/{user_id}/export")
def export_user_data(user_id: str, repo: DragunRepository = Depends(get_repo)) -> dict:
    user = require_user(repo, user_id)
    return repo.export_user_data(user.user_id)


@app.delete("/api/users/{user_id}")
def delete_user(user_id: str, repo: DragunRepository = Depends(get_repo)) -> dict[str, str]:
    require_user(repo, user_id)
    repo.delete_user_data(user_id)
    return {"status": "deleted"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, repo: DragunRepository = Depends(get_repo)) -> ChatResponse:
    user = require_user(repo, request.user_id)
    text = request.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Say what is entering or leaving the hoard.")

    lower = text.lower()
    if lower.startswith("budget") or " budget" in lower:
        return handle_budget_message(user.user_id, text)
    if any(term in lower for term in ("limit", "cap", "don't let me", "dont let me", "warn me")):
        return handle_constraint_message(user.user_id, text)
    if re.search(r"\b(how many|inventory|what do i have|do i have)\b", lower):
        return inventory_question(user.user_id)

    parsed = parse_text_input(text)
    if not parsed.items:
        return ChatResponse(reply="I need one clear item, quantity, or budget line to guard.")
    evaluation: PurchaseEvaluation | None = (
        budget_service.evaluate_purchase(user.user_id, parsed.items)
        if parsed.intent == "purchase"
        else None
    )
    events = inventory_service.log_items(user, parsed, input_source=request.input_source)
    inventory_rows = inventory_service.query_inventory(user.user_id)
    budget_statuses = budget_service.get_budget_statuses(user.user_id)
    constraint_alerts = evaluation.constraint_alerts if evaluation else []
    velocity_notes = inventory_service.velocity_notes(user.user_id, events)
    reply = build_dragon_reply(
        inventory_rows,
        budget_statuses,
        constraint_alerts,
        velocity_notes,
        intent=parsed.intent,
    )
    return ChatResponse(
        reply=reply,
        parsed=parsed,
        events=events,
        inventory=inventory_rows,
        budgets=budget_statuses,
        constraints=constraint_alerts,
    )


def require_user(repo: DragunRepository, user_id: str) -> User:
    user = repo.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="No hoard found for that user.")
    return user


def hash_passkey(passkey: str) -> str:
    import hashlib
    import os

    salt = os.environ.get("DRAGUN_PASSKEY_SALT", "local-dev-salt")
    return hashlib.sha256(f"{salt}:{passkey}".encode("utf-8")).hexdigest()


def handle_budget_message(user_id: str, text: str) -> ChatResponse:
    parsed = parse_text_input(text)
    if parsed.budget_amount is None:
        return ChatResponse(reply="Name the budget amount, and the dragon will mark the coin line.")
    amount = parsed.budget_amount
    scope = parsed.budget_scope or "all"
    budget = budget_service.create_budget(
        user_id,
        BudgetCreateRequest(
            budget_scope=scope,
            scope_tags=[scope] if scope != "all" else [],
            budget_amount=amount,
            period_type=parsed.period_type,
        ),
    )
    status = budget_service.get_budget_status(budget)
    period_label = "week" if parsed.period_type == PeriodType.WEEKLY else "month"
    reply = f"Marked. {scope} budget is ${amount:.2f} for this {period_label}. ${status.amount_remaining:.2f} remains."
    return ChatResponse(reply=reply, budgets=[status])


def handle_constraint_message(user_id: str, text: str) -> ChatResponse:
    lower = text.lower()
    number_match = re.search(r"(\d+(?:\.\d+)?)", lower)
    if not number_match:
        return ChatResponse(reply="Give me the number for the limit, and I will guard it.")
    threshold = float(number_match.group(1))
    item = "items"
    constraint_type = ConstraintType.INVENTORY_CAP
    operator = ConstraintOperator.COUNT_EXCEEDS
    scope_tags: list[str] = []
    for candidate in ("shirt", "shirts", "dress", "dresses", "pants", "shoe", "shoes", "deodorant", "coffee"):
        if candidate in lower:
            item = candidate.rstrip("s")
            break
    if "budget" in lower or "$" in text:
        constraint_type = ConstraintType.HARD_BUDGET_LIMIT
        operator = ConstraintOperator.EXCEEDS
        for tag in ("clothing", "dining", "food", "body care", "wellness", "fitness", "essentials"):
            if tag in lower:
                scope_tags = [tag]
                item = tag
                break
    constraint = budget_service.create_constraint(
        user_id,
        ConstraintCreateRequest(
            constraint_type=constraint_type,
            scope_tags=scope_tags,
            item_normalized=item if constraint_type == ConstraintType.INVENTORY_CAP else None,
            operator=operator,
            threshold_value=threshold,
        ),
    )
    return ChatResponse(reply=f"Guard set. I will flag {item} when it crosses {threshold:g}.", constraints=[constraint])


def inventory_question(user_id: str) -> ChatResponse:
    rows = inventory_service.query_inventory(user_id)
    if not rows:
        return ChatResponse(reply="The lair is empty so far. Tell me what you have or what you are buying.", inventory=[])
    inventory_text = ", ".join(f"{row.current_quantity:g} {row.item_normalized}" for row in rows)
    return ChatResponse(reply=f"In the hoard: {inventory_text}.", inventory=rows)


def build_dragon_reply(inventory_rows, budget_impacts, constraint_alerts, velocity_notes, intent: str) -> str:
    owned = ", ".join(f"{row.current_quantity:g} {row.item_normalized}" for row in inventory_rows[:8])
    opener = "Baseline marked" if intent == "manual_inventory" else "Got it"
    parts = [f"{opener}. You now have {owned}." if owned else f"{opener}. The hoard is updated."]
    if budget_impacts:
        budget_lines = []
        for status in budget_impacts:
            budget_lines.append(
                f"{status.budget_scope} budget has ${status.amount_remaining:.2f} left"
                f" — ${status.daily_pace:.2f}/day for {status.days_remaining} days"
            )
        parts.append("; ".join(budget_lines) + ".")
    else:
        parts.append("No budget is guarding this category yet.")
    if constraint_alerts:
        parts.append(" ".join(alert.message for alert in constraint_alerts))
    if velocity_notes:
        parts.append(" ".join(velocity_notes))
    return " ".join(parts)
