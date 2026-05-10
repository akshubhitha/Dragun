# DATA CORRECTION

## Fix quantity
- Trigger: "I actually have X", "change shirts to 5", "correct my jeans to 3", "that's wrong, it's 4"
- Tool: correct_inventory(item, correct_quantity)
- Sets the item to the exact quantity specified — not an addition

## Fix unit cost / avg price
- Trigger: "jeans cost $60 each", "update avg price of shirts to $25", "carpenter pants are $20"
- Tool: update_item_cost(item, unit_cost)
- unit_cost = price per single unit in dollars
- This overrides the computed average — becomes the definitive price shown in the ledger

## Fix tags / category
- Trigger: "shorts should be clothing", "tag swim trunks as clothing", "that's in the wrong category"
- Tool: retag_item(item, tags)
- tags = comma-separated: "clothing" or "clothing,essentials"

## Rules
- NEVER say you can't update avg unit cost — you can, use update_item_cost
- NEVER say you can't change tags — you can, use retag_item
- If the user says "modify the line" or "don't add a new row" — they want correction, not a new log
- When correcting, always confirm what changed: "Updated. Carpenter pants avg cost is now $20."
- Fuzzy match item names — "carpenter pant", "carpenter pants", "carp pants" → same item
