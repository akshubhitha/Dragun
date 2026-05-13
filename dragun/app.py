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
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
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
from dragun.models import (
    BudgetCreateRequest,
    ChatRequest,
    EventType,
    ChatResponse,
    ConstraintCreateRequest,
    ConstraintOperator,
    ConstraintType,
    Goal,
    GoalCreateRequest,
    GoalUpdateRequest,
    InputSource,
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
    utc_now,
)
from dragun.services.actions import AdvisorResponseService, BackendActionRouter
from dragun.services.agent import clear_history as _clear_agent_history
from dragun.services.budget import BudgetService
from dragun.services.history import append_turn, clear_history as _clear_conv_history
from dragun.services.intent import AgentIntent, IntentExtractionService, IntentItem
from dragun.services.rag import get_instruction_retriever
from dragun.services.security import sanitize_input, sanitize_receipt_item
from dragun.services.inventory import InventoryService
from dragun.services.spending import get_spending_daily, get_spending_summary
from dragun.services.parser import generate_dragon_reply, parse_text_input_async
from dragun.storage.base import DragunRepository
from dragun.storage.firestore import FirestoreRepository
from dragun.storage.memory import InMemoryDragunRepository


def clear_history(user_id: str) -> None:
    """Clear both agentic loop history and deterministic conversation history."""
    _clear_agent_history(user_id)
    _clear_conv_history(user_id)

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


@app.on_event("startup")
async def startup() -> None:
    """Build the semantic RAG index at startup so all requests use embedding-based retrieval."""
    await get_instruction_retriever().build_index()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


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

    # Do not reveal is_new_user — leaks whether the email is registered (enumeration risk)
    return {"status": "otp_sent", "email": email}


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
    allowed = {"monthly_income", "fixed_costs_floor", "utility_costs_avg"}
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


@app.patch("/api/users/{user_id}/budgets/{budget_id}")
def patch_budget(
    user_id: str,
    budget_id: str,
    body: dict,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    require_user_session(repo, user_id, request)
    updates: dict = {}
    if "budget_amount" in body and body["budget_amount"] is not None:
        try:
            v = float(body["budget_amount"])
            if v <= 0:
                raise HTTPException(status_code=400, detail="budget_amount must be greater than 0.")
            updates["budget_amount"] = round(v, 2)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="budget_amount must be a number.")
    if "period_type" in body and body["period_type"] is not None:
        if body["period_type"] not in {p.value for p in PeriodType}:
            raise HTTPException(status_code=400, detail=f"period_type must be one of: {[p.value for p in PeriodType]}")
        updates["period_type"] = body["period_type"]
    if "rollover_enabled" in body and isinstance(body["rollover_enabled"], bool):
        updates["rollover_enabled"] = body["rollover_enabled"]
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    try:
        budget = repo.update_budget(user_id, budget_id, **updates)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    status = budget_service.get_budget_status(budget)
    return {"budget": budget.model_dump(mode="json"), "status": status.model_dump(mode="json")}


@app.delete("/api/users/{user_id}/budgets/{budget_id}")
def delete_budget(
    user_id: str,
    budget_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    require_user_session(repo, user_id, request)
    repo.delete_budget(user_id, budget_id)
    return {"status": "deleted"}


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


@app.get("/api/users/{user_id}/constraints")
def list_constraints(user_id: str, request: Request, repo: DragunRepository = Depends(get_repo)) -> dict:
    require_user_session(repo, user_id, request)
    constraints = repo.get_constraints(user_id)
    return {"constraints": [c.model_dump(mode="json") for c in constraints]}


@app.patch("/api/users/{user_id}/constraints/{constraint_id}")
def patch_constraint(
    user_id: str,
    constraint_id: str,
    body: dict,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    require_user_session(repo, user_id, request)
    updates: dict = {}
    if "is_active" in body and isinstance(body["is_active"], bool):
        updates["is_active"] = body["is_active"]
    if "threshold_value" in body and body["threshold_value"] is not None:
        try:
            v = float(body["threshold_value"])
            if v <= 0:
                raise HTTPException(status_code=400, detail="threshold_value must be greater than 0.")
            updates["threshold_value"] = v
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="threshold_value must be a number.")
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    try:
        constraint = repo.update_constraint(user_id, constraint_id, **updates)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"constraint": constraint.model_dump(mode="json")}


@app.delete("/api/users/{user_id}/constraints/{constraint_id}")
def delete_constraint(
    user_id: str,
    constraint_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    require_user_session(repo, user_id, request)
    repo.delete_constraint(user_id, constraint_id)
    return {"status": "deleted"}


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


@app.post("/api/users/{user_id}/goals")
def create_goal(
    user_id: str,
    payload: GoalCreateRequest,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    require_user_session(repo, user_id, request)
    goal = Goal(
        user_id=user_id,
        name=payload.name,
        target_amount=payload.target_amount,
        deadline=payload.deadline,
        category=payload.category,
    )
    saved = repo.create_goal(goal)
    return {"goal": saved.model_dump(mode="json")}


@app.get("/api/users/{user_id}/goals")
def list_goals(user_id: str, request: Request, repo: DragunRepository = Depends(get_repo)) -> dict:
    require_user_session(repo, user_id, request)
    goals = repo.get_goals(user_id)
    return {"goals": [g.model_dump(mode="json") for g in goals]}


@app.patch("/api/users/{user_id}/goals/{goal_id}")
def patch_goal(
    user_id: str,
    goal_id: str,
    payload: GoalUpdateRequest,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    require_user_session(repo, user_id, request)
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    updates["updated_at"] = utc_now()
    try:
        goal = repo.update_goal(user_id, goal_id, **updates)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"goal": goal.model_dump(mode="json")}


@app.delete("/api/users/{user_id}/goals/{goal_id}")
def delete_goal(
    user_id: str,
    goal_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> dict:
    require_user_session(repo, user_id, request)
    repo.delete_goal(user_id, goal_id)
    return {"status": "deleted"}


@app.get("/api/users/{user_id}/spending/summary")
def spending_summary(
    user_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
    period: str = "month",
) -> dict:
    require_user_session(repo, user_id, request)
    if period not in {"month", "week"}:
        raise HTTPException(status_code=400, detail="period must be 'month' or 'week'.")
    summary = get_spending_summary(repo, user_id, period)
    return {
        "total_spent": summary.total_spent,
        "by_category": [
            {"category": c.category, "amount": c.amount, "pct": c.pct}
            for c in summary.by_category
        ],
        "period_start": summary.period_start,
        "period_end": summary.period_end,
    }


@app.get("/api/users/{user_id}/spending/daily")
def spending_daily(
    user_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
    period: str = "month",
) -> dict:
    require_user_session(repo, user_id, request)
    if period not in {"month", "week"}:
        raise HTTPException(status_code=400, detail="period must be 'month' or 'week'.")
    daily = get_spending_daily(repo, user_id, period)
    return {
        "days": [{"date": d.date, "amount": d.amount} for d in daily.days],
        "period_start": daily.period_start,
        "period_end": daily.period_end,
    }


@app.get("/api/users/{user_id}/events/recent")
def recent_events(
    user_id: str,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
    limit: int = 25,
) -> dict:
    """Return the most recent purchase events for the activity feed."""
    require_user_session(repo, user_id, request)
    all_events = repo.list_events(user_id)
    purchase_events = [
        e for e in all_events if e.event_type == EventType.PURCHASE
    ]
    purchase_events.sort(key=lambda e: e.event_timestamp, reverse=True)
    recent = purchase_events[: min(limit, 50)]
    event_ids = [e.event_id for e in recent]
    tags_by_event = repo.list_event_tags(event_ids)
    return {
        "events": [
            {
                **e.model_dump(mode="json"),
                "tags": tags_by_event.get(e.event_id, []),
            }
            for e in recent
        ]
    }


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


@app.post("/api/users/{user_id}/receipt", response_model=ChatResponse)
async def upload_receipt(
    user_id: str,
    request: Request,
    file: UploadFile = File(...),
    repo: DragunRepository = Depends(get_repo),
) -> ChatResponse:
    """Upload a receipt image. Gemini Vision extracts line items and logs them to the hoard."""
    user = require_user_session(repo, user_id, request)
    settings = get_settings()
    if not settings.google_api_key:
        raise HTTPException(status_code=503, detail="Vision processing requires a Google API key.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    mime_type = file.content_type or "image/jpeg"

    from google import genai
    from google.genai import types as gtypes
    from dragun.services.catalog import infer_lifespan_type, normalize_item_name, suggest_tags

    try:
        client = genai.Client(api_key=settings.google_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=[
                gtypes.Part(inline_data=gtypes.Blob(mime_type=mime_type, data=image_bytes)),
                gtypes.Part(text="""Extract every purchasable line item from this receipt as JSON.

Return exactly:
{
  "store_name": "store name or null",
  "total": 0.00,
  "items": [
    {"description": "item name", "quantity": 1, "unit_cost": 0.00, "total_cost": 0.00}
  ]
}

Rules:
- Omit tax lines, tips, subtotals, and payment method lines.
- If quantity is not shown, default to 1.
- If only a total is shown with no per-item prices, distribute evenly.
- Normalize item descriptions to plain English (no all-caps, no product codes)."""),
            ],
            config=gtypes.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=1200,
            ),
        )
        payload = json.loads(response.text or "{}")
    except Exception as exc:
        logger.error("Receipt OCR failed for user %s: %s", user_id, exc)
        raise HTTPException(status_code=422, detail="Could not read the receipt. Try a clearer photo.")

    raw_items = payload.get("items") or []
    if not raw_items:
        raise HTTPException(status_code=422, detail="No items found on this receipt. Try a clearer photo.")

    store = payload.get("store_name") or "receipt"
    transaction_total = payload.get("total")

    intent_items: list[IntentItem] = []
    for raw in raw_items:
        desc = str(raw.get("description") or "").strip()
        if not desc:
            continue
        # Sanitize OCR'd item names — receipt images can contain arbitrary text.
        desc = sanitize_receipt_item(desc, user_id=user.user_id)
        normalized = normalize_item_name(desc)
        qty = int(raw.get("quantity") or 1)
        unit_cost = float(raw["unit_cost"]) if raw.get("unit_cost") is not None else None
        total_cost = float(raw["total_cost"]) if raw.get("total_cost") is not None else None
        if total_cost is None and unit_cost is not None:
            total_cost = round(unit_cost * qty, 2)
        intent_items.append(
            IntentItem(
                name_raw=desc,
                item_normalized=normalized,
                quantity=qty,
                unit_cost=unit_cost,
                total_cost=total_cost,
                estimated_total_cost=total_cost,
                tags=suggest_tags(normalized),
                lifespan_type=infer_lifespan_type(normalized),
            )
        )

    if not intent_items:
        raise HTTPException(status_code=422, detail="Could not parse items from this receipt.")

    receipt_intent = AgentIntent(
        intent="log_purchase",
        confidence=1.0,
        items=intent_items,
        transaction_total=transaction_total,
        raw_input=f"Receipt from {store}",
    )
    user_profile = repo.get_user_profile(user.user_id)
    result = await action_router.handle(
        user, receipt_intent, input_source=InputSource.RECEIPT, user_profile=user_profile
    )
    append_turn(user.user_id, f"[receipt: {store}]", result.reply)
    return ChatResponse(
        reply=result.reply,
        intent=result.intent.model_dump(mode="json"),
        decision_band=result.decision_band,
        events=result.events,
        inventory=result.inventory,
        budgets=result.budgets,
        constraints=result.constraints,
    )


@app.post("/api/users/{user_id}/barcode", response_model=ChatResponse)
async def scan_barcode(
    user_id: str,
    body: dict,
    request: Request,
    repo: DragunRepository = Depends(get_repo),
) -> ChatResponse:
    """Resolve a UPC/EAN barcode to a product name and log it to the hoard."""
    user = require_user_session(repo, user_id, request)
    barcode = str(body.get("barcode") or "").strip()
    if not barcode:
        raise HTTPException(status_code=400, detail="Barcode value is required.")

    from dragun.services.catalog import infer_lifespan_type, normalize_item_name, suggest_tags

    # Look up the product name via Open Food Facts (free, no key needed)
    product_name: str | None = None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json",
                headers={"User-Agent": "Dragun/1.0 (https://mydragun.com)"},
            )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == 1:
                product = data.get("product") or {}
                product_name = (
                    product.get("product_name_en")
                    or product.get("product_name")
                    or product.get("generic_name_en")
                    or product.get("generic_name")
                    or ""
                ).strip() or None
    except Exception:
        pass  # fall through to barcode-as-name fallback

    if not product_name:
        # Unknown barcode — return a clear message so the frontend can prompt the user
        raise HTTPException(
            status_code=404,
            detail=f"Product not found for barcode {barcode}. Enter the item name manually.",
        )

    normalized = normalize_item_name(product_name)
    barcode_intent = AgentIntent(
        intent="log_purchase",
        confidence=0.95,
        items=[
            IntentItem(
                name_raw=product_name,
                item_normalized=normalized,
                quantity=1,
                tags=suggest_tags(normalized),
                lifespan_type=infer_lifespan_type(normalized),
            )
        ],
        raw_input=f"Barcode scan: {product_name}",
    )
    user_profile = repo.get_user_profile(user.user_id)
    result = await action_router.handle(
        user, barcode_intent, input_source=InputSource.BARCODE, user_profile=user_profile
    )
    append_turn(user.user_id, f"[barcode: {product_name}]", result.reply)
    return ChatResponse(
        reply=result.reply,
        intent=result.intent.model_dump(mode="json"),
        decision_band=result.decision_band,
        events=result.events,
        inventory=result.inventory,
        budgets=result.budgets,
        constraints=result.constraints,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, repo: DragunRepository = Depends(get_repo)) -> ChatResponse:
    user = require_user_session(repo, payload.user_id, request)
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Say what is entering or leaving the hoard.")

    # Fetch the user's profile so the advisor can personalise responses
    user_profile = repo.get_user_profile(user.user_id)

    # Sanitize before any LLM call — strip injection attempts, log if flagged.
    text, _ = sanitize_input(text, source="chat", user_id=user.user_id)

    # Gemini extraction layer: cheap flash-lite model, JSON only.
    # History injected for pronoun/reference resolution across turns.
    extracted_intent = await intent_service.extract(text, user_id=user.user_id)
    result = await action_router.handle(
        user, extracted_intent, input_source=payload.input_source, user_profile=user_profile
    )
    # Persist this turn so the next message has conversational context
    append_turn(user.user_id, text, result.reply)
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


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str, request: Request) -> FileResponse:
    """Serve React app for all non-API, non-static routes (React Router support)."""
    if full_path.startswith("api/") or full_path.startswith("static/") or full_path.startswith("assets/"):
        raise HTTPException(status_code=404)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404)


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
