from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from google import genai
from google.genai import types

from dragun.config import get_settings
from dragun.models import (
    BudgetCreateRequest,
    BudgetStatus,
    ConstraintAlert,
    ConstraintCreateRequest,
    ConstraintOperator,
    ConstraintType,
    Event,
    EventType,
    InputSource,
    InventoryRow,
    User,
    UserProfile,
    utc_now,
)
from dragun.services.catalog import infer_lifespan_type, suggest_tags
from dragun.services.intent import AgentIntent, IntentItem, parsed_input_from_intent
from dragun.services.rag import get_instruction_retriever
from dragun.services.security import validate_advisor_output

if False:  # pragma: no cover
    from dragun.services.budget import BudgetService
    from dragun.services.inventory import InventoryService


DecisionBand = Literal["green", "yellow", "orange", "red", "unknown"]


@dataclass
class ActionResult:
    reply: str
    intent: AgentIntent
    events: list[Event] = field(default_factory=list)
    inventory: list[InventoryRow] = field(default_factory=list)
    budgets: list[BudgetStatus] = field(default_factory=list)
    constraints: list[ConstraintAlert] = field(default_factory=list)
    decision_band: DecisionBand | None = None
    facts: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BackendActionRouter:
    inventory_service: "InventoryService"
    budget_service: "BudgetService"
    advisor: "AdvisorResponseService"
    # Set once per request in handle(); read by private methods
    _profile: UserProfile | None = field(default=None, init=False, repr=False)
    _history_text: str = field(default="", init=False, repr=False)

    async def handle(
        self,
        user: User,
        intent: AgentIntent,
        *,
        input_source: InputSource = InputSource.TEXT,
        user_profile: UserProfile | None = None,
    ) -> ActionResult:
        # Store per-request context so private methods can pass it to advisor
        from dragun.services.history import get_full_history
        self._profile = user_profile
        self._history_text = get_full_history(user.user_id, max_turns=3)

        if intent.intent == "log_purchase":
            return await self._log_purchase(user, intent, input_source)
        if intent.intent == "set_inventory_baseline":
            return await self._set_baseline(user, intent, input_source)
        if intent.intent == "remove_items":
            return await self._remove_items(user, intent)
        if intent.intent == "query_inventory":
            return await self._query_inventory(user, intent)
        if intent.intent == "create_budget":
            return await self._create_budget(user, intent)
        if intent.intent == "query_budget":
            return await self._query_budget(user, intent)
        if intent.intent == "create_constraint":
            return await self._create_constraint(user, intent)
        if intent.intent == "update_item_cost":
            return await self._update_item_cost(user, intent)
        if intent.intent == "retag_item":
            return await self._retag_item(user, intent)
        if intent.intent == "purchase_advice":
            return await self._purchase_advice(user, intent)
        if intent.intent == "update_profile":
            return await self._update_profile(user, intent)
        if intent.intent == "off_topic":
            return self._off_topic(intent)
        if intent.intent == "clear_inventory":
            return await self._clear_inventory(user, intent)
        if intent.intent == "clarify" or intent.needs_clarification:
            return ActionResult(
                reply=intent.clarifying_question or "What exactly should I guard or log?",
                intent=intent,
                inventory=self.inventory_service.query_inventory(user.user_id),
                budgets=self.budget_service.get_budget_statuses(user.user_id),
            )
        return await self._casual(user, intent)

    async def _log_purchase(self, user: User, intent: AgentIntent, input_source: InputSource) -> ActionResult:
        if not intent.items:
            return await self._clarify(user, intent, "What did you buy?")
        parsed = parsed_input_from_intent(intent, parsed_intent="purchase")
        evaluation = self.budget_service.evaluate_purchase(user.user_id, parsed.items)
        events = self.inventory_service.log_items(user, parsed, input_source=input_source)
        inventory = self.inventory_service.query_inventory(user.user_id)
        budgets = self.budget_service.get_budget_statuses(user.user_id)
        velocity_notes = self.inventory_service.velocity_notes(user.user_id, events)
        facts = {
            "action": "logged_purchase",
            "items": [{"item": e.item_normalized, "quantity": e.quantity, "total_cost": e.total_cost} for e in events],
            "inventory": _inventory_facts(inventory),
            "budgets": _budget_facts(budgets),
            "constraint_alerts": [alert.message for alert in evaluation.constraint_alerts],
            "velocity_notes": velocity_notes,
        }
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or _purchase_reply(
            inventory, budgets, evaluation.constraint_alerts, velocity_notes
        )
        return ActionResult(reply, intent, events, inventory, budgets, evaluation.constraint_alerts, facts=facts)

    async def _set_baseline(self, user: User, intent: AgentIntent, input_source: InputSource) -> ActionResult:
        if not intent.items:
            return await self._clarify(user, intent, "What do you already have?")
        parsed = parsed_input_from_intent(intent, parsed_intent="manual_inventory")
        events = self.inventory_service.log_items(user, parsed, input_source=input_source)
        inventory = self.inventory_service.query_inventory(user.user_id)
        budgets = self.budget_service.get_budget_statuses(user.user_id)
        facts = {"action": "baseline_set", "inventory": _inventory_facts(inventory)}
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or f"Baseline marked. You now have {_owned_text(inventory)}."
        return ActionResult(reply, intent, events, inventory, budgets, facts=facts)

    async def _remove_items(self, user: User, intent: AgentIntent) -> ActionResult:
        if not intent.items:
            return await self._clarify(user, intent, "What left the hoard?")
        events: list[Event] = []
        for item in intent.items:
            event = Event(
                event_id=str(uuid4()),
                user_id=user.user_id,
                event_type=EventType.DISCARD,
                item_description=item.name_raw,
                item_normalized=item.item_normalized,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                total_cost=item.total_cost,
                lifespan_type=item.lifespan_type,
                input_source=InputSource.TEXT,
                raw_input=intent.raw_input,
                event_timestamp=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            self.inventory_service.repository.create_event(event, item.tags or suggest_tags(item.item_normalized))
            events.append(event)
        inventory = self.inventory_service.query_inventory(user.user_id)
        budgets = self.budget_service.get_budget_statuses(user.user_id)
        facts = {"action": "removed_items", "items": [{"item": e.item_normalized, "quantity": e.quantity} for e in events]}
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or f"Removed. The hoard now shows {_owned_text(inventory)}."
        return ActionResult(reply, intent, events, inventory, budgets, facts=facts)

    async def _query_inventory(self, user: User, intent: AgentIntent) -> ActionResult:
        query = intent.query
        item_filter = query.item_normalized if query else None
        inventory = self.inventory_service.query_inventory(user.user_id, item_filter=item_filter)
        if query and query.tags:
            tag_set = set(query.tags)
            inventory = [row for row in inventory if tag_set.intersection(row.tags)]
        budgets = self.budget_service.get_budget_statuses(user.user_id)
        facts = {"action": "query_inventory", "inventory": _inventory_facts(inventory)}
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or (
            f"In the hoard: {_owned_text(inventory)}." if inventory else "The lair is empty for that query."
        )
        return ActionResult(reply, intent, inventory=inventory, budgets=budgets, facts=facts)

    async def _create_budget(self, user: User, intent: AgentIntent) -> ActionResult:
        if not intent.budget or intent.budget.amount is None:
            return await self._clarify(user, intent, "How much should I guard for that budget?")
        budget = self.budget_service.create_budget(
            user.user_id,
            BudgetCreateRequest(
                budget_scope=intent.budget.scope,
                scope_tags=[] if intent.budget.scope == "all" else [intent.budget.scope],
                budget_amount=intent.budget.amount,
                period_type=intent.budget.period_type,
            ),
        )
        status = self.budget_service.get_budget_status(budget)
        budgets = self.budget_service.get_budget_statuses(user.user_id)
        facts = {"action": "budget_created", "budget": status.model_dump(mode="json")}
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or (
            f"Marked. {status.budget_scope} has ${status.amount_remaining:.2f} left this period."
        )
        return ActionResult(reply, intent, budgets=budgets, facts=facts)

    async def _query_budget(self, user: User, intent: AgentIntent) -> ActionResult:
        budgets = self.budget_service.get_budget_statuses(user.user_id)
        scope = intent.query.scope if intent.query else None
        if scope:
            budgets = [budget for budget in budgets if scope in budget.budget_scope]
        facts = {"action": "query_budget", "budgets": _budget_facts(budgets)}
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or (
            "; ".join(f"{b.budget_scope}: ${b.amount_remaining:.2f} left" for b in budgets)
            if budgets
            else "No budgets are guarding this category yet."
        )
        return ActionResult(reply, intent, budgets=budgets, facts=facts)

    async def _create_constraint(self, user: User, intent: AgentIntent) -> ActionResult:
        if not intent.constraint or intent.constraint.threshold_value is None:
            return await self._clarify(user, intent, "What limit should I guard?")
        constraint = self.budget_service.create_constraint(
            user.user_id,
            ConstraintCreateRequest(
                constraint_type=intent.constraint.constraint_type,
                scope_tags=intent.constraint.scope_tags,
                item_normalized=intent.constraint.item_normalized,
                operator=intent.constraint.operator,
                threshold_value=intent.constraint.threshold_value,
            ),
        )
        facts = {"action": "constraint_created", "constraint": constraint.model_dump(mode="json")}
        item = constraint.item_normalized or ", ".join(constraint.scope_tags) or "that scope"
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or (
            f"Guard set. I will flag {item} when it crosses {constraint.threshold_value:g}."
        )
        return ActionResult(reply, intent, constraints=[], facts=facts)

    async def _update_item_cost(self, user: User, intent: AgentIntent) -> ActionResult:
        if not intent.items or (intent.items[0].unit_cost is None and intent.items[0].total_cost is None):
            return await self._clarify(user, intent, "Which item price should I update, and to what?")
        item = intent.items[0]
        unit_cost = item.unit_cost or item.total_cost or item.estimated_total_cost
        if unit_cost is None:
            return await self._clarify(user, intent, "What is the new unit price?")
        event = Event(
            event_id=str(uuid4()),
            user_id=user.user_id,
            event_type=EventType.MANUAL_INVENTORY,
            item_description=item.item_normalized,
            item_normalized=item.item_normalized,
            quantity=0,
            unit_cost=float(unit_cost),
            total_cost=None,
            lifespan_type=infer_lifespan_type(item.item_normalized),
            input_source=InputSource.MANUAL,
            raw_input=intent.raw_input,
            event_timestamp=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        self.inventory_service.repository.create_event(event, item.tags or suggest_tags(item.item_normalized))
        inventory = self.inventory_service.query_inventory(user.user_id)
        facts = {"action": "cost_updated", "item": item.item_normalized, "unit_cost": unit_cost}
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or f"Price updated. {item.item_normalized} is now marked at ${unit_cost:.2f}."
        return ActionResult(reply, intent, [event], inventory, self.budget_service.get_budget_statuses(user.user_id), facts=facts)

    async def _retag_item(self, user: User, intent: AgentIntent) -> ActionResult:
        if not intent.items or not intent.items[0].tags:
            return await self._clarify(user, intent, "Which item should I retag, and what tags should it use?")
        item = intent.items[0]
        updated = self.inventory_service.retag_item(user.user_id, item.item_normalized, item.tags)
        inventory = self.inventory_service.query_inventory(user.user_id)
        facts = {"action": "retagged", "item": item.item_normalized, "tags": item.tags, "events_updated": updated}
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or f"Retagged {item.item_normalized} as {', '.join(item.tags)}."
        return ActionResult(reply, intent, inventory=inventory, budgets=self.budget_service.get_budget_statuses(user.user_id), facts=facts)

    async def _purchase_advice(self, user: User, intent: AgentIntent) -> ActionResult:
        inventory = self.inventory_service.query_inventory(user.user_id)
        budgets = self.budget_service.get_budget_statuses(user.user_id)
        decision = evaluate_purchase_decision(intent.items, budgets)
        facts = {
            "action": "purchase_advice",
            "decision_band": decision["band"],
            "items": [item.model_dump(mode="json") for item in intent.items],
            "budget_match": decision.get("budget"),
            "reason": decision.get("reason"),
            "inventory": _inventory_facts(inventory),
        }
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or decision_reply(decision)
        return ActionResult(reply, intent, inventory=inventory, budgets=budgets, decision_band=decision["band"], facts=facts)

    async def _update_profile(self, user: User, intent: AgentIntent) -> ActionResult:
        repo = self.inventory_service.repository
        pu = intent.profile_update
        # Merge with existing profile (or create a blank one)
        existing = repo.get_user_profile(user.user_id)
        if existing:
            new_profile = existing.model_copy(deep=True)
        else:
            new_profile = UserProfile(user_id=user.user_id)

        if pu:
            if pu.pain_points:
                merged = list({*new_profile.pain_points, *pu.pain_points})
                new_profile.pain_points = merged
            if pu.primary_goal:
                new_profile.primary_goal = pu.primary_goal
            if pu.preferred_tone:
                new_profile.preferred_tone = pu.preferred_tone

        new_profile.updated_at = utc_now()
        saved = repo.upsert_user_profile(new_profile)
        self._profile = saved  # advisor will use the freshly saved profile

        facts = {
            "action": "profile_updated",
            "pain_points": saved.pain_points,
            "primary_goal": saved.primary_goal,
            "preferred_tone": saved.preferred_tone,
        }
        inventory = self.inventory_service.query_inventory(user.user_id)
        budgets = self.budget_service.get_budget_statuses(user.user_id)
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or (
            "Noted. I'll keep that in mind going forward."
        )
        return ActionResult(reply, intent, inventory=inventory, budgets=budgets, facts=facts)

    async def _casual(self, user: User, intent: AgentIntent) -> ActionResult:
        inventory = self.inventory_service.query_inventory(user.user_id)
        budgets = self.budget_service.get_budget_statuses(user.user_id)
        facts = {"action": "casual", "inventory_count": len(inventory), "budgets": _budget_facts(budgets)}
        reply = await self.advisor.reply(intent.raw_input, intent, facts, user_profile=self._profile, history_text=self._history_text) or "I am here. Tell me what enters the hoard, or ask if the coins can spare it."
        return ActionResult(reply, intent, inventory=inventory, budgets=budgets, facts=facts)

    def _off_topic(self, intent: AgentIntent) -> ActionResult:
        """Return a static reply immediately — no LLM call, no DB queries."""
        raw = intent.raw_input.lower()
        _investment_terms = {
            "stock", "stocks", "invest", "investing", "investment", "investments",
            "portfolio", "crypto", "cryptocurrency", "bitcoin", "ethereum", "nft",
            "etf", "mutual fund", "trading", "trade", "market", "markets",
            "nasdaq", "s&p", "dividend", "dividends", "bond", "bonds",
            "equity", "equities", "forex", "hedge fund", "options contract",
            "financial advice", "wealth management",
        }
        is_investment = any(term in raw for term in _investment_terms)
        if is_investment:
            reply = (
                "Dragun tracks what you spend day-to-day — investment and market advice "
                "isn't something I offer, and for good reason: that territory needs a "
                "licensed financial advisor, not a dragon. I'll stay in my lane."
            )
        else:
            reply = "The dragon's eyes are on your hoard, not the world beyond it. Tell me what you've spent, what you own, or what you're thinking of buying."
        return ActionResult(reply=reply, intent=intent)

    async def _clear_inventory(self, user: User, intent: AgentIntent) -> ActionResult:
        """Wipe all inventory — requires confirmation from the previous turn."""
        _CONFIRM_PROMPT = "Your entire hoard will be wiped — this can't be undone. Reply **yes, clear everything** to confirm."
        _CONFIRM_MARKERS = {"yes, clear everything", "yes clear everything", "confirm", "yes do it", "yes wipe", "yes delete everything"}

        # Check if the previous Dragun turn was our confirmation prompt
        confirmed = any(marker in self._history_text.lower() for marker in ["wipe — this can't be undone", "yes, clear everything to confirm"]) \
                    and any(marker in intent.raw_input.lower() for marker in _CONFIRM_MARKERS)

        if not confirmed:
            inventory = self.inventory_service.query_inventory(user.user_id)
            return ActionResult(
                reply=_CONFIRM_PROMPT,
                intent=intent,
                inventory=inventory,
                budgets=self.budget_service.get_budget_statuses(user.user_id),
            )

        # Confirmed — delete all inventory items
        inventory = self.inventory_service.query_inventory(user.user_id)
        for row in inventory:
            event = Event(
                event_id=str(uuid4()),
                user_id=user.user_id,
                event_type=EventType.DISCARD,
                item_description=row.item_normalized,
                item_normalized=row.item_normalized,
                quantity=row.quantity,
                unit_cost=row.avg_unit_cost,
                total_cost=None,
                lifespan_type=row.lifespan_type,
                input_source=InputSource.TEXT,
                raw_input=intent.raw_input,
                event_timestamp=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            self.inventory_service.repository.create_event(event, row.tags)

        return ActionResult(
            reply="The hoard is empty. Fresh start — what enters the lair?",
            intent=intent,
            inventory=[],
            budgets=self.budget_service.get_budget_statuses(user.user_id),
        )

    async def _clarify(self, user: User, intent: AgentIntent, question: str) -> ActionResult:
        return ActionResult(
            reply=question,
            intent=intent,
            inventory=self.inventory_service.query_inventory(user.user_id),
            budgets=self.budget_service.get_budget_statuses(user.user_id),
        )


@dataclass(slots=True)
class AdvisorResponseService:
    """Facts -> Dragun voice. Does not query or compute backend state."""

    async def reply(
        self,
        user_message: str,
        intent: AgentIntent,
        facts: dict[str, Any],
        *,
        user_profile: "UserProfile | None" = None,
        history_text: str = "",
    ) -> str | None:
        settings = get_settings()
        if not settings.google_api_key:
            return None
        context = await get_instruction_retriever().retrieve_as_context(
            user_message, intent=intent.intent, limit=2
        )

        profile_section = ""
        if user_profile:
            parts: list[str] = []
            if user_profile.primary_goal:
                parts.append(f"Primary goal: {user_profile.primary_goal}")
            if user_profile.pain_points:
                parts.append(f"Known pain points: {', '.join(user_profile.pain_points)}")
            if user_profile.preferred_tone and user_profile.preferred_tone != "balanced":
                parts.append(f"Preferred tone: {user_profile.preferred_tone}")
            if parts:
                profile_section = "User profile:\n" + "\n".join(parts)

        # history_text is already compressed by compress_history_for_injection()
        # in get_full_history() — it contains no raw user content, only topic labels.
        history_section = (
            f"\n{history_text}"
        ) if history_text else ""

        prompt = f"""
You are Dragun — a sharp, warm financial guardian speaking directly to your user. Python already did the database work.

Rules:
- Use only the JSON facts below. Do not invent counts, spend, or budgets.
- Be equal parts people-pleasing and budget-protective.
- Never shame. Do nudge when the decision band is orange/red.
- Keep it to 1-3 concise sentences.
- If facts.action is casual, answer warmly in character.
- Adapt your tone and advice to the user profile if one is provided.
- If recent conversation is present, maintain continuity — don't repeat what was just said.
- Never open by echoing the user's greeting back (e.g. if they say "hey", do not start with "Hey"). Vary your sentence starters naturally.

Relevant voice guidance:
{context or "No extra context."}

{profile_section}{history_section}

User said: {user_message}
Extracted intent: {intent.intent}
Backend facts JSON:
{json.dumps(facts, default=str)}
"""
        try:
            client = genai.Client(api_key=settings.google_api_key)
            response = await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.55, max_output_tokens=350),
            )
            raw_reply = (response.text or "").strip()
            if not raw_reply:
                return None
            # Validate output for signs of injection success or persona break.
            return validate_advisor_output(raw_reply) or None
        except Exception:
            return None


def evaluate_purchase_decision(items: list[IntentItem], budgets: list[BudgetStatus]) -> dict[str, Any]:
    item = items[0] if items else None
    if not item:
        return {"band": "unknown", "reason": "No item was provided."}
    estimated_cost = item.estimated_total_cost or item.total_cost
    if estimated_cost is None and item.unit_cost is not None:
        estimated_cost = item.unit_cost * item.quantity
    matching = _matching_budget(item, budgets)
    if estimated_cost is None:
        return {
            "band": "unknown",
            "reason": "No estimated cost was provided.",
            "budget": matching.model_dump(mode="json") if matching else None,
        }
    if not matching:
        return {
            "band": "yellow",
            "reason": "No matching budget is guarding this item yet.",
            "estimated_cost": estimated_cost,
        }
    remaining_after = matching.amount_remaining - estimated_cost
    daily_after = remaining_after / max(matching.days_remaining, 1)
    if remaining_after < 0:
        band: DecisionBand = "red"
        reason = "This would put the matching budget below zero."
    elif daily_after < 1:
        band = "orange"
        reason = "This leaves very little daily room for the rest of the period."
    elif estimated_cost > max(matching.amount_remaining * 0.35, 0):
        band = "yellow"
        reason = "This is affordable, but it uses a noticeable chunk of the remaining budget."
    else:
        band = "green"
        reason = "The matching budget can absorb this."
    return {
        "band": band,
        "reason": reason,
        "estimated_cost": estimated_cost,
        "remaining_after": round(remaining_after, 2),
        "daily_pace_after": round(daily_after, 2),
        "budget": matching.model_dump(mode="json"),
    }


def decision_reply(decision: dict[str, Any]) -> str:
    band = decision["band"]
    if band == "green":
        return f"You can do it. The matching budget can absorb about ${decision.get('estimated_cost', 0):.2f}; the hoard stays steady."
    if band == "yellow":
        return f"You can, but keep it small. {decision.get('reason', 'The coins are watching.')}"
    if band == "orange":
        return f"I'd pause unless this really matters. {decision.get('reason', 'You are close to the line.')}"
    if band == "red":
        return f"I am going to be the annoying dragon: skip this one if staying on budget matters. {decision.get('reason', '')}"
    return "Name the price and I can give you a sharper answer."


def _matching_budget(item: IntentItem, budgets: list[BudgetStatus]) -> BudgetStatus | None:
    tags = set(item.tags)
    for budget in budgets:
        if budget.budget_scope == "all" or budget.budget_scope == item.item_normalized or budget.budget_scope in tags:
            return budget
    return None


def _inventory_facts(inventory: list[InventoryRow]) -> list[dict[str, Any]]:
    return [
        {"item": row.item_normalized, "quantity": row.current_quantity, "tags": row.tags, "avg_unit_cost": row.avg_unit_cost}
        for row in inventory[:20]
    ]


def _budget_facts(budgets: list[BudgetStatus]) -> list[dict[str, Any]]:
    return [
        {
            "scope": row.budget_scope,
            "amount_spent": row.amount_spent,
            "amount_remaining": row.amount_remaining,
            "daily_pace": row.daily_pace,
            "days_remaining": row.days_remaining,
            "pct_consumed": row.pct_consumed,
        }
        for row in budgets
    ]


def _owned_text(inventory: list[InventoryRow]) -> str:
    return ", ".join(f"{row.current_quantity:g} {row.item_normalized}" for row in inventory[:8]) or "nothing logged yet"


def _purchase_reply(
    inventory: list[InventoryRow],
    budgets: list[BudgetStatus],
    alerts: list[ConstraintAlert],
    velocity_notes: list[str],
) -> str:
    parts = [f"Got it. You now have {_owned_text(inventory)}."]
    if budgets:
        parts.append(
            "; ".join(
                f"{budget.budget_scope} has ${budget.amount_remaining:.2f} left (${budget.daily_pace:.2f}/day)"
                for budget in budgets
            )
            + "."
        )
    if alerts:
        parts.append(" ".join(alert.message for alert in alerts))
    if velocity_notes:
        parts.append(" ".join(velocity_notes))
    return " ".join(parts)
