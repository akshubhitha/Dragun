from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Iterable

from dragun.models import Budget, Constraint, Event, Tag, User, UserProfile


class DragunRepository(ABC):
    """Storage boundary for Dragun's event-sourced data model."""

    @abstractmethod
    def create_user(self, user: User) -> User:
        raise NotImplementedError

    @abstractmethod
    def get_user_by_handle(self, handle: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def get_user_by_email(self, email: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def get_user(self, user_id: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def create_event(self, event: Event, tag_names: Iterable[str]) -> Event:
        raise NotImplementedError

    @abstractmethod
    def list_events(
        self,
        user_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Event]:
        raise NotImplementedError

    @abstractmethod
    def upsert_tag(self, tag_name: str, tag_origin: str = "agent_inferred") -> Tag:
        raise NotImplementedError

    @abstractmethod
    def list_tags(self) -> list[Tag]:
        raise NotImplementedError

    @abstractmethod
    def list_event_tags(self, event_ids: Iterable[str]) -> dict[str, list[str]]:
        raise NotImplementedError

    @abstractmethod
    def update_item_tags(self, user_id: str, item_normalized: str, new_tags: list[str]) -> int:
        """Replace tags on all events for this user+item. Returns number of events updated."""
        raise NotImplementedError

    @abstractmethod
    def create_budget(self, budget: Budget) -> Budget:
        raise NotImplementedError

    @abstractmethod
    def list_active_budgets(self, user_id: str) -> list[Budget]:
        raise NotImplementedError

    @abstractmethod
    def create_constraint(self, constraint: Constraint) -> Constraint:
        raise NotImplementedError

    @abstractmethod
    def list_active_constraints(self, user_id: str) -> list[Constraint]:
        raise NotImplementedError

    @abstractmethod
    def update_user_handle(self, user_id: str, new_handle: str) -> User:
        raise NotImplementedError

    @abstractmethod
    def update_user_profile(self, user_id: str, **fields) -> User:
        """Update arbitrary scalar fields on a user record."""
        raise NotImplementedError

    @abstractmethod
    def anonymize_user(self, user_id: str) -> None:
        """Strip PII from the user record but keep all spending data as synthetic."""
        raise NotImplementedError

    @abstractmethod
    def get_user_profile(self, user_id: str) -> UserProfile | None:
        """Return the UserProfile for a user, or None if not yet created."""
        raise NotImplementedError

    @abstractmethod
    def upsert_user_profile(self, profile: UserProfile) -> UserProfile:
        """Create or fully replace the UserProfile for a user."""
        raise NotImplementedError

    @abstractmethod
    def delete_user_data(self, user_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def export_user_data(self, user_id: str) -> dict:
        raise NotImplementedError
