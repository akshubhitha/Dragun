from __future__ import annotations

import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class EventType(StrEnum):
    PURCHASE = "purchase"
    MANUAL_INVENTORY = "manual_inventory"
    CONSUMPTION = "consumption"
    RETURN = "return"
    BUDGET_SET = "budget_set"
    CONSTRAINT_SET = "constraint_set"
    GIFT = "gift"
    DISCARD = "discard"


class LifespanType(StrEnum):
    CONSUMABLE = "consumable"
    DURABLE = "durable"
    SERVICE = "service"


class InputSource(StrEnum):
    VOICE = "voice"
    TEXT = "text"
    BARCODE = "barcode"
    IMAGE = "image"
    RECEIPT = "receipt"
    MANUAL = "manual"


class PeriodType(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class ConstraintType(StrEnum):
    HARD_BUDGET_LIMIT = "hard_budget_limit"
    INVENTORY_CAP = "inventory_cap"
    TREND_ALERT = "trend_alert"
    VELOCITY_WARNING = "velocity_warning"
    PACE_ALERT = "pace_alert"


class ConstraintOperator(StrEnum):
    EXCEEDS = "exceeds"
    FALLS_BELOW = "falls_below"
    INCREASES_BY_PCT = "increases_by_pct"
    COUNT_EXCEEDS = "count_exceeds"


class User(BaseModel):
    user_id: str = Field(default_factory=lambda: str(uuid4()))
    handle: str
    passkey_hash: str = ""  # kept for backward compat; not used in OTP auth
    email: str | None = None
    zip_code: str = ""
    currency: str = "USD"
    monthly_income: float = 0.0
    fixed_costs_floor: float = 0.0
    utility_costs_avg: float = 0.0
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("handle")
    @classmethod
    def normalize_handle(cls, value: str) -> str:
        return value.strip().lower()


class FamilyMember(BaseModel):
    member_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    member_name: str
    created_at: datetime = Field(default_factory=utc_now)


class Tag(BaseModel):
    tag_id: str = Field(default_factory=lambda: str(uuid4()))
    tag_name: str
    tag_origin: Literal["system", "agent_inferred", "user_defined"] = "agent_inferred"

    @field_validator("tag_name")
    @classmethod
    def normalize_tag(cls, value: str) -> str:
        return value.strip().lower()


class EventTag(BaseModel):
    event_id: str
    tag_id: str
    confidence: float = 0.8
    assigned_by: Literal["agent", "user"] = "agent"


class Event(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    event_type: EventType
    item_description: str
    item_normalized: str
    quantity: int = 1
    unit_cost: float | None = None
    total_cost: float | None = None
    lifespan_type: LifespanType = LifespanType.DURABLE
    input_source: InputSource = InputSource.TEXT
    raw_input: str
    family_member_id: str | None = None
    event_timestamp: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)


class Budget(BaseModel):
    budget_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    budget_scope: str
    scope_tags: list[str]
    budget_amount: float
    period_type: PeriodType = PeriodType.MONTHLY
    period_start: date
    period_end: date
    rollover_enabled: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class Constraint(BaseModel):
    constraint_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    constraint_type: ConstraintType
    scope_tags: list[str] = Field(default_factory=list)
    item_normalized: str | None = None
    operator: ConstraintOperator
    threshold_value: float
    message_template: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    last_triggered_at: datetime | None = None


class GoalStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"


class Goal(BaseModel):
    goal_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    name: str
    target_amount: float
    current_amount: float = 0.0
    deadline: date | None = None
    category: str | None = None
    status: GoalStatus = GoalStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GoalCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_amount: float = Field(gt=0)
    deadline: date | None = None
    category: str | None = None


class GoalUpdateRequest(BaseModel):
    name: str | None = None
    target_amount: float | None = None
    current_amount: float | None = None
    deadline: date | None = None
    category: str | None = None
    status: GoalStatus | None = None


class ParsedItem(BaseModel):
    description: str
    quantity: int = 1
    unit_cost: float | None = None
    total_cost: float | None = None
    lifespan_type: LifespanType = LifespanType.DURABLE
    suggested_tags: list[str] = Field(default_factory=list)
    item_normalized: str


class ParsedInput(BaseModel):
    intent: Literal[
        "register",
        "purchase",
        "manual_inventory",
        "budget_create",
        "constraint_create",
        "inventory_query",
        "unknown",
    ]
    items: list[ParsedItem] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    family_member: str | None = None
    budget_scope: str | None = None
    budget_amount: float | None = None
    period_type: PeriodType = PeriodType.MONTHLY
    constraint_type: ConstraintType | None = None
    constraint_threshold: float | None = None
    constraint_item: str | None = None
    raw: str = ""


class InventoryRow(BaseModel):
    user_id: str
    family_member_id: str | None = None
    item_normalized: str
    tags: list[str] = Field(default_factory=list)
    current_quantity: int
    lifespan_type: LifespanType = LifespanType.DURABLE
    avg_unit_cost: float | None = None
    last_purchased: datetime | None = None
    first_seen: datetime | None = None


class BudgetStatus(BaseModel):
    budget_id: str
    budget_scope: str
    budget_amount: float
    period_type: PeriodType
    rollover_enabled: bool = False
    amount_spent: float
    amount_remaining: float
    daily_pace: float
    days_remaining: int
    pct_consumed: float


class ConstraintAlert(BaseModel):
    constraint_id: str
    constraint_type: ConstraintType
    message: str
    severity: Literal["info", "warning"] = "warning"


class PurchaseEvaluation(BaseModel):
    budget_statuses: list[BudgetStatus] = Field(default_factory=list)
    constraint_alerts: list[ConstraintAlert] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)


class UserPublic(BaseModel):
    """Safe user representation — passkey_hash is never included."""
    user_id: str
    handle: str
    email: str | None = None
    currency: str
    monthly_income: float = 0.0
    fixed_costs_floor: float = 0.0
    utility_costs_avg: float = 0.0
    created_at: datetime

    @classmethod
    def from_user(cls, user: "User") -> "UserPublic":
        return cls(
            user_id=user.user_id,
            handle=user.handle,
            email=user.email,
            currency=user.currency,
            monthly_income=user.monthly_income,
            fixed_costs_floor=user.fixed_costs_floor,
            utility_costs_avg=user.utility_costs_avg,
            created_at=user.created_at,
        )


class RegisterRequest(BaseModel):
    handle: str
    passkey: str = Field(min_length=8)
    zip_code: str = ""


class LoginRequest(BaseModel):
    handle: str
    passkey: str


class SendOTPRequest(BaseModel):
    email: str
    username: str | None = None  # required for new users; ignored for returning users


class VerifyOTPRequest(BaseModel):
    email: str
    code: str


class ChatRequest(BaseModel):
    user_id: str
    message: str
    input_source: InputSource = InputSource.TEXT


class ChatResponse(BaseModel):
    reply: str
    intent: dict[str, Any] | None = None
    decision_band: str | None = None
    parsed: ParsedInput | None = None
    events: list[Event] = Field(default_factory=list)
    inventory: list[InventoryRow] = Field(default_factory=list)
    budgets: list[BudgetStatus] = Field(default_factory=list)
    constraints: list[ConstraintAlert | Constraint] = Field(default_factory=list)


class BudgetCreateRequest(BaseModel):
    budget_scope: str = "all"
    scope_tags: list[str] = Field(default_factory=list)
    budget_amount: float = Field(gt=0)
    period_type: PeriodType = PeriodType.MONTHLY
    rollover_enabled: bool = False


class ConstraintCreateRequest(BaseModel):
    constraint_type: ConstraintType
    scope_tags: list[str] = Field(default_factory=list)
    item_normalized: str | None = None
    operator: ConstraintOperator
    threshold_value: float = Field(gt=0)
    message_template: str | None = None


class UserProfile(BaseModel):
    """Persistent personality + goal context passed to the agent on every turn."""

    user_id: str
    # Set during onboarding; can grow over time as agent detects shifts
    pain_points: list[str] = Field(default_factory=list)
    primary_goal: str | None = None
    # "warm" | "direct" | "analytical" | "balanced"
    preferred_tone: str = "balanced"
    onboarding_completed: bool = False
    updated_at: datetime = Field(default_factory=utc_now)


_PROFILE_TEXT_MAX = 200   # chars per free-text field
_PAIN_POINT_MAX = 80      # chars per individual pain point
_PAIN_POINTS_MAX_COUNT = 10
_ALLOWED_TONES = {"warm", "direct", "analytical", "balanced"}
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")  # strip control characters


def _sanitize(value: str, max_len: int) -> str:
    """Strip control characters and enforce a length cap."""
    return _CTRL_RE.sub("", value).strip()[:max_len]


class UserProfileUpdateRequest(BaseModel):
    pain_points: list[str] | None = None
    primary_goal: str | None = None
    preferred_tone: str | None = None
    onboarding_completed: bool | None = None

    @field_validator("primary_goal", mode="before")
    @classmethod
    def _clean_goal(cls, v: str | None) -> str | None:
        return _sanitize(v, _PROFILE_TEXT_MAX) if v else None

    @field_validator("pain_points", mode="before")
    @classmethod
    def _clean_pains(cls, v: list | None) -> list | None:
        if v is None:
            return None
        cleaned = [_sanitize(str(p), _PAIN_POINT_MAX) for p in v if str(p).strip()]
        return cleaned[:_PAIN_POINTS_MAX_COUNT]

    @field_validator("preferred_tone", mode="before")
    @classmethod
    def _clean_tone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = str(v).strip().lower()
        return v if v in _ALLOWED_TONES else "balanced"


class ExportResponse(BaseModel):
    user: User
    events: list[Event]
    budgets: list[Budget]
    constraints: list[Constraint]
    tags_by_event: dict[str, list[str]]


def model_dump_firestore(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="python")
