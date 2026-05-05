"""Pydantic models used by the Dragun HTTP API and domain layer."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    handle: str = Field(min_length=3, max_length=40)
    passkey: str = Field(min_length=4, max_length=200)
    zip_code: str = Field(pattern=r"^\d{5}$")


class RegisterResponse(BaseModel):
    user_id: str
    handle: str
    created_at: datetime


class ChatRequest(BaseModel):
    handle: str
    passkey: str
    message: str = Field(min_length=1, max_length=3000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    inventory_preview: list[dict]
    budget_preview: list[dict]


class BudgetCreateRequest(BaseModel):
    handle: str
    passkey: str
    budget_scope: str = "all"
    scope_tags: list[str] = Field(default_factory=list)
    budget_amount: float = Field(gt=0)
    period_type: Literal["weekly", "monthly", "custom"] = "monthly"
    period_start: date | None = None
    period_end: date | None = None
    rollover_enabled: bool = False


class ConstraintCreateRequest(BaseModel):
    handle: str
    passkey: str
    constraint_type: Literal[
        "hard_budget_limit",
        "inventory_cap",
        "trend_alert",
        "velocity_warning",
        "pace_alert",
    ]
    scope_tags: list[str] = Field(default_factory=list)
    operator: str = "exceeds"
    threshold_value: float
    message_template: str | None = None

