from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date
from threading import RLock
from typing import Iterable

from dragun.models import (
    Budget,
    Constraint,
    Event,
    EventTag,
    Goal,
    Tag,
    User,
    UserProfile,
)
from dragun.storage.base import DragunRepository


class InMemoryRepository(DragunRepository):
    """Local repository for tests and no-credential demos."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.users: dict[str, User] = {}
        self.users_by_handle: dict[str, str] = {}
        self.users_by_email: dict[str, str] = {}
        self.events: dict[str, Event] = {}
        self.tags: dict[str, Tag] = {}
        self.tags_by_name: dict[str, str] = {}
        self.event_tags: dict[str, list[dict]] = defaultdict(list)
        self.budgets: dict[str, Budget] = {}
        self.constraints: dict[str, Constraint] = {}
        self.user_profiles: dict[str, UserProfile] = {}
        self.goals: dict[str, Goal] = {}

    def create_user(self, user: User) -> User:
        normalized = user.handle.strip().lower()
        with self._lock:
            if normalized in self.users_by_handle:
                raise ValueError("That handle is already guarding a hoard.")
            self.users[user.user_id] = deepcopy(user)
            self.users_by_handle[normalized] = user.user_id
            if user.email:
                self.users_by_email[user.email.strip().lower()] = user.user_id
            return deepcopy(user)

    def get_user_by_handle(self, handle: str) -> User | None:
        with self._lock:
            user_id = self.users_by_handle.get(handle.strip().lower())
            return deepcopy(self.users.get(user_id)) if user_id else None

    def get_user_by_email(self, email: str) -> User | None:
        with self._lock:
            user_id = self.users_by_email.get(email.strip().lower())
            return deepcopy(self.users.get(user_id)) if user_id else None

    def get_user(self, user_id: str) -> User | None:
        with self._lock:
            user = self.users.get(user_id)
            return deepcopy(user) if user else None

    def create_event(self, event: Event, tag_names: Iterable[str] = ()) -> Event:
        with self._lock:
            self.events[event.event_id] = deepcopy(event)
            for tag_name in tag_names:
                tag = self.upsert_tag(tag_name, "agent_inferred")
                self.event_tags[event.event_id].append(
                    EventTag(event_id=event.event_id, tag_id=tag.tag_id).model_dump()
                )
            return deepcopy(event)

    def list_events(
        self,
        user_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Event]:
        with self._lock:
            events = [event for event in self.events.values() if event.user_id == user_id]
            if start:
                events = [event for event in events if event.event_timestamp.date() >= start]
            if end:
                events = [event for event in events if event.event_timestamp.date() <= end]
            return deepcopy(sorted(events, key=lambda event: event.event_timestamp))

    def list_event_tags(self, event_ids: Iterable[str]) -> dict[str, list[str]]:
        with self._lock:
            event_id_set = set(event_ids)
            output: dict[str, list[str]] = {}
            for event_id in event_id_set:
                names: list[str] = []
                for link in self.event_tags.get(event_id, []):
                    tag = self.tags.get(link["tag_id"])
                    if tag:
                        names.append(tag.tag_name)
                output[event_id] = names
            return output

    def upsert_tag(self, tag_name: str, tag_origin: str = "agent_inferred") -> Tag:
        normalized = tag_name.strip().lower()
        with self._lock:
            existing_id = self.tags_by_name.get(normalized)
            if existing_id:
                return deepcopy(self.tags[existing_id])
            tag = Tag(tag_name=normalized, tag_origin=tag_origin)
            self.tags[tag.tag_id] = deepcopy(tag)
            self.tags_by_name[normalized] = tag.tag_id
            return deepcopy(tag)

    def list_tags(self) -> list[Tag]:
        with self._lock:
            return deepcopy(list(self.tags.values()))

    def update_item_tags(self, user_id: str, item_normalized: str, new_tags: list[str]) -> int:
        """Replace tags on all events for this user+item."""
        with self._lock:
            matching = [e for e in self.events.values() if e.user_id == user_id and e.item_normalized == item_normalized]
            if not matching:
                return 0
            new_tag_objects = [self.upsert_tag(t) for t in new_tags if t]
            for event in matching:
                self.event_tags[event.event_id] = [
                    EventTag(event_id=event.event_id, tag_id=tag.tag_id).model_dump()
                    for tag in new_tag_objects
                ]
            return len(matching)

    def create_budget(self, budget: Budget) -> Budget:
        with self._lock:
            self.budgets[budget.budget_id] = deepcopy(budget)
            return deepcopy(budget)

    def list_active_budgets(self, user_id: str) -> list[Budget]:
        with self._lock:
            budgets = [
                budget
                for budget in self.budgets.values()
                if budget.user_id == user_id and budget.is_active
            ]
            return deepcopy(sorted(budgets, key=lambda budget: budget.created_at))

    def update_budget(self, user_id: str, budget_id: str, **kwargs) -> Budget:
        allowed = {"budget_amount", "period_type", "rollover_enabled"}
        with self._lock:
            budget = self.budgets.get(budget_id)
            if not budget or budget.user_id != user_id:
                raise ValueError("Budget not found.")
            for key, value in kwargs.items():
                if key in allowed and value is not None:
                    setattr(budget, key, value)
            return deepcopy(budget)

    def delete_budget(self, user_id: str, budget_id: str) -> None:
        with self._lock:
            budget = self.budgets.get(budget_id)
            if budget and budget.user_id == user_id:
                budget.is_active = False

    def create_constraint(self, constraint: Constraint) -> Constraint:
        with self._lock:
            self.constraints[constraint.constraint_id] = deepcopy(constraint)
            return deepcopy(constraint)

    def list_active_constraints(self, user_id: str) -> list[Constraint]:
        with self._lock:
            constraints = [
                constraint
                for constraint in self.constraints.values()
                if constraint.user_id == user_id and constraint.is_active
            ]
            return deepcopy(sorted(constraints, key=lambda constraint: constraint.created_at))

    def get_constraints(self, user_id: str) -> list[Constraint]:
        return self.list_active_constraints(user_id)

    def delete_constraint(self, user_id: str, constraint_id: str) -> None:
        with self._lock:
            constraint = self.constraints.get(constraint_id)
            if constraint and constraint.user_id == user_id:
                constraint.is_active = False

    def update_constraint(self, user_id: str, constraint_id: str, **kwargs) -> Constraint:
        allowed = {"is_active", "threshold_value"}
        with self._lock:
            constraint = self.constraints.get(constraint_id)
            if not constraint or constraint.user_id != user_id:
                raise ValueError("Constraint not found.")
            for key, value in kwargs.items():
                if key in allowed and value is not None:
                    setattr(constraint, key, value)
            return deepcopy(constraint)

    def create_goal(self, goal: Goal) -> Goal:
        with self._lock:
            self.goals[goal.goal_id] = deepcopy(goal)
            return deepcopy(goal)

    def get_goals(self, user_id: str) -> list[Goal]:
        with self._lock:
            goals = [g for g in self.goals.values() if g.user_id == user_id]
            return deepcopy(sorted(goals, key=lambda g: g.created_at))

    def get_goal(self, user_id: str, goal_id: str) -> Goal | None:
        with self._lock:
            goal = self.goals.get(goal_id)
            if goal and goal.user_id == user_id:
                return deepcopy(goal)
            return None

    def update_goal(self, user_id: str, goal_id: str, **kwargs) -> Goal:
        allowed = {"name", "target_amount", "current_amount", "deadline", "category", "status", "updated_at"}
        with self._lock:
            goal = self.goals.get(goal_id)
            if not goal or goal.user_id != user_id:
                raise ValueError("Goal not found.")
            for key, value in kwargs.items():
                if key in allowed:
                    setattr(goal, key, value)
            return deepcopy(goal)

    def delete_goal(self, user_id: str, goal_id: str) -> None:
        with self._lock:
            goal = self.goals.get(goal_id)
            if goal and goal.user_id == user_id:
                del self.goals[goal_id]

    def export_user_data(self, user_id: str) -> dict:
        with self._lock:
            user = self.users[user_id]
            events = [event for event in self.events.values() if event.user_id == user_id]
            budgets = [budget for budget in self.budgets.values() if budget.user_id == user_id]
            constraints = [
                constraint
                for constraint in self.constraints.values()
                if constraint.user_id == user_id
            ]
            event_ids = {event.event_id for event in events}
            event_tags = {
                event_id: deepcopy(tags)
                for event_id, tags in self.event_tags.items()
                if event_id in event_ids
            }
            return {
                "user": user.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in events],
                "event_tags": event_tags,
                "budgets": [budget.model_dump(mode="json") for budget in budgets],
                "constraints": [
                    constraint.model_dump(mode="json") for constraint in constraints
                ],
                "tags": [tag.model_dump(mode="json") for tag in self.tags.values()],
            }

    def update_user_profile(self, user_id: str, **fields) -> User:
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                raise ValueError("User not found.")
            for key, value in fields.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            return deepcopy(user)

    def update_user_handle(self, user_id: str, new_handle: str) -> User:
        normalized = new_handle.strip().lower()
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                raise ValueError("User not found.")
            if normalized in self.users_by_handle and self.users_by_handle[normalized] != user_id:
                raise ValueError("That username is already taken.")
            # Remove old handle mapping
            self.users_by_handle.pop(user.handle, None)
            user.handle = normalized
            self.users_by_handle[normalized] = user_id
            return deepcopy(user)

    def anonymize_user(self, user_id: str) -> None:
        """Remove PII; keep events/budgets under a synthetic handle."""
        import secrets
        with self._lock:
            user = self.users.get(user_id)
            if not user:
                return
            # Remove identity lookups
            self.users_by_handle.pop(user.handle, None)
            if user.email:
                self.users_by_email.pop(user.email.strip().lower(), None)
            # Overwrite PII fields in place
            synth = f"synth_{secrets.token_hex(6)}"
            user.handle = synth
            user.email = None
            user.monthly_income = 0.0
            user.fixed_costs_floor = 0.0
            # Strip user profile too
            self.user_profiles.pop(user_id, None)
            # Don't re-add to lookup indexes — account is gone, data stays

    def get_user_profile(self, user_id: str) -> UserProfile | None:
        with self._lock:
            profile = self.user_profiles.get(user_id)
            return deepcopy(profile) if profile else None

    def upsert_user_profile(self, profile: UserProfile) -> UserProfile:
        with self._lock:
            self.user_profiles[profile.user_id] = deepcopy(profile)
            return deepcopy(profile)

    def delete_user_data(self, user_id: str) -> None:
        with self._lock:
            user = self.users.pop(user_id, None)
            if user:
                self.users_by_handle.pop(user.handle, None)
                if user.email:
                    self.users_by_email.pop(user.email.strip().lower(), None)
            self.user_profiles.pop(user_id, None)
            event_ids = [
                event_id for event_id, event in self.events.items() if event.user_id == user_id
            ]
            for event_id in event_ids:
                self.events.pop(event_id, None)
                self.event_tags.pop(event_id, None)
            for budget_id, budget in list(self.budgets.items()):
                if budget.user_id == user_id:
                    self.budgets.pop(budget_id, None)
            for constraint_id, constraint in list(self.constraints.items()):
                if constraint.user_id == user_id:
                    self.constraints.pop(constraint_id, None)

    def reset(self) -> None:
        with self._lock:
            self.__init__()


InMemoryDragunRepository = InMemoryRepository
