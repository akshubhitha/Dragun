from __future__ import annotations

import re
from dataclasses import dataclass

from dragun.models import LifespanType

@dataclass(frozen=True)
class CatalogEntry:
    normalized: str
    tags: tuple[str, ...]
    lifespan_type: str = "durable"


CATALOG: dict[str, CatalogEntry] = {
    "deo": CatalogEntry("deodorant", ("body care", "essentials"), "consumable"),
    "deodorant": CatalogEntry("deodorant", ("body care", "essentials"), "consumable"),
    "shirt": CatalogEntry("shirt", ("clothing",), "durable"),
    "shirts": CatalogEntry("shirt", ("clothing",), "durable"),
    "dress": CatalogEntry("dress", ("clothing",), "durable"),
    "dresses": CatalogEntry("dress", ("clothing",), "durable"),
    "pant": CatalogEntry("pant", ("clothing",), "durable"),
    "pants": CatalogEntry("pant", ("clothing",), "durable"),
    "jeans": CatalogEntry("jeans", ("clothing",), "durable"),
    "shoe": CatalogEntry("shoes", ("clothing",), "durable"),
    "shoes": CatalogEntry("shoes", ("clothing",), "durable"),
    "coffee": CatalogEntry("coffee", ("food", "drink"), "consumable"),
    "groceries": CatalogEntry("groceries", ("food", "essentials"), "consumable"),
    "milk": CatalogEntry("milk", ("food", "essentials"), "consumable"),
    "eggs": CatalogEntry("eggs", ("food", "essentials"), "consumable"),
    "bread": CatalogEntry("bread", ("food", "essentials"), "consumable"),
    "chicken": CatalogEntry("chicken", ("food", "essentials"), "consumable"),
    "gym membership": CatalogEntry("gym membership", ("wellness", "fitness", "recurring"), "service"),
    "membership": CatalogEntry("gym membership", ("wellness", "fitness", "recurring"), "service"),
    "vitamins": CatalogEntry("vitamins", ("wellness", "body care"), "consumable"),
    "charger": CatalogEntry("phone charger", ("electronics",), "durable"),
    "chargers": CatalogEntry("phone charger", ("electronics",), "durable"),
    "dinner": CatalogEntry("dinner", ("dining", "food"), "consumable"),
    "lunch": CatalogEntry("lunch", ("dining", "food"), "consumable"),
}


TAG_KEYWORDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("gym|fitness|massage|class|wellness", ("wellness",), "service"),
    ("restaurant|dinner|lunch|coffee|takeout", ("dining", "food"), "consumable"),
    ("milk|egg|bread|chicken|snack|grocery|groceries|food", ("food", "essentials"), "consumable"),
    ("shirt|dress|pant|jean|shoe|jacket|sock|closet|short|sweat|trunk|hoodie|sweater|cardigan|coat|blazer|skirt|legging|underwear|bra|brief|boxer|swimsuit|bikini|hat|cap|belt|scarf|glove|boot|sandal|slipper|sneaker", ("clothing",), "durable"),
    ("soap|shampoo|deo|deodorant|toothpaste|vitamin", ("body care", "essentials"), "consumable"),
    ("charger|phone|cable|laptop|headphone", ("electronics",), "durable"),
)


def normalize_item(description: str) -> CatalogEntry:
    clean = re.sub(r"[^a-z0-9 ]+", " ", description.lower()).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        return CatalogEntry("item", ("uncategorized",), "durable")

    if clean in CATALOG:
        return CATALOG[clean]

    singular = clean[:-1] if clean.endswith("s") and len(clean) > 3 else clean
    if singular in CATALOG:
        return CATALOG[singular]

    for pattern, tags, lifespan_type in TAG_KEYWORDS:
        if re.search(pattern, clean):
            return CatalogEntry(singular, tags, lifespan_type)

    return CatalogEntry(singular, ("uncategorized",), "durable")


def default_budget_scope(raw_scope: str | None) -> str:
    if not raw_scope:
        return "all"
    scope = raw_scope.lower().strip()
    entry = normalize_item(scope)
    return entry.tags[0] if entry.tags and entry.tags[0] != "uncategorized" else scope


def normalize_item_name(description: str) -> str:
    return normalize_item(description).normalized


def normalize_for_inventory_cap(description: str) -> str:
    cleaned = normalize_item_name(description)
    return cleaned[:-1] if cleaned.endswith("s") and len(cleaned) > 3 else cleaned


def suggest_tags(description: str) -> list[str]:
    return list(normalize_item(description).tags)


def infer_lifespan_type(description: str) -> LifespanType:
    return LifespanType(normalize_item(description).lifespan_type)
