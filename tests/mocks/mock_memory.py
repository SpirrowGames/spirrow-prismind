"""Mock Memory client for testing."""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from spirrow_prismind.integrations.memory_client import (
    CurrentProject,
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

    def _session_key(self, project: str, user: str) -> str:
        """Generate session state key."""
        return f"prismind:session:{project}:{user}"

    def get_session_state(
        self,
        project: str,
        user: str,
    ) -> Optional[SessionState]:
        """Get session state for a project/user."""
        key = self._session_key(project, user)
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
        key = self._session_key(state.project, state.user)

        return self.set(key, state.to_dict())

    def delete_session_state(
        self,
        project: str,
        user: str,
    ) -> MemoryOperationResult:
        """Delete session state."""
        key = self._session_key(project, user)
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
        suffix = f":{user}"

        for key in all_keys:
            if key.endswith(suffix):
                entry = self.get(key)
                if entry and entry.value:
                    sessions.append(SessionState.from_dict(entry.value))

        return sessions

    # =======================
    # Test Helpers
    # =======================

    def clear_all(self) -> None:
        """Clear all data (useful for test setup/teardown)."""
        self._storage.clear()

    def get_all_entries(self) -> dict[str, MemoryEntry]:
        """Get all entries (for test inspection)."""
        return dict(self._storage)
