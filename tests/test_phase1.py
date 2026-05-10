from dragun.app import hash_passkey
from dragun.models import (
    BudgetCreateRequest,
    ConstraintCreateRequest,
    ConstraintOperator,
    ConstraintType,
    User,
)
from dragun.services.actions import AdvisorResponseService, BackendActionRouter
from dragun.services.budget import BudgetService
from dragun.services.intent import fallback_extract
from dragun.services.inventory import InventoryService
from dragun.services.parser import parse_text_input
from dragun.storage.memory import InMemoryDragunRepository


def register(store: InMemoryDragunRepository):
    user = User(handle="ember", passkey_hash=hash_passkey("secret-passkey"), zip_code="12345")
    return store.create_user(user)


def test_parser_splits_items_and_allocates_bundle_cost():
    parsed = parse_text_input("3 shirts, 2 dresses, 1 pant - 50 bucks")

    assert len(parsed.items) == 3
    assert [item.item_normalized for item in parsed.items] == ["shirt", "dress", "pant"]
    assert [item.quantity for item in parsed.items] == [3, 2, 1]
    assert sum(item.total_cost or 0 for item in parsed.items) == 50
    assert "clothing" in parsed.items[0].suggested_tags


def test_logging_updates_inventory_and_budget_status():
    store = InMemoryDragunRepository()
    user = register(store)
    inventory = InventoryService(store)
    budget = BudgetService(store, inventory)

    budget.create_budget(
        user.user_id,
        BudgetCreateRequest(
            budget_scope="clothing",
            scope_tags=["clothing"],
            budget_amount=100,
            period_type="monthly",
        ),
    )
    parsed = parse_text_input("3 shirts, 2 dresses - 50 bucks")
    inventory.log_items(user, parsed)
    result = inventory.query_inventory(user.user_id)

    by_item = {row.item_normalized: row for row in result}
    assert by_item["shirt"].current_quantity == 3

    statuses = budget.get_budget_statuses(user.user_id)
    assert statuses[0].amount_spent == 50
    assert statuses[0].amount_remaining == 50


def test_inventory_cap_constraint_triggers_on_purchase():
    store = InMemoryDragunRepository()
    user = register(store)
    inventory = InventoryService(store)
    budget = BudgetService(store, inventory)

    inventory.log_items(user, parse_text_input("I have 14 shirts"))
    budget.create_constraint(
        user.user_id,
        ConstraintCreateRequest(
            constraint_type=ConstraintType.INVENTORY_CAP,
            scope_tags=[],
            operator=ConstraintOperator.COUNT_EXCEEDS,
            threshold_value=15,
            message_template="You have {count} {item}. Max is {threshold}.",
            item_normalized="shirt",
        ),
    )

    parsed = parse_text_input("3 shirts - 30 bucks")
    alerts = budget.check_constraints(user.user_id, parsed.items)

    assert len(alerts) == 1
    assert "17" in alerts[0].message
    assert "15" in alerts[0].message


def test_intent_extraction_detects_purchase_advice():
    intent = fallback_extract("can I get coffee today for $6")

    assert intent.intent == "purchase_advice"
    assert intent.items[0].item_normalized == "coffee"
    assert intent.items[0].estimated_total_cost == 6
    assert "coffee" in intent.items[0].tags


async def test_action_router_advises_without_writing_purchase():
    store = InMemoryDragunRepository()
    user = register(store)
    inventory = InventoryService(store)
    budget = BudgetService(store, inventory)
    router = BackendActionRouter(inventory, budget, AdvisorResponseService())
    budget.create_budget(
        user.user_id,
        BudgetCreateRequest(
            budget_scope="coffee",
            scope_tags=["coffee"],
            budget_amount=10,
            period_type="monthly",
        ),
    )

    result = await router.handle(user, fallback_extract("can I get coffee today for $6"))

    assert result.decision_band in {"yellow", "orange", "red", "green"}
    assert result.events == []
    assert inventory.query_inventory(user.user_id) == []
