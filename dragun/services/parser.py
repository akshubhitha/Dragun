from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

from dragun.config import get_settings
from dragun.models import ConstraintType, ParsedInput, ParsedItem, PeriodType
from dragun.services.catalog import infer_lifespan_type, normalize_item_name, suggest_tags


PRICE_RE = re.compile(
    r"(?P<prefix>\$)?(?P<amount>\d+(?:\.\d{1,2})?)\s*(?P<suffix>bucks?|dollars?|usd)?",
    re.IGNORECASE,
)
QTY_ITEM_RE = re.compile(
    r"(?:(?P<qty>\d+)\s+)?(?P<item>[a-zA-Z][a-zA-Z0-9' -]*?)(?=,| and | with | for |$)"
)


@dataclass
class InputParserService:
    """Parses text input into Dragun line items.

    Gemini Flash is the primary parser when configured. The deterministic parser
    keeps local tests and demos usable without Google Cloud credentials.
    """

    use_gemini: bool = True

    async def parse(self, raw_input: str) -> ParsedInput:
        text = raw_input.strip()
        if self.use_gemini:
            parsed = await self._parse_with_gemini(text)
            if parsed:
                return parsed
        return parse_text_fallback(text)

    async def _parse_with_gemini(self, raw_input: str) -> ParsedInput | None:
        settings = get_settings()
        if not settings.google_api_key:
            return None

        prompt = f"""
Parse this Dragun user input into strict JSON.

Return exactly:
{{
  "intent": "purchase" | "manual_inventory" | "budget_create" | "constraint_create" | "inventory_query" | "unknown",
  "items": [
    {{
      "description": "raw item phrase",
      "quantity": 1,
      "unit_cost": null,
      "total_cost": null,
      "lifespan_type": "consumable" | "durable" | "service",
      "tags": ["lowercase tag"]
    }}
  ],
  "budget": {{
    "scope": "clothing",
    "amount": 200,
    "period_type": "monthly"
  }},
  "constraint": {{
    "constraint_type": "inventory_cap" | "hard_budget_limit" | "pace_alert",
    "scope": "shirts",
    "operator": "count_exceeds",
    "threshold_value": 15
  }},
  "family_member": null
}}

Rules:
- Split "3 shirts, 2 dresses, 1 pant - 50 bucks" into three items and distribute the total by quantity if no per-item prices exist.
- Normalize only obvious shorthand in tags and lifespan, not description.
- Treat "I have 12 shirts" as manual_inventory.
- Treat "budget 200 for clothing" as budget_create.
- Treat "don't let me own more than 15 shirts" as constraint_create inventory_cap.

Input: {raw_input}
"""
        try:
            client = genai.Client(api_key=settings.google_api_key)
            response = await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            payload = json.loads(response.text or "{}")
            return _parsed_input_from_payload(raw_input, payload)
        except Exception:
            return None


def parse_text_fallback(raw_input: str) -> ParsedInput:
    text = raw_input.strip()
    lowered = text.lower()
    if not text:
        return ParsedInput(intent="unknown", raw=raw_input)

    constraint = _parse_constraint(lowered)
    if constraint:
        return ParsedInput(intent="constraint_create", raw=raw_input, **constraint)

    budget = _parse_budget(lowered)
    if budget:
        return ParsedInput(intent="budget_create", raw=raw_input, **budget)

    if _looks_like_inventory_query(lowered):
        items = _extract_items_without_prices(text)
        return ParsedInput(intent="inventory_query", raw=raw_input, items=items)

    event_type = "manual_inventory" if _looks_like_manual_inventory(lowered) else "purchase"
    items = _extract_items(text)
    return ParsedInput(intent=event_type, raw=raw_input, items=items)


def _parse_budget(text: str) -> dict[str, Any] | None:
    if "budget" not in text and "spend" not in text:
        return None
    amount = _last_price(text)
    if amount is None:
        return None
    period_type = "weekly" if "week" in text else "monthly"
    scope = "all"
    scope_match = re.search(r"(?:for|on)\s+([a-z][a-z -]+?)(?:\s+(?:this|per|a|each)\s+(?:month|week)|$)", text)
    if scope_match:
        scope = normalize_item_name(scope_match.group(1))
    return {"budget_scope": scope, "budget_amount": amount, "period_type": period_type}


def _parse_constraint(text: str) -> dict[str, Any] | None:
    cap_match = re.search(
        r"(?:more than|over|above|max(?:imum)?(?: of)?)\s+(?P<threshold>\d+)\s+(?P<scope>[a-z][a-z -]+)",
        text,
    )
    if cap_match and ("own" in text or "have" in text or "inventory" in text):
        scope = normalize_item_name(cap_match.group("scope"))
        return {
            "constraint_type": ConstraintType.INVENTORY_CAP,
            "constraint_item": scope,
            "constraint_threshold": float(cap_match.group("threshold")),
        }

    budget_match = re.search(
        r"(?:more than|over|above)\s+\$?(?P<threshold>\d+(?:\.\d{1,2})?)\s+(?:on|for)\s+(?P<scope>[a-z][a-z -]+)",
        text,
    )
    if budget_match and ("don't" in text or "do not" in text or "limit" in text):
        return {
            "constraint_type": ConstraintType.HARD_BUDGET_LIMIT,
            "budget_scope": normalize_item_name(budget_match.group("scope")),
            "constraint_threshold": float(budget_match.group("threshold")),
        }

    pace_match = re.search(r"(?:below|under)\s+\$?(?P<threshold>\d+(?:\.\d{1,2})?)\s*(?:/day|per day|a day)", text)
    if pace_match:
        return {
            "constraint_type": ConstraintType.PACE_ALERT,
            "budget_scope": "all",
            "constraint_threshold": float(pace_match.group("threshold")),
        }
    return None


def _looks_like_manual_inventory(text: str) -> bool:
    return bool(re.search(r"\b(i have|currently have|own|inventory|baseline)\b", text))


def _looks_like_inventory_query(text: str) -> bool:
    return bool(re.search(r"\b(how many|what do i have|show inventory|inventory)\b", text)) and "budget" not in text


def _extract_items(raw_input: str) -> list[ParsedItem]:
    cleaned, total_cost = _strip_price(raw_input)
    cleaned = re.sub(r"\b(i have|currently have|own|bought|buying|get|got|about|around)\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bat\b.+$", "", cleaned, flags=re.I)
    fragments = _split_item_fragments(cleaned)
    if not fragments:
        return []

    quantities: list[int] = []
    descriptions: list[str] = []
    for fragment in fragments:
        qty, description = _parse_item_fragment(fragment)
        if description:
            quantities.append(qty)
            descriptions.append(description)

    if not descriptions:
        return []

    total_units = sum(quantities) or len(quantities)
    items: list[ParsedItem] = []
    for qty, description in zip(quantities, descriptions, strict=True):
        item_total = round(total_cost * (qty / total_units), 2) if total_cost is not None else None
        item = _line_item(description=description, quantity=qty, total_cost=item_total)
        items.append(item)
    return items


def _extract_items_without_prices(raw_input: str) -> list[ParsedItem]:
    text = re.sub(r"\b(how many|do i have|what do i have|show inventory|inventory|of)\b", "", raw_input, flags=re.I)
    return [_line_item(description=text.strip(" ?.,") or "all", quantity=1)]


def _strip_price(raw_input: str) -> tuple[str, float | None]:
    matches = list(PRICE_RE.finditer(raw_input))
    price_matches = [
        match
        for match in matches
        if match.group("prefix") or match.group("suffix") or _price_is_contextual(raw_input, match.start())
    ]
    if not price_matches:
        return raw_input, None
    match = price_matches[-1]
    amount = float(match.group("amount"))
    cleaned = f"{raw_input[: match.start()]} {raw_input[match.end() :]}"
    return cleaned.strip(" -—,."), amount


def _price_is_contextual(raw_input: str, start: int) -> bool:
    before = raw_input[max(0, start - 12) : start].lower()
    after = raw_input[start : start + 20].lower()
    return any(token in before + after for token in ("cost", "total", "budget", "spend", "monthly", "weekly"))


def _last_price(text: str) -> float | None:
    cleaned, amount = _strip_price(text)
    if amount is not None:
        return amount
    amounts = re.findall(r"\d+(?:\.\d{1,2})?", cleaned)
    return float(amounts[-1]) if amounts else None


def _split_item_fragments(text: str) -> list[str]:
    normalized = text.replace("—", ",").replace("-", ",")
    normalized = re.sub(r"\band\b", ",", normalized, flags=re.I)
    fragments = [fragment.strip(" .,") for fragment in normalized.split(",")]
    expanded: list[str] = []
    for fragment in fragments:
        matches = list(re.finditer(r"(?:^|\s)(\d+)\s+[a-zA-Z]", fragment))
        if len(matches) <= 1:
            expanded.append(fragment)
            continue
        starts = [match.start(1) for match in matches] + [len(fragment)]
        for idx in range(len(starts) - 1):
            expanded.append(fragment[starts[idx] : starts[idx + 1]].strip())
    return [fragment for fragment in expanded if fragment]


def _parse_item_fragment(fragment: str) -> tuple[int, str]:
    match = re.match(r"(?:(?P<qty>\d+)\s+)?(?P<description>.+)", fragment.strip())
    if not match:
        return 1, ""
    qty = int(match.group("qty") or 1)
    description = normalize_item_name(match.group("description"))
    return qty, description


def _line_item(description: str, quantity: int, total_cost: float | None = None) -> ParsedItem:
    normalized = normalize_item_name(description)
    unit_cost = round(total_cost / quantity, 2) if total_cost is not None and quantity else None
    return ParsedItem(
        description=description,
        item_normalized=normalized,
        quantity=quantity,
        unit_cost=unit_cost,
        total_cost=total_cost,
        lifespan_type=infer_lifespan_type(normalized),
        suggested_tags=suggest_tags(normalized),
    )


def _parsed_input_from_payload(raw_input: str, payload: dict[str, Any]) -> ParsedInput:
    items = []
    for item in payload.get("items") or []:
        description = str(item.get("description") or item.get("item_normalized") or "").strip()
        if not description:
            continue
        normalized = normalize_item_name(str(item.get("item_normalized") or description))
        tags = item.get("tags") or item.get("suggested_tags") or suggest_tags(normalized)
        quantity = int(item.get("quantity") or 1)
        total_cost = item.get("total_cost")
        unit_cost = item.get("unit_cost")
        if total_cost is None and unit_cost is not None:
            total_cost = float(unit_cost) * quantity
        if unit_cost is None and total_cost is not None and quantity:
            unit_cost = float(total_cost) / quantity
        items.append(
            ParsedItem(
                description=description,
                item_normalized=normalized,
                quantity=quantity,
                unit_cost=round(float(unit_cost), 2) if unit_cost is not None else None,
                total_cost=round(float(total_cost), 2) if total_cost is not None else None,
                lifespan_type=item.get("lifespan_type") or infer_lifespan_type(normalized),
                suggested_tags=[normalize_item_name(str(tag)) for tag in tags],
            )
        )

    return ParsedInput(
        intent=payload.get("intent") or "purchase",
        raw=raw_input,
        items=items,
        budget_scope=(payload.get("budget") or {}).get("scope"),
        budget_amount=(payload.get("budget") or {}).get("amount"),
        period_type=PeriodType((payload.get("budget") or {}).get("period_type", "monthly")),
        constraint_type=(payload.get("constraint") or {}).get("constraint_type"),
        constraint_threshold=(payload.get("constraint") or {}).get("threshold_value"),
        constraint_item=(payload.get("constraint") or {}).get("scope"),
        family_member=payload.get("family_member"),
    )


def parse_text_input(raw_input: str) -> ParsedInput:
    """Synchronous fallback-only parser. Use parse_text_input_async for Gemini."""
    return parse_text_fallback(raw_input)


async def parse_text_input_async(raw_input: str) -> ParsedInput:
    """Use Gemini Flash if GOOGLE_API_KEY is set, otherwise fall back to deterministic parser."""
    parser = InputParserService(use_gemini=True)
    return await parser.parse(raw_input)


async def generate_dragon_reply(
    user_message: str,
    inventory_summary: str,
    budget_summary: str,
    constraint_alerts: str,
    velocity_notes: str,
) -> str | None:
    """Ask Gemini Flash to generate the dragon's reply. Returns None if unavailable."""
    settings = get_settings()
    if not settings.google_api_key:
        return None
    try:
        prompt = f"""You are Dragun, a personal consumption intelligence dragon. You are the user's financial hoard guardian.

Personality: warm, direct, occasionally blunt, never judgmental. Protective, not controlling.
Speak concisely — no filler, no corporate language. Use "you" not "the user".
Never say "I recommend against" or "that's irresponsible". Just show truth and let them decide.
You can handle casual conversation naturally — greetings, questions, anything. Stay in character.

The user just said: "{user_message}"

Current state of their hoard:
Inventory: {inventory_summary or "empty so far"}
Budgets: {budget_summary or "none set yet"}
Constraint alerts: {constraint_alerts or "none"}
Velocity notes: {velocity_notes or "none"}

Reply as Dragun in 1–3 sentences max. If it's a greeting or casual message, respond warmly and briefly in character.
If it's about purchases or budgets, lead with the hoard state. Never make up inventory data not listed above.
"""
        client = genai.Client(api_key=settings.google_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=200),
        )
        return (response.text or "").strip() or None
    except Exception:
        return None
