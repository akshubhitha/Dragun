"""Minimal Firestore-backed ADK session service for persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
import uuid

from google.adk.events.event import Event
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.sessions.base_session_service import ListSessionsResponse
from google.adk.sessions.session import Session
from google.cloud import firestore
from pydantic import TypeAdapter


_EVENT_ADAPTER = TypeAdapter(Event)


def _serialize_event(event: Event) -> dict[str, Any]:
    return event.model_dump(mode="json")


def _deserialize_event(payload: dict[str, Any]) -> Event:
    return _EVENT_ADAPTER.validate_python(payload)


class FirestoreSessionService(BaseSessionService):
    """Persist ADK sessions/events in Firestore."""

    def __init__(self, db: firestore.Client, root_collection: str = "adk_sessions") -> None:
        self._db = db
        self._root = root_collection

    def _session_doc(self, app_name: str, user_id: str, session_id: str):
        return (
            self._db.collection(self._root)
            .document(app_name)
            .collection("users")
            .document(user_id)
            .collection("sessions")
            .document(session_id)
        )

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        sid = session_id.strip() if session_id and session_id.strip() else str(uuid.uuid4())
        now = datetime.utcnow().timestamp()
        session = Session(
            app_name=app_name,
            user_id=user_id,
            id=sid,
            state=state or {},
            events=[],
            last_update_time=now,
        )
        self._session_doc(app_name, user_id, sid).set(
            {
                "app_name": app_name,
                "user_id": user_id,
                "session_id": sid,
                "state": state or {},
                "events": [],
                "last_update_time": now,
            }
        )
        return session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        snap = self._session_doc(app_name, user_id, session_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        events_payload = data.get("events") or []
        if config:
            if config.after_timestamp:
                events_payload = [
                    event
                    for event in events_payload
                    if float(event.get("timestamp", 0)) >= config.after_timestamp
                ]
            if config.num_recent_events is not None:
                if config.num_recent_events <= 0:
                    events_payload = []
                else:
                    events_payload = events_payload[-config.num_recent_events :]
        events = [_deserialize_event(event) for event in events_payload]
        return Session(
            app_name=app_name,
            user_id=user_id,
            id=session_id,
            state=data.get("state") or {},
            events=events,
            last_update_time=float(data.get("last_update_time", datetime.utcnow().timestamp())),
        )

    async def list_sessions(
        self, *, app_name: str, user_id: Optional[str] = None
    ) -> ListSessionsResponse:
        sessions: list[Session] = []
        if user_id is not None:
            docs = (
                self._db.collection(self._root)
                .document(app_name)
                .collection("users")
                .document(user_id)
                .collection("sessions")
                .stream()
            )
            for doc in docs:
                payload = doc.to_dict() or {}
                sessions.append(
                    Session(
                        app_name=app_name,
                        user_id=user_id,
                        id=payload.get("session_id", doc.id),
                        state=payload.get("state") or {},
                        events=[],
                        last_update_time=float(
                            payload.get("last_update_time", datetime.utcnow().timestamp())
                        ),
                    )
                )
            return ListSessionsResponse(sessions=sessions)

        user_docs = (
            self._db.collection(self._root).document(app_name).collection("users").stream()
        )
        for user_doc in user_docs:
            uid = user_doc.id
            session_docs = (
                self._db.collection(self._root)
                .document(app_name)
                .collection("users")
                .document(uid)
                .collection("sessions")
                .stream()
            )
            for doc in session_docs:
                payload = doc.to_dict() or {}
                sessions.append(
                    Session(
                        app_name=app_name,
                        user_id=uid,
                        id=payload.get("session_id", doc.id),
                        state=payload.get("state") or {},
                        events=[],
                        last_update_time=float(
                            payload.get("last_update_time", datetime.utcnow().timestamp())
                        ),
                    )
                )
        return ListSessionsResponse(sessions=sessions)

    async def delete_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
        self._session_doc(app_name, user_id, session_id).delete()

    async def append_event(self, session: Session, event: Event) -> Event:
        await super().append_event(session=session, event=event)
        session.last_update_time = event.timestamp

        session_doc = self._session_doc(session.app_name, session.user_id, session.id)
        session_doc.set(
            {
                "app_name": session.app_name,
                "user_id": session.user_id,
                "session_id": session.id,
                "state": session.state,
                "last_update_time": session.last_update_time,
                "events": [_serialize_event(existing) for existing in session.events],
            }
        )
        return event
