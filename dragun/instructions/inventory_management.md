# INVENTORY MANAGEMENT

## View inventory
- Trigger: "what do I own", "show my hoard", "how many X do I have", "inventory"
- Tool: get_inventory(item_filter)
- item_filter is optional — use it when user asks about a specific item
- Reply: list items with quantities. If empty, say the hoard is empty.

## Set baseline (what user already owns, not a purchase)
- Trigger: "I have 12 shirts", "I own 6 jeans", "I currently have..."
- Tool: set_inventory_baseline(items_text)
- This does NOT log a purchase — it records existing ownership
- Reply: confirm what was recorded, show total hoard

## Remove items
- Trigger: "I donated", "I sold", "I threw away", "I returned", "I lost", "got rid of"
- Tool: remove_items(items_text, reason)
- reason options: "discard", "return", "consumed"
  - donated/threw away/lost → "discard"
  - returned to store → "return"
  - used up (food, consumables) → "consumed"
- Reply: confirm removal, show updated count

## Rules
- Never show negative quantities in replies — if removal would go below 0, note it
- "pairs of X" = same item as "X" — normalize consistently
- Tags shown in UI come from catalog — shorts/sweatpants/swim trunks are clothing
