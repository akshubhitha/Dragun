"""Lightweight deterministic parser for item logging text."""

from __future__ import annotations

import re


_PRICE_PATTERN = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*(?:\$|dollars?|bucks?)", re.IGNORECASE)
_LINE_ITEM_PATTERN = re.compile(
    r"(?P<qty>\d+)\s*(?P<name>[a-zA-Z][a-zA-Z\s\-]+?)(?=,|$)", re.IGNORECASE
)

_NORMALIZATION_MAP = {
    "deo": "deodorant",
    "deo stick": "deodorant",
    "pant": "pants",
    "shirt": "shirts",
    "dress": "dresses",
}

_TAG_MAP = {
    "shirt": ["clothing"],
    "shirts": ["clothing"],
    "pant": ["clothing"],
    "pants": ["clothing"],
    "dress": ["clothing"],
    "dresses": ["clothing"],
    "deodorant": ["body care", "essentials"],
    "milk": ["food", "groceries"],
    "eggs": ["food", "groceries"],
    "bread": ["food", "groceries"],
    "chicken": ["food", "groceries"],
    "gym membership": ["wellness", "fitness", "recurring"],
}


def normalize_item_name(raw_name: str) -> str:
    lowered = " ".join(raw_name.strip().lower().split())
    if lowered in _NORMALIZATION_MAP:
        return _NORMALIZATION_MAP[lowered]
    return lowered


def infer_lifespan_type(item_name: str) -> str:
    if "membership" in item_name or "service" in item_name:
        return "service"
    if item_name in {"pants", "shirts", "dresses", "jacket", "jackets", "shoes"}:
        return "durable"
    return "consumable"


def infer_tags(item_name: str) -> list[str]:
    if item_name in _TAG_MAP:
        return _TAG_MAP[item_name]
    if any(token in item_name for token in ["shirt", "dress", "pant", "shoe", "jacket"]):
        return ["clothing"]
    return ["misc"]


def parse_purchase_text(text: str) -> list[dict]:
    """
    Parse natural-ish text into line items.

    Supported examples:
    - "3 shirts, 2 dresses, 1 pant — 50 bucks"
    - "coffee 7 bucks"
    - "gym membership 200"
    """
    normalized_text = text.strip()
    lower = normalized_text.lower()

    total_cost: float | None = None
    price_match = _PRICE_PATTERN.search(lower)
    if price_match:
        total_cost = float(price_match.group("amount"))
        lower = _PRICE_PATTERN.sub("", lower).strip(" -,:")

    items: list[dict] = []
    for match in _LINE_ITEM_PATTERN.finditer(lower):
        qty = int(match.group("qty"))
        raw_name = match.group("name").strip(" -")
        name = normalize_item_name(raw_name)
        items.append(
            {
                "description": raw_name,
                "item_normalized": name,
                "quantity": qty,
                "lifespan_type": infer_lifespan_type(name),
                "suggested_tags": infer_tags(name),
            }
        )

    if not items:
        # fallback: "coffee 7 bucks" or "gym membership 200"
        compact = lower.strip(" -")
        trailing_number = re.search(r"(.+?)\s+(\d+(?:\.\d+)?)$", compact)
        if trailing_number:
            possible_name = trailing_number.group(1).strip()
            if total_cost is None:
                total_cost = float(trailing_number.group(2))
            name = normalize_item_name(possible_name)
            items.append(
                {
                    "description": possible_name,
                    "item_normalized": name,
                    "quantity": 1,
                    "lifespan_type": infer_lifespan_type(name),
                    "suggested_tags": infer_tags(name),
                }
            )
        elif compact:
            name = normalize_item_name(compact)
            items.append(
                {
                    "description": compact,
                    "item_normalized": name,
                    "quantity": 1,
                    "lifespan_type": infer_lifespan_type(name),
                    "suggested_tags": infer_tags(name),
                }
            )

    if total_cost is not None and items:
        total_qty = sum(item["quantity"] for item in items)
        unit_estimate = total_cost / total_qty if total_qty else total_cost
        for item in items:
            item["unit_cost"] = round(unit_estimate, 2)
            item["total_cost"] = round(item["quantity"] * unit_estimate, 2)
    else:
        for item in items:
            item["unit_cost"] = None
            item["total_cost"] = None

    return items

