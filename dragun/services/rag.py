from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


INSTRUCTIONS_DIR = Path(__file__).parent.parent / "instructions"


@dataclass(frozen=True)
class RetrievedInstruction:
    name: str
    score: int
    text: str


class InstructionRetriever:
    """Tiny local RAG layer for agent operating instructions.

    This intentionally avoids a vector database for now. The goal is to keep
    prompts small by retrieving only the instruction snippets relevant to the
    user's current message.
    """

    def __init__(self, instructions_dir: Path = INSTRUCTIONS_DIR) -> None:
        self.instructions_dir = instructions_dir

    def retrieve(self, query: str, *, limit: int = 3) -> list[RetrievedInstruction]:
        terms = _tokenize(query)
        if not terms:
            return []

        matches: list[RetrievedInstruction] = []
        for path in sorted(self.instructions_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            score = _score(text, terms) + _filename_score(path.name, terms)
            if score > 0:
                matches.append(
                    RetrievedInstruction(
                        name=path.name,
                        score=score,
                        text=_truncate(text),
                    )
                )
        return sorted(matches, key=lambda item: item.score, reverse=True)[:limit]

    def context(self, query: str, *, limit: int = 3) -> str:
        snippets = self.retrieve(query, limit=limit)
        if not snippets:
            return ""
        return "\n\n".join(f"# {item.name}\n{item.text}" for item in snippets)


@lru_cache(maxsize=1)
def get_instruction_retriever() -> InstructionRetriever:
    return InstructionRetriever()


def _tokenize(text: str) -> set[str]:
    words = {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 2}
    expanded = set(words)
    for word in words:
        if word in {"buy", "bought", "purchase", "purchased", "spend", "spent"}:
            expanded.update({"purchase", "buy", "spend"})
        if word in {"receipt", "image", "photo", "picture", "ocr"}:
            expanded.update({"receipt", "image", "ocr"})
        if word in {"voice", "audio", "speak", "talk", "transcript"}:
            expanded.update({"voice", "transcript"})
        if word in {"budget", "afford", "coffee", "today", "should"}:
            expanded.update({"budget", "advice", "constraint"})
    return expanded


def _score(text: str, terms: set[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(term) for term in terms)


def _filename_score(name: str, terms: set[str]) -> int:
    lowered = name.lower()
    return sum(5 for term in terms if term in lowered)


def _truncate(text: str, limit: int = 1200) -> str:
    compact = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rsplit("\n", 1)[0] + "\n..."
