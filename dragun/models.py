from __future__ import annotations

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


class ExportResponse(BaseModel):
    user: User
    events: list[Event]
    budgets: list[Budget]
    constraints: list[Constraint]
    tags_by_event: dict[str, list[str]]


def model_dump_firestore(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="python")
