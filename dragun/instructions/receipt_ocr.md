# Receipt and image input

Use these instructions only when the input is OCR text, a receipt, a price tag,
or a user asks to log from an image.

- Treat OCR as noisy. Extract candidate line items, quantities, and prices.
- Do not save anything directly from OCR unless the backend or user confirms.
- Return structured item candidates only.
- Ignore obvious receipt metadata unless useful: store name, tax, card number,
  authorization code, cashier id, subtotal labels, and loyalty messages.
- If a line item is ambiguous, preserve the raw text and set a lower confidence.
- Backend code owns persistence, cost allocation, tag validation, and event writes.

