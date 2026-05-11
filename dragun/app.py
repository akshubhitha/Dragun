from __future__ import annotations

import hashlib
import hmac
import base64
import json
import logging
import os
import random
import re
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


def _init_phoenix_tracing(api_key: str | None) -> None:
    """Initialize Arize Phoenix OpenTelemetry tracing for all Gemini calls."""
    if not api_key:
        return
    try:
        import os
        from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
        from phoenix.otel import register

        # Force HTTP/protobuf transport to Phoenix cloud
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://app.phoenix.arize.com"
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"api_key={api_key}"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"

        tracer_provider = register(project_name="dragun")
        GoogleGenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        logger.info("Arize Phoenix tracing enabled — all Gemini calls traced")
    except Exception:
        logger.warning("Arize Phoenix tracing failed to initialize", exc_info=True)

from dragun.agents import root_agent
from dragun.config import Settings, get_settings
from dragun.services.agent import clear_history
from dragun.models import (
    BudgetCreateRequest,
    ChatRequest,
    ChatResponse,
    ConstraintCreateRequest,
    ConstraintOperator,
    ConstraintType,
    LoginRequest,
    PeriodType,
    PurchaseEvaluation,
    RegisterRequest,
    SendOTPRequest,
    User,
    UserProfile,
    UserProfileUpdateRequest,
    UserPublic,
    VerifyOTPRequest,
)
from dragun.services.actions import AdvisorResponseService, BackendActionRouter
from dragun.services.budget import BudgetService
from dragun.services.intent import IntentExtractionService
from dragun.services.inventory import InventoryService
from dragun.services.parser import generate_dragon_reply, parse_text_input_async
from dragun.storage.base import DragunRepository
from dragun.storage.firestore import FirestoreRepository
from dragun.storage.memory import InMemoryDragunRepository

STATIC_DIR = Path(__file__).parent / "static"


def create_repository(settings: Settings) -> DragunRepository:
    if settings.use_firestore and (settings.firestore_emulator_host or settings.google_cloud_project):
        return FirestoreRepository(settings.google_cloud_project, settings.firestore_database)
    return InMemoryDragunRepository()


settings = get_settings()
_init_phoenix_tracing(settings.arize_api_key)
repository = create_repository(settings)
inventory_service = InventoryService(repository)
budget_service = BudgetService(repository, inventory_service)
intent_service = IntentExtractionService()
action_router = BackendActionRouter(
    inventory_service=inventory_service,
    budget_service=budget_service,
    advisor=AdvisorResponseService(),
)

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


# ── OTP store ──────────────────────────────────────────────────────────────────
# { email: { "code": str, "expires_at": datetime, "attempts": int, "last_sent_at": datetime } }
_otp_store: dict[str, dict] = {}
_OTP_TTL_MINUTES = 10
_OTP_MAX_ATTEMPTS = 5
_OTP_RESEND_COOLDOWN_SECONDS = 60
_SESSION_TTL_DAYS = 30


def _generate_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


def _purge_expired_otps() -> None:
    now = datetime.now(UTC)
    expired = [email for email, entry in _otp_store.items() if entry["expires_at"] < now]
    for email in expired:
        del _otp_store[email]


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _session_secret() -> str:
    return (
        settings.session_secret
        or os.environ.get("DRAGUN_PASSKEY_SALT")
        or settings.google_api_key
        or "local-dev-session-secret"
    )


def create_session_token(user_id: str) -> str:
    expires_at = datetime.now(UTC) + timedelta(days=_SESSION_TTL_DAYS)
    payload = _b64encode(
        json.dumps(
            {"sub": user_id, "exp": int(expires_at.timestamp())},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = hmac.new(
        _session_secret().encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload}.{_b64encode(signature)}"


def verify_session_token(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload, signature = token.split(".", 1)
    expected = _b64encode(
        hmac.new(
            _session_secret().encode("utf-8"),
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        claims = json.loads(_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(claims.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) else None


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


async def _send_otp_email(to_email: str, code: str, username: str | None, is_new: bool) -> bool:
    """Send OTP via Resend API. Returns True on success."""
    api_key = settings.resend_api_key
    if not api_key:
        # Dev mode — log the code so you can manually share it
        logger.warning("RESEND_API_KEY not set. OTP for %s → %s (expires in %d min)", to_email, code, _OTP_TTL_MINUTES)
        return False

    greeting = f"Hey {username}," if username else "Hey,"
    action_text = "create your Dragun account" if is_new else "sign back in to Dragun"
    html_body = f"""
    <div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;padding:40px 24px;">
      <div style="font-size:22px;font-weight:800;letter-spacing:-0.5px;margin-bottom:6px;">
        dra<span style="color:#00c9a7;">gun</span>
      </div>
      <p style="color:#6b7a8d;font-size:13px;margin-top:0;margin-bottom:32px;">
        Your dragon knows every coin in the hoard.
      </p>
      <p style="font-size:15px;color:#1a2332;">{greeting}</p>
      <p style="font-size:15px;color:#1a2332;">
        Here's your code to {action_text}:
      </p>
      <div style="background:#f0f2f5;border-radius:12px;padding:24px;text-align:center;margin:24px 0;">
        <div style="font-size:40px;font-weight:800;letter-spacing:8px;color:#0f1923;font-variant-numeric:tabular-nums;">
          {code}
        </div>
        <div style="font-size:12px;color:#6b7a8d;margin-top:8px;">
          Expires in {_OTP_TTL_MINUTES} minutes
        </div>
      </div>
      <p style="font-size:13px;color:#6b7a8d;">
        If you didn't request this, you can safely ignore this email.
      </p>
    </div>
    """

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.email_from,
                    "to": [to_email],
                    "subject": f"Your Dragun code: {code}",
                    "html": html_body,
                },
            )
        if resp.status_code not in (200, 201):
            logger.error("Resend API error %s: %s", resp.status_code, resp.text)
            return False
        return True
    except Exception:
        logger.error("Failed to send OTP email to %s", to_email, exc_info=True)
        return False


@app.post("/api/auth/send-otp")
async def send_otp(request: SendOTPRequest, repo: DragunRepository = Depends(get_repo)) -> dict:
    """Step 1 of passwordless auth: send a 6-digit OTP to the given email."""
    email = request.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    _purge_expired_otps()
    existing_user = repo.get_user_by_email(email)
    is_new = existing_user is None
    now = datetime.now(UTC)

    existing_entry = _otp_store.get(email)
    if existing_entry and existing_entry.get("last_sent_at"):
        elapsed = (now - existing_entry["last_sent_at"]).total_seconds()
        if elapsed < _OTP_RESEND_COOLDOWN_SECONDS:
            retry_after = int(_OTP_RESEND_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Code already sent. Try again in {retry_after} seconds.",
            )

    code = _generate_otp()
    _otp_store[email] = {
        "code": code,
        "expires_at": now + timedelta(minutes=_OTP_TTL_MINUTES),
        "is_new": is_new,
        "attempts": 0,
        "last_sent_at": now,
    }

    sent = await _send_otp_email(email, code, None, is_new)
    if not sent and settings.resend_api_key:
        raise HTTPException(status_code=500, detail="Failed to send code. Try again in a moment.")

    return {"status": "otp_sent", "is_new_user": is_new, "email": email}


@app.post("/api/auth/verify-otp")
async def verify_otp(request: VerifyOTPRequest, repo: DragunRepository = Depends(get_repo)) -> dict:
    """Step 2 of passwordless auth: verify the OTP and return (or create) the user."""
    email = request.email.strip().lower()
    entry = _otp_store.get(email)

    if not entry:
        raise HTTPException(status_code=400, detail="No code found for this email. Request a new one.")
    if datetime.now(UTC) > entry["expires_at"]:
        del _otp_store[email]
        raise HTTPException(status_code=400, detail="That code expired. Request a new one.")
    if entry["code"] != request.code.strip():
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        if entry["attempts"] >= _OTP_MAX_ATTEMPTS:
            del _otp_store[email]
            raise HTTPException(status_code=429, detail="Too many wrong codes. Request a new one.")
        raise HTTPException(status_code=400, detail="Wrong code. Check your email and try again.")

    # Code is valid — consume it
    del _otp_store[email]

    existing_user = repo.get_user_by_email(email)
    if existing_user:
        pub = UserPublic.from_user(existing_user)
        return {
            **pub.model_dump(mode="json"),
            "is_new_user": False,
            "session_token": create_session_token(existing_user.user_id),
        }

    # New user — create account with a temp handle; onboarding will set the real one
    new_id = str(uuid4())
    temp_handle = f"user_{new_id[:8]}"
    user = User(
        user_id=new_id,
        handle=temp_handle,
        email=email,
        currency="USD",
        created_at=datetime.now(UTC),
    )
    repo.create_user(user)
    pub = UserPublic.from_user(user)
    return {
        **pub.model_dump(mode="json"),
        "is_new_user": True,
        "session_token": create_session_token(user.user_id),
    }


@app.patch("/api/users/{user_id}/handle")
def set_user_handle(
    user_id: str,
    body: dict,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    """Set / change a user's handle. Called from onboarding to claim their chosen username."""
    require_user_session(repo, user_id, request)
    handle = (body.get("handle") or "").strip().lower()
    if not handle:
        raise HTTPException(status_code=400, detail="Handle cannot be empty.")
    if len(handle) < 2:
        raise HTTPException(status_code=400, detail="Username must be at least 2 characters.")
    if not handle.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Username can only contain letters, numbers, hyphens, and underscores.")
    # Check uniqueness — but allow re-setting the same handle
    existing = repo.get_user_by_handle(handle)
    if existing and existing.user_id != user_id:
        raise HTTPException(status_code=409, detail="That username is already taken. Try another.")
    try:
        user = repo.update_user_handle(user_id, handle)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    pub = UserPublic.from_user(user)
    return pub.model_dump(mode="json")


@app.patch("/api/users/{user_id}/profile")
def update_profile(
    user_id: str,
    body: dict,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    """Save financial profile fields collected during onboarding."""
    require_user_session(repo, user_id, request)
    allowed = {"monthly_income", "fixed_costs_floor"}
    updates = {k: float(v) for k, v in body.items() if k in allowed and v is not None}
    try:
        user = repo.update_user_profile(user_id, **updates)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return UserPublic.from_user(user).model_dump(mode="json")


@app.patch("/api/users/{user_id}/user-profile")
def update_user_profile(
    user_id: str,
    payload: UserProfileUpdateRequest,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    """Create or update the user's personality/goals profile (pain points, primary goal, tone)."""
    require_user_session(repo, user_id, request)
    existing = repo.get_user_profile(user_id)
    if existing:
        profile = existing.model_copy(deep=True)
    else:
        profile = UserProfile(user_id=user_id)

    if payload.pain_points is not None:
        profile.pain_points = payload.pain_points
    if payload.primary_goal is not None:
        profile.primary_goal = payload.primary_goal
    if payload.preferred_tone is not None:
        profile.preferred_tone = payload.preferred_tone
    if payload.onboarding_completed is not None:
        profile.onboarding_completed = payload.onboarding_completed

    from dragun.models import utc_now
    profile.updated_at = utc_now()
    saved = repo.upsert_user_profile(profile)
    return saved.model_dump(mode="json")


@app.get("/api/users/{user_id}/user-profile")
def get_user_profile(
    user_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    """Fetch the user's profile (or a blank default if not yet created)."""
    require_user_session(repo, user_id, request)
    profile = repo.get_user_profile(user_id) or UserProfile(user_id=user_id)
    return profile.model_dump(mode="json")


@app.delete("/api/users/{user_id}")
def delete_account(
    user_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    """Anonymise the user — strips PII but keeps spending data as synthetic records."""
    require_user_session(repo, user_id, request)
    repo.anonymize_user(user_id)
    clear_history(user_id)
    return {"status": "anonymized"}


@app.get("/api/users/{user_id}/me")
def get_me(
    user_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    """Restore a session — returns the user if found, 404 otherwise."""
    user = require_user_session(repo, user_id, request)
    return UserPublic.from_user(user).model_dump(mode="json")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/onboarding")
def onboarding() -> FileResponse:
    return FileResponse(STATIC_DIR / "onboarding.html")


@app.get("/health")
def health() -> dict[str, str]:
    agent_name = root_agent.name if root_agent is not None else "dragun_coordinator"
    storage = "firestore" if settings.use_firestore else "memory"
    return {"status": "ok", "model": settings.gemini_model, "agent": agent_name, "storage": storage}


@app.post("/api/register")
def register_user(payload: RegisterRequest, repo: DragunRepository = Depends(get_repo)) -> dict:
    existing = repo.get_user_by_handle(payload.handle)
    if existing:
        raise HTTPException(status_code=409, detail="That handle is already guarding a hoard.")

    user = User(
        user_id=str(uuid4()),
        handle=payload.handle,
        passkey_hash=hash_passkey(payload.passkey),
        zip_code=payload.zip_code,
        currency="USD",
        created_at=datetime.now(UTC),
    )
    repo.create_user(user)
    return {
        **UserPublic.from_user(user).model_dump(mode="json"),
        "session_token": create_session_token(user.user_id),
    }


@app.post("/api/login")
def login_user(payload: LoginRequest, repo: DragunRepository = Depends(get_repo)) -> dict:
    user = repo.get_user_by_handle(payload.handle)
    # Use constant-time comparison to prevent timing attacks
    if not user or not hmac.compare_digest(
        user.passkey_hash,
        hash_passkey(payload.passkey),
    ):
        raise HTTPException(status_code=401, detail="Wrong handle or passkey. The dragon is suspicious.")
    return {
        **UserPublic.from_user(user).model_dump(mode="json"),
        "session_token": create_session_token(user.user_id),
    }


@app.get("/api/users/{handle}", response_model=UserPublic)
def get_user(handle: str, repo: DragunRepository = Depends(get_repo)) -> UserPublic:
    raise HTTPException(status_code=410, detail="Use OTP login to open a hoard.")
    user = repo.get_user_by_handle(handle)
    if not user:
        raise HTTPException(status_code=404, detail="No hoard found for that handle.")
    return UserPublic.from_user(user)


@app.post("/api/users/{user_id}/budgets")
def create_budget(
    user_id: str,
    payload: BudgetCreateRequest,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    user = require_user_session(repo, user_id, request)
    budget = budget_service.create_budget(user.user_id, payload)
    status = budget_service.get_budget_status(budget)
    return {"budget": budget, "status": status}


@app.post("/api/users/{user_id}/constraints")
def create_constraint(
    user_id: str,
    payload: ConstraintCreateRequest,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    user = require_user_session(repo, user_id, request)
    constraint = budget_service.create_constraint(user.user_id, payload)
    return {"constraint": constraint}


@app.get("/api/users/{user_id}/inventory")
def inventory(user_id: str, request: Request, repo: DragunRepository = Depends(get_repo)) -> dict:
    require_user_session(repo, user_id, request)
    return {"inventory": inventory_service.query_inventory(user_id)}


@app.get("/api/users/{user_id}/budgets/status")
def budget_status(user_id: str, request: Request, repo: DragunRepository = Depends(get_repo)) -> dict:
    require_user_session(repo, user_id, request)
    return {"budgets": budget_service.get_budget_statuses(user_id)}


@app.get("/api/users/{user_id}/export")
def export_user_data(user_id: str, request: Request, repo: DragunRepository = Depends(get_repo)) -> dict:
    user = require_user_session(repo, user_id, request)
    return repo.export_user_data(user.user_id)


@app.delete("/api/users/{user_id}/hard-delete")
def delete_user(
    user_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict[str, str]:
    require_user_session(repo, user_id, request)
    repo.delete_user_data(user_id)
    clear_history(user_id)
    return {"status": "deleted"}


@app.post("/api/users/{user_id}/logout")
def logout_user(user_id: str, request: Request, repo: DragunRepository = Depends(get_repo)) -> dict[str, str]:
    require_user_session(repo, user_id, request)
    clear_history(user_id)
    return {"status": "logged_out"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, repo: DragunRepository = Depends(get_repo)) -> ChatResponse:
    user = require_user_session(repo, payload.user_id, request)
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Say what is entering or leaving the hoard.")

    # Fetch the user's profile so the advisor can personalise responses
    user_profile = repo.get_user_profile(user.user_id)

    # Gemini now acts as a JSON extraction layer only. Python validates the
    # intent, executes all database work, computes decisions, then optionally
    # asks Gemini to phrase the final advice from compact backend facts.
    extracted_intent = await intent_service.extract(text)
    result = await action_router.handle(
        user, extracted_intent, input_source=payload.input_source, user_profile=user_profile
    )
    return ChatResponse(
        reply=result.reply,
        intent=result.intent.model_dump(mode="json"),
        decision_band=result.decision_band,
        events=result.events,
        inventory=result.inventory,
        budgets=result.budgets,
        constraints=result.constraints,
    )


def require_user(repo: DragunRepository, user_id: str) -> User:
    user = repo.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="No hoard found for that user.")
    return user


def require_user_session(repo: DragunRepository, user_id: str, request: Request) -> User:
    token_user_id = verify_session_token(_bearer_token(request))
    if token_user_id != user_id:
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.")
    return require_user(repo, user_id)


def hash_passkey(passkey: str) -> str:
    salt = os.environ.get("DRAGUN_PASSKEY_SALT", "local-dev-salt")
    return hashlib.sha256(f"{salt}:{passkey}".encode("utf-8")).hexdigest()


async def handle_budget_message(user_id: str, text: str, parsed: any) -> ChatResponse:
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
    fallback = f"Marked. {scope} budget is ${amount:.2f} for this {period_label}. ${status.amount_remaining:.2f} remains."
    reply = await generate_dragon_reply(text, "", f"{scope} ${status.amount_remaining:.2f} left", "", "") or fallback
    return ChatResponse(reply=reply, budgets=[status])


def handle_constraint_message(user_id: str, text: str, parsed: any) -> ChatResponse:
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


def conversational_fallback(text: str) -> str:
    """Friendly fallback reply when Gemini is unavailable and input isn't a command."""
    greetings = {"hey", "hi", "hello", "sup", "yo", "hiya", "howdy"}
    if text.strip().lower().rstrip("!? ") in greetings:
        return "Hey. Tell me what you bought, what you own, or what you want to guard. I track hoards."
    if "?" in text:
        return "Good question. Add a Gemini API key to .env and I'll give you a real answer. For now: tell me what you bought or own."
    return "I didn't catch that as a purchase, inventory update, or budget command. Try: '3 shirts — 50 bucks' or 'budget 200 for clothing'."


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
