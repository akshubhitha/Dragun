"""ADK runtime wrapper used by the FastAPI service."""

from __future__ import annotations

import asyncio
from typing import Any
import uuid

from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from dragun.agents.graph import build_dragun_agent
from dragun.agents.toolkit import DragunToolkit
from dragun.config import settings
from dragun.repositories.adk_firestore_session_service import FirestoreSessionService
from dragun.repositories.budgets_repository import BudgetsRepository
from dragun.repositories.events_repository import EventsRepository
from dragun.repositories.firestore_client import get_firestore_client
from dragun.repositories.users_repository import UsersRepository
from dragun.services.engine import DragunEngine


class DragunApp:
    """Owns the data layer, ADK agent, and runtime runner."""

    def __init__(self) -> None:
        self.db = get_firestore_client()
        self.users_repo = UsersRepository(self.db)
        self.events_repo = EventsRepository(self.db)
        self.budgets_repo = BudgetsRepository(self.db)
        self.engine = DragunEngine(
            users_repo=self.users_repo,
            events_repo=self.events_repo,
            budgets_repo=self.budgets_repo,
        )
        self.toolkit = DragunToolkit(self.engine)
        self.root_agent = build_dragun_agent(self.toolkit)

        # ADK doesn't expose FirestoreSessionService in Python yet; we provide one.
        # If Firestore is unavailable at startup, we fall back to in-memory sessions.
        try:
            self.session_service = FirestoreSessionService(self.db)
        except Exception:
            self.session_service = InMemorySessionService()

        self.runner = Runner(
            app_name=settings.app_name,
            agent=self.root_agent,
            session_service=self.session_service,
        )

    async def ensure_session(self, *, user_id: str, session_id: str | None) -> str:
        sid = session_id or str(uuid.uuid4())
        existing = await self.session_service.get_session(
            app_name=settings.app_name,
            user_id=user_id,
            session_id=sid,
        )
        if existing is None:
            await self.session_service.create_session(
                app_name=settings.app_name,
                user_id=user_id,
                session_id=sid,
                state={"user_id": user_id},
            )
        elif not existing.state.get("user_id"):
            existing.state["user_id"] = user_id
            # Session state persistence is handled via subsequent events.
        return sid

    async def run_chat(self, *, user_id: str, session_id: str, message: str) -> str:
        content = types.Content(role="user", parts=[types.Part(text=message)])
        final_text = ""
        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            if isinstance(event, Event) and event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if getattr(part, "text", None):
                            final_text += part.text
        return final_text.strip()


_app_singleton: DragunApp | None = None


def get_dragun_app() -> DragunApp:
    global _app_singleton  # noqa: PLW0603
    if _app_singleton is None:
        _app_singleton = DragunApp()
    return _app_singleton
