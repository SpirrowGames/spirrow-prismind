"""Mock Memory client for testing."""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from spirrow_prismind.integrations.memory_client import (
    CurrentProject,
    Identity,
    MemoryClient,
    MemoryEntry,
    MemoryOperationResult,
    SessionState,
)


class MockMemoryClient(MemoryClient):
    """In-memory mock Memory client for testing.

    Stores data in memory without requiring an actual Memory server.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 10.0,
    ):
        # Don't call super().__init__() to avoid creating httpx client
        self.base_url = base_url
        self.timeout = timeout
        self._available = True  # Mock is always available

        # In-memory storage: key -> MemoryEntry
        self._storage: dict[str, MemoryEntry] = {}

    @property
    def is_available(self) -> bool:
        """Mock is always available."""
        return self._available

    def close(self):
        """No-op for mock client."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    # ===================
    # Basic Operations
    # ===================

    def get(self, key: str) -> Optional[MemoryEntry]:
        """Get a value by key."""
        return self._storage.get(key)

    def set(
        self,
        key: str,
        value: Any,
    ) -> MemoryOperationResult:
        """Set a value."""
        now = datetime.now().isoformat()

        existing = self._storage.get(key)
        created_at = existing.created_at if existing else now

        self._storage[key] = MemoryEntry(
            key=key,
            value=value,
            created_at=created_at,
            updated_at=now,
        )

        return MemoryOperationResult(
            success=True,
            key=key,
            message="Value set successfully",
        )

    def delete(self, key: str) -> MemoryOperationResult:
        """Delete a key."""
        if key in self._storage:
            del self._storage[key]
            return MemoryOperationResult(
                success=True,
                key=key,
                message="Key deleted successfully",
            )

        return MemoryOperationResult(
            success=True,  # Deleting non-existent key is still success
            key=key,
            message="Key deleted successfully",
        )

    def list_keys(self, prefix: Optional[str] = None) -> list[str]:
        """List all keys, optionally filtered by prefix."""
        if prefix:
            return [k for k in self._storage.keys() if k.startswith(prefix)]
        return list(self._storage.keys())

    # =======================
    # Session State Operations
    # =======================

    def _session_key(self, project: str, user: str, author: str = "") -> str:
        """Generate session state key (author = optional last segment)."""
        if author:
            return f"prismind:session:{project}:{user}:{author}"
        return f"prismind:session:{project}:{user}"

    def get_session_state(
        self,
        project: str,
        user: str,
        author: str = "",
    ) -> Optional[SessionState]:
        """Get session state for a project/user/author."""
        key = self._session_key(project, user, author)
        entry = self.get(key)

        if entry is None or entry.value is None:
            return None

        return SessionState.from_dict(entry.value)

    def save_session_state(
        self,
        state: SessionState,
    ) -> MemoryOperationResult:
        """Save session state."""
        state.updated_at = datetime.now().isoformat()
        key = self._session_key(state.project, state.user, state.author)

        return self.set(key, state.to_dict())

    def delete_session_state(
        self,
        project: str,
        user: str,
        author: str = "",
    ) -> MemoryOperationResult:
        """Delete session state."""
        key = self._session_key(project, user, author)
        return self.delete(key)

    # =============================
    # Current Project Operations
    # =============================

    def _current_project_key(self, user: str) -> str:
        """Generate current project key."""
        return f"prismind:current_project:{user}"

    def get_current_project(self, user: str) -> Optional[CurrentProject]:
        """Get the current project for a user."""
        key = self._current_project_key(user)
        entry = self.get(key)

        if entry is None or entry.value is None:
            return None

        return CurrentProject.from_dict(entry.value)

    def set_current_project(
        self,
        user: str,
        project_id: str,
    ) -> MemoryOperationResult:
        """Set the current project for a user."""
        key = self._current_project_key(user)
        value = CurrentProject(
            project_id=project_id,
            switched_at=datetime.now().isoformat(),
        )

        return self.set(key, value.to_dict())

    def clear_current_project(self, user: str) -> MemoryOperationResult:
        """Clear the current project for a user."""
        key = self._current_project_key(user)
        return self.delete(key)

    # =======================
    # Utility Methods
    # =======================

    def get_all_sessions_for_project(
        self,
        project: str,
    ) -> list[SessionState]:
        """Get all session states for a project."""
        prefix = f"prismind:session:{project}:"
        keys = self.list_keys(prefix)

        sessions = []
        for key in keys:
            entry = self.get(key)
            if entry and entry.value:
                sessions.append(SessionState.from_dict(entry.value))

        return sessions

    def get_all_sessions_for_user(
        self,
        user: str,
    ) -> list[SessionState]:
        """Get all session states for a user across projects."""
        all_keys = self.list_keys("prismind:session:")

        sessions = []
        for key in all_keys:
            entry = self.get(key)
            if not (entry and entry.value):
                continue
            state = SessionState.from_dict(entry.value)
            if state.user == user:
                sessions.append(state)

        return sessions

    # =======================
    # Identity Operations
    # =======================

    def _identity_key(self, user: str, identity_name: str) -> str:
        return f"prismind:identity:{user}:{identity_name}"

    def get_identity(self, user: str, identity_name: str) -> Optional[Identity]:
        if not user or not identity_name:
            return None
        entry = self.get(self._identity_key(user, identity_name))
        if entry is None or entry.value is None:
            return None
        return Identity.from_dict(entry.value)

    def save_identity(self, identity: Identity) -> MemoryOperationResult:
        if not identity.user or not identity.identity_name:
            return MemoryOperationResult(
                success=False, key="",
                message="identity.user and identity.identity_name are required",
            )
        now = datetime.now().isoformat()
        if not identity.created_at:
            existing = self.get_identity(identity.user, identity.identity_name)
            identity.created_at = existing.created_at if existing and existing.created_at else now
        identity.updated_at = now
        return self.set(self._identity_key(identity.user, identity.identity_name), identity.to_dict())

    def delete_identity(self, user: str, identity_name: str) -> MemoryOperationResult:
        return self.delete(self._identity_key(user, identity_name))

    def list_identities(self, user: str = "") -> list[Identity]:
        prefix = f"prismind:identity:{user}:" if user else "prismind:identity:"
        out: list[Identity] = []
        for key in self.list_keys(prefix):
            entry = self.get(key)
            if entry and entry.value:
                out.append(Identity.from_dict(entry.value))
        return out

    def list_context_authors(
        self,
        project: str,
        user: str = "",
    ) -> list[dict]:
        """List the distinct context authors saved for a project."""
        states = self.get_all_sessions_for_project(project)
        if user:
            states = [s for s in states if s.user == user]

        by_author: dict[tuple, SessionState] = {}
        for state in states:
            ident = (state.user, state.author)
            existing = by_author.get(ident)
            if existing is None or (state.updated_at or "") > (existing.updated_at or ""):
                by_author[ident] = state

        authors: list[dict] = []
        for s in by_author.values():
            entry: dict = {
                "author": s.author,
                "user": s.user,
                "updated_at": s.updated_at,
                "current_task": s.current_task,
                "current_phase": s.current_phase,
                "identity": None,
            }
            if s.author and s.user:
                ident_record = self.get_identity(s.user, s.author)
                if ident_record is not None:
                    from spirrow_prismind.integrations.memory_client import (
                        _identity_to_response_dict,
                    )
                    entry["identity"] = _identity_to_response_dict(ident_record)
            authors.append(entry)
        authors.sort(key=lambda a: a["updated_at"] or "", reverse=True)
        return authors

    # =======================
    # Test Helpers
    # =======================

    def clear_all(self) -> None:
        """Clear all data (useful for test setup/teardown)."""
        self._storage.clear()

    def get_all_entries(self) -> dict[str, MemoryEntry]:
        """Get all entries (for test inspection)."""
        return dict(self._storage)
