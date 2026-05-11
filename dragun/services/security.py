"""Prompt injection defenses and output validation for Dragun.

All untrusted string input passes through sanitize_input() before any LLM call.
Receipt OCR descriptions get an additional pass via sanitize_receipt_item().
Advisor output is checked via validate_advisor_output() before reaching the user.
Every flagged event is logged as a structured JSON entry.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Injection pattern library
# ---------------------------------------------------------------------------

INJECTION_PATTERNS: list[str] = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"forget\s+(everything|all|what)",
    r"you\s+are\s+now\s+a?\s+\w+",
    r"new\s+system\s+prompt",
    r"act\s+as\s+(if\s+)?(you\s+are\s+)?",
    r"do\s+not\s+follow",
    r"override\s+(your\s+)?(instructions?|rules?|guidelines?)",
    r"disregard\s+(your\s+)?",
    r"pretend\s+(you\s+are|to\s+be)",
    r"(system|assistant|user)\s*:\s*",       # role injection attempt
    r"<\s*(system|instruction|prompt)\s*>",  # XML injection
    r"\[INST\]|\[\/INST\]",                  # Llama-style injection
    r"###\s*(instruction|system|human)",     # common jailbreak markers
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

# ---------------------------------------------------------------------------
# Output anomaly patterns
# ---------------------------------------------------------------------------

OUTPUT_ANOMALY_PATTERNS: list[str] = [
    r"(system|assistant)\s*:",
    r"ignore\s+(my\s+)?instructions",
    r"<\s*(system|prompt)\s*>",
    r"as\s+an?\s+AI\s+(language\s+)?model",
]

_OUTPUT_COMPILED = [re.compile(p, re.IGNORECASE) for p in OUTPUT_ANOMALY_PATTERNS]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_security_event(
    event: str,
    user_id: str | None,
    source: str,
    pattern: str,
    input_preview: str,
) -> None:
    entry = {
        "event": event,
        "user_id": user_id or "anonymous",
        "source": source,
        "pattern_matched": pattern,
        "input_preview": input_preview[:100],
        "timestamp": _utc_now(),
    }
    logger.warning("SECURITY %s", json.dumps(entry))


# ---------------------------------------------------------------------------
# Input sanitization
# ---------------------------------------------------------------------------

def sanitize_input(
    text: str,
    source: str = "user",
    user_id: str | None = None,
) -> tuple[str, bool]:
    """Scan *text* for injection patterns and strip matches.

    Returns ``(sanitized_text, was_flagged)``.

    Flagged inputs are logged and the matched segment is replaced with
    ``[removed]``. The message is still processed — we prefer graceful
    degradation over silent drops for chat input.
    """
    flagged = False
    for compiled, raw_pattern in zip(_COMPILED, INJECTION_PATTERNS):
        if compiled.search(text):
            flagged = True
            _log_security_event(
                event="injection_attempt",
                user_id=user_id,
                source=source,
                pattern=raw_pattern,
                input_preview=text,
            )
            text = compiled.sub("[removed]", text)
    return text, flagged


# ---------------------------------------------------------------------------
# Receipt-specific sanitization
# ---------------------------------------------------------------------------

_MAX_ITEM_DESC_LEN = 80


def sanitize_receipt_item(
    description: str,
    user_id: str | None = None,
) -> str:
    """Strip injection attempts from OCR'd receipt item descriptions.

    Real item names are almost never longer than 60 characters; anything
    longer is suspicious. The description is then passed through the
    standard sanitizer.
    """
    if len(description) > _MAX_ITEM_DESC_LEN:
        description = description[:_MAX_ITEM_DESC_LEN] + "…"

    sanitized, _ = sanitize_input(description, source="receipt_ocr", user_id=user_id)
    return sanitized


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

_SAFE_FALLBACK = "The hoard is updated. Ask me what you own or what you've spent."


def validate_advisor_output(
    reply: str,
    user_id: str | None = None,
) -> str:
    """Check the advisor reply for signs of injection success or persona break.

    Returns the reply unchanged if clean, or a safe fallback if an anomaly
    is detected. Every anomaly is logged.
    """
    for compiled, raw_pattern in zip(_OUTPUT_COMPILED, OUTPUT_ANOMALY_PATTERNS):
        if compiled.search(reply):
            _log_security_event(
                event="output_anomaly",
                user_id=user_id,
                source="advisor_output",
                pattern=raw_pattern,
                input_preview=reply,
            )
            return _SAFE_FALLBACK
    return reply
