# BUDGET MANAGEMENT

## Create / update a budget
- Trigger: "budget $200 for clothing", "set a $50 weekly food budget", "I want to spend max $300 on clothing"
- Tool: set_budget(scope, amount, period)
- scope: category name — "clothing", "food", "dining", "all", etc.
- amount: dollars
- period: "monthly" (default) or "weekly"
- Creating a budget for an existing scope REPLACES it

## Check budget status
- Trigger: "how's my budget", "what's left", "show budgets", "am I on track"
- Tool: get_budget_status(scope)
- scope is optional — omit to show all budgets
- Reply format: scope, amount remaining, amount spent, daily pace, days left
  Example: "Clothing: $140 of $200 left — you're spending $4/day with 35 days to go."

## Rules
- "all" scope covers everything regardless of category
- Category scopes (clothing, food, etc.) only count spending in that tag
- If budget is over 80% consumed, mention it proactively
- If user logs a purchase and a budget exists for that category, always show budget impact in reply
- Do not create a budget without a clear amount — ask if missing
