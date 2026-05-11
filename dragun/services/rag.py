"""Semantic RAG layer for Dragun operating instructions.

Replaces the keyword-based InstructionRetriever with a full embedding pipeline:

  - Chunks split on ## headers, each chunk embedded via Google text-embedding-004
  - Summaries are embedded at index time (not raw content) to bridge the
    imperative→declarative semantic gap
  - Cosine similarity with a 0.72 hard threshold (silence > noise)
  - 4-factor re-ranking: semantic · intent affinity · recency · position
  - Injected context is labelled with source + relevance score for provenance

The singleton ``get_instruction_retriever()`` is preserved so callers in
intent.py and actions.py need no changes.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

INSTRUCTIONS_DIR = Path(__file__).parent.parent / "instructions"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InstructionChunk:
    chunk_id: str            # deterministic hash of source + header + position
    source_file: str         # e.g. "purchase_logging.md"
    section_header: str      # the ## heading this chunk lives under
    content: str             # the actual rule text
    summary: str             # what gets embedded — bridges imperative→declarative gap
    intent_affinity: list[str] = field(default_factory=list, compare=False, hash=False)
    position: int = 0        # order within file — earlier rules rank higher


@dataclass
class RetrievedChunk:
    chunk: InstructionChunk
    semantic_score: float
    final_score: float


# Back-compat alias kept so any code that references RetrievedInstruction still works
@dataclass(frozen=True)
class RetrievedInstruction:
    name: str
    score: int
    text: str


# ---------------------------------------------------------------------------
# Intent affinity map
# ---------------------------------------------------------------------------

_AFFINITY_MAP: dict[str, list[str]] = {
    "purchase_logging.md":    ["log_purchase"],
    "inventory_management.md":["set_inventory_baseline", "remove_items", "query_inventory",
                               "update_item_cost", "retag_item"],
    "budget_management.md":   ["create_budget", "query_budget", "purchase_advice"],
    "constraints.md":         ["create_constraint"],
    "receipt_ocr.md":         ["log_purchase"],
    "voice_input.md":         ["log_purchase", "purchase_advice", "query_inventory"],
    "conversational.md":      ["casual"],
    "data_correction.md":     ["update_item_cost", "retag_item", "remove_items"],
    "insights.md":            ["purchase_advice", "query_budget"],
}

# Hand-written summaries that bridge imperative rule text → natural query language.
_SUMMARY_MAP: dict[tuple[str, str], str] = {
    ("purchase_logging.md", "When to trigger"):
        "Governs when to record a purchase — buying, getting, ordering, or receiving items",
    ("purchase_logging.md", "Tool: log_purchase(items_text, total_cost)"):
        "Specifies how item names and prices should be formatted before saving to inventory",
    ("purchase_logging.md", "Rules"):
        "Rules for splitting costs, normalising item names, and stripping filler words from purchases",
    ("purchase_logging.md", "Reply format"):
        "How Dragun should reply after logging a purchase including budget impact",
    ("inventory_management.md", "When to trigger"):
        "When to use inventory baseline or removal — setting what you own or removing items",
    ("budget_management.md", "When to trigger"):
        "When to create or query a spending budget and what fields are required",
    ("constraints.md", "When to trigger"):
        "When to set a limit or cap on an item type or spending category",
    ("receipt_ocr.md", "When to trigger"):
        "When the user uploads a receipt image for automatic item extraction",
    ("conversational.md", "When to trigger"):
        "How to respond to casual greetings and small talk that are not purchase requests",
    ("data_correction.md", "When to trigger"):
        "When the user corrects a price, retags an item, or removes something from the hoard",
    ("insights.md", "When to trigger"):
        "When the user asks for spending advice or whether they can afford something",
}


def _make_chunk_id(source: str, header: str, position: int) -> str:
    raw = f"{source}|{header}|{position}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _auto_summary(source_file: str, section_header: str, content: str) -> str:
    key = (source_file, section_header)
    if key in _SUMMARY_MAP:
        return _SUMMARY_MAP[key]
    first_sentence = re.split(r"[.!?\n]", content.strip())[0].strip()
    return f"[{source_file} § {section_header}] {first_sentence}"


def _build_chunks(instructions_dir: Path) -> list[InstructionChunk]:
    """Parse all instruction .md files into InstructionChunk objects."""
    chunks: list[InstructionChunk] = []
    for path in sorted(instructions_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        affinity = _AFFINITY_MAP.get(path.name, [])

        sections = re.split(r"^(##\s+.+)$", text, flags=re.MULTILINE)
        position = 0
        i = 1 if (sections and not sections[0].startswith("##")) else 0

        while i < len(sections) - 1:
            raw_header = sections[i].strip() if sections[i].startswith("##") else ""
            if not raw_header:
                i += 1
                continue
            header = raw_header.lstrip("#").strip()
            body = sections[i + 1].strip() if i + 1 < len(sections) else ""
            i += 2

            if not body or len(body) < 40:
                if chunks and chunks[-1].source_file == path.name:
                    merged = chunks.pop()
                    body = merged.content + "\n" + body
                    header = merged.section_header
                    position = merged.position

            paragraphs = re.split(r"\n{2,}", body)
            current_parts: list[str] = []
            current_len = 0
            sub_position = 0

            def _flush(parts: list[str], hdr: str, pos: int) -> None:
                content_str = "\n\n".join(parts).strip()
                if not content_str:
                    return
                chunk_id = _make_chunk_id(path.name, hdr, pos)
                summary = _auto_summary(path.name, hdr, content_str)
                chunks.append(InstructionChunk(
                    chunk_id=chunk_id,
                    source_file=path.name,
                    section_header=hdr,
                    content=content_str,
                    summary=summary,
                    intent_affinity=list(affinity),
                    position=position + pos,
                ))

            for para in paragraphs:
                para_len = len(para)
                if current_len + para_len > 1600 and current_parts:
                    _flush(current_parts, header, sub_position)
                    sub_position += 1
                    current_parts = [para]
                    current_len = para_len
                else:
                    current_parts.append(para)
                    current_len += para_len

            if current_parts:
                _flush(current_parts, header, sub_position)

            position += 1

    return chunks


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


async def _embed(client, text: str, task_type: str) -> list[float]:
    from google.genai import types
    response = await client.aio.models.embed_content(
        model="text-embedding-004",
        contents=text,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=768,
        ),
    )
    return response.embeddings[0].values


# ---------------------------------------------------------------------------
# Semantic retriever
# ---------------------------------------------------------------------------

class SemanticInstructionRetriever:
    """Embedding-based retriever for Dragun operating instructions.

    ``build_index()`` must be awaited once at startup before the semantic path
    activates. The sync ``context()`` shim falls back to keyword scoring so
    existing callers (intent.py, actions.py) keep working without changes.
    """

    def __init__(self, instructions_dir: Path = INSTRUCTIONS_DIR) -> None:
        self.instructions_dir = instructions_dir
        self._chunks: list[InstructionChunk] = []
        self._embeddings: dict[str, list[float]] = {}  # chunk_id → vector
        self._recency_counter: dict[str, int] = {}     # chunk_id → hit count
        self._indexed = False

    async def build_index(self) -> None:
        """Chunk instruction files and embed summaries. Called once at startup."""
        from dragun.config import get_settings
        settings = get_settings()
        if not settings.google_api_key:
            logger.warning("RAG: no API key — semantic index skipped, keyword fallback active")
            self._chunks = _build_chunks(self.instructions_dir)
            return

        from google import genai
        client = genai.Client(api_key=settings.google_api_key)
        self._chunks = _build_chunks(self.instructions_dir)

        for chunk in self._chunks:
            try:
                vec = await _embed(client, chunk.summary, "RETRIEVAL_DOCUMENT")
                self._embeddings[chunk.chunk_id] = vec
            except Exception as exc:
                logger.warning("RAG: failed to embed chunk %s: %s", chunk.chunk_id, exc)

        self._indexed = True
        logger.info(
            "RAG: index built — %d chunks, %d embedded",
            len(self._chunks), len(self._embeddings),
        )

    def invalidate(self, source_file: str) -> None:
        """Drop cached embeddings for one file (dev hot-reload)."""
        ids_to_drop = {c.chunk_id for c in self._chunks if c.source_file == source_file}
        self._chunks = [c for c in self._chunks if c.source_file != source_file]
        self._embeddings = {k: v for k, v in self._embeddings.items() if k not in ids_to_drop}

    async def retrieve(
        self,
        query: str,
        intent: Optional[str] = None,
        limit: int = 3,
        threshold: float = 0.72,
    ) -> list[RetrievedChunk]:
        """Return up to *limit* re-ranked chunks above *threshold*."""
        if not self._chunks:
            return []
        if self._indexed and self._embeddings:
            return await self._semantic_retrieve(query, intent, limit, threshold)
        return self._keyword_fallback(query, limit)

    async def _semantic_retrieve(
        self,
        query: str,
        intent: Optional[str],
        limit: int,
        threshold: float,
    ) -> list[RetrievedChunk]:
        from dragun.config import get_settings
        settings = get_settings()
        try:
            from google import genai
            client = genai.Client(api_key=settings.google_api_key)
            query_vec = await _embed(client, query, "RETRIEVAL_QUERY")
        except Exception as exc:
            logger.warning("RAG: query embedding failed (%s) — keyword fallback", exc)
            return self._keyword_fallback(query, limit)

        max_position = max((c.position for c in self._chunks), default=1) or 1
        candidates: list[RetrievedChunk] = []

        for chunk in self._chunks:
            if chunk.chunk_id not in self._embeddings:
                continue
            sem = _cosine_similarity(query_vec, self._embeddings[chunk.chunk_id])
            if sem < threshold:
                continue

            affinity_bonus = 0.15 if (intent and intent in chunk.intent_affinity) else 0.0
            hits = self._recency_counter.get(chunk.chunk_id, 0)
            recency = min(hits / 20.0, 1.0) * 0.10
            position_penalty = (chunk.position / max_position) * 0.05

            final = sem * 0.60 + affinity_bonus * 0.25 + recency - position_penalty
            candidates.append(RetrievedChunk(chunk=chunk, semantic_score=sem, final_score=final))

        candidates.sort(key=lambda r: r.final_score, reverse=True)
        selected = candidates[:limit]

        for r in selected:
            self._recency_counter[r.chunk.chunk_id] = (
                self._recency_counter.get(r.chunk.chunk_id, 0) + 1
            )
        return selected

    def _keyword_fallback(self, query: str, limit: int) -> list[RetrievedChunk]:
        terms = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2}
        results: list[RetrievedChunk] = []
        for chunk in self._chunks:
            score = sum(chunk.content.lower().count(t) for t in terms)
            score += sum(5 for t in terms if t in chunk.source_file.lower())
            if score > 0:
                norm = min(score / 20.0, 1.0)
                results.append(RetrievedChunk(chunk=chunk, semantic_score=norm, final_score=norm))
        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[:limit]

    async def retrieve_as_context(
        self,
        query: str,
        intent: Optional[str] = None,
        limit: int = 3,
    ) -> str:
        """Return a structured RAG context block ready for prompt injection."""
        retrieved = await self.retrieve(query, intent=intent, limit=limit)
        if not retrieved:
            return ""
        lines = ["[RAG CONTEXT — verified operating instructions]"]
        for r in retrieved:
            intent_tag = (
                f" | Intent match: {intent}"
                if intent and intent in r.chunk.intent_affinity
                else ""
            )
            lines.append(
                f"Source: {r.chunk.source_file} § {r.chunk.section_header}\n"
                f"Relevance: {r.semantic_score:.2f}{intent_tag}"
            )
            lines.append("---")
            lines.append(r.chunk.content)
        lines.append("[END RAG CONTEXT]")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Sync shim — keeps existing callers working without await
    # ------------------------------------------------------------------

    def context(self, query: str, *, limit: int = 3) -> str:
        """Keyword-based context for sync callers (intent.py, actions.py).

        Async callers should use ``await retrieve_as_context()`` to get the
        full semantic pipeline with provenance labels.
        """
        results = self._keyword_fallback(query, limit)
        if not results:
            return ""
        return "\n\n".join(
            f"# {r.chunk.source_file} § {r.chunk.section_header}\n{r.chunk.content}"
            for r in results
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_instruction_retriever() -> SemanticInstructionRetriever:
    return SemanticInstructionRetriever()


# Back-compat alias
InstructionRetriever = SemanticInstructionRetriever
