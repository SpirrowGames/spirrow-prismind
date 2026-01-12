"""MCP Memory Server client for session state management."""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """An entry in the memory server."""
    key: str
    value: Any
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MemoryOperationResult:
    """Result of a memory operation."""
    success: bool
    key: str = ""
    message: str = ""


@dataclass
class SessionState:
    """Session state stored in memory."""
    project: str
    user: str
    current_phase: str = ""
    current_task: str = ""
    last_completed: str = ""
    blockers: list[str] = field(default_factory=list)
    notes: str = ""
    last_summary: str = ""
    next_action: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        """Create from dictionary."""
        return cls(
            project=data.get("project", ""),
            user=data.get("user", ""),
            current_phase=data.get("current_phase", ""),
            current_task=data.get("current_task", ""),
            last_completed=data.get("last_completed", ""),
            blockers=data.get("blockers", []),
            notes=data.get("notes", ""),
            last_summary=data.get("last_summary", ""),
            next_action=data.get("next_action", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class CurrentProject:
    """Current project information stored in memory."""
    project_id: str
    switched_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CurrentProject":
        """Create from dictionary."""
        return cls(
            project_id=data.get("project_id", ""),
            switched_at=data.get("switched_at", ""),
        )


class MemoryClient:
    """Client for MCP Memory Server operations.

    Assumes a simple key-value REST API.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 10.0,
        connect_timeout: float = 3.0,
    ):
        """Initialize the memory client.

        Args:
            base_url: Memory server URL
            timeout: Request timeout in seconds
            connect_timeout: Connection check timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        self._available = self._check_connection(connect_timeout)

    def _check_connection(self, timeout: float) -> bool:
        """Check if the Memory server is available.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if server is available, False otherwise
        """
        try:
            response = httpx.get(
                f"{self.base_url}/health",
                timeout=timeout,
            )
            logger.info(f"Memory server connected: {self.base_url}")
            return True
        except Exception as e:
            logger.warning(f"Memory server not available at {self.base_url}: {e}")
            return False

    @property
    def is_available(self) -> bool:
        """Check if the Memory server is available."""
        return self._available

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        """Make an HTTP request to the memory server.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint
            json_data: JSON body data
            params: Query parameters
            
        Returns:
            Response JSON or None
            
        Raises:
            httpx.HTTPError: If the request fails
        """
        url = f"{self.base_url}{endpoint}"
        
        response = self._client.request(
            method=method,
            url=url,
            json=json_data,
            params=params,
        )
        
        if response.status_code == 404:
            return None
        
        response.raise_for_status()
        
        if response.content:
            return response.json()
        return {}

    # ===================
    # Basic Operations
    # ===================

    def get(self, key: str) -> Optional[MemoryEntry]:
        """Get a value by key.
        
        Args:
            key: Memory key
            
        Returns:
            MemoryEntry if found, None otherwise
        """
        try:
            result = self._make_request("GET", f"/memory/{key}")
            
            if result is None:
                return None
            
            return MemoryEntry(
                key=key,
                value=result.get("value"),
                created_at=result.get("created_at", ""),
                updated_at=result.get("updated_at", ""),
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to get memory key '{key}': {e}")
            return None

    def set(
        self,
        key: str,
        value: Any,
    ) -> MemoryOperationResult:
        """Set a value.
        
        Args:
            key: Memory key
            value: Value to store
            
        Returns:
            MemoryOperationResult
        """
        try:
            self._make_request(
                "POST",
                f"/memory/{key}",
                json_data={"value": value},
            )
            
            return MemoryOperationResult(
                success=True,
                key=key,
                message="Value set successfully",
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to set memory key '{key}': {e}")
            return MemoryOperationResult(
                success=False,
                key=key,
                message=str(e),
            )

    def delete(self, key: str) -> MemoryOperationResult:
        """Delete a key.
        
        Args:
            key: Memory key
            
        Returns:
            MemoryOperationResult
        """
        try:
            self._make_request("DELETE", f"/memory/{key}")
            
            return MemoryOperationResult(
                success=True,
                key=key,
                message="Key deleted successfully",
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to delete memory key '{key}': {e}")
            return MemoryOperationResult(
                success=False,
                key=key,
                message=str(e),
            )

    def list_keys(self, prefix: Optional[str] = None) -> list[str]:
        """List all keys, optionally filtered by prefix.
        
        Args:
            prefix: Key prefix to filter by
            
        Returns:
            List of keys
        """
        try:
            params = {}
            if prefix:
                params["prefix"] = prefix
            
            result = self._make_request("GET", "/memory", params=params)
            
            if result is None:
                return []
            
            return result.get("keys", [])
        except httpx.HTTPError as e:
            logger.error(f"Failed to list memory keys: {e}")
            return []

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
        """Get session state for a project/user.
        
        Args:
            project: Project ID
            user: User ID
            
        Returns:
            SessionState if found, None otherwise
        """
        key = self._session_key(project, user)
        entry = self.get(key)
        
        if entry is None or entry.value is None:
            return None
        
        return SessionState.from_dict(entry.value)

    def save_session_state(
        self,
        state: SessionState,
    ) -> MemoryOperationResult:
        """Save session state.
        
        Args:
            state: Session state to save
            
        Returns:
            MemoryOperationResult
        """
        state.updated_at = datetime.now().isoformat()
        key = self._session_key(state.project, state.user)
        
        return self.set(key, state.to_dict())

    def delete_session_state(
        self,
        project: str,
        user: str,
    ) -> MemoryOperationResult:
        """Delete session state.
        
        Args:
            project: Project ID
            user: User ID
            
        Returns:
            MemoryOperationResult
        """
        key = self._session_key(project, user)
        return self.delete(key)

    # =============================
    # Current Project Operations
    # =============================

    def _current_project_key(self, user: str) -> str:
        """Generate current project key."""
        return f"prismind:current_project:{user}"

    def get_current_project(self, user: str) -> Optional[CurrentProject]:
        """Get the current project for a user.
        
        Args:
            user: User ID
            
        Returns:
            CurrentProject if set, None otherwise
        """
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
        """Set the current project for a user.
        
        Args:
            user: User ID
            project_id: Project ID to set as current
            
        Returns:
            MemoryOperationResult
        """
        key = self._current_project_key(user)
        value = CurrentProject(
            project_id=project_id,
            switched_at=datetime.now().isoformat(),
        )
        
        return self.set(key, value.to_dict())

    def clear_current_project(self, user: str) -> MemoryOperationResult:
        """Clear the current project for a user.
        
        Args:
            user: User ID
            
        Returns:
            MemoryOperationResult
        """
        key = self._current_project_key(user)
        return self.delete(key)

    # =======================
    # Utility Methods
    # =======================

    def get_all_sessions_for_project(
        self,
        project: str,
    ) -> list[SessionState]:
        """Get all session states for a project.
        
        Args:
            project: Project ID
            
        Returns:
            List of SessionState
        """
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
        """Get all session states for a user across projects.
        
        Args:
            user: User ID
            
        Returns:
            List of SessionState
        """
        # We need to search through all sessions - this is less efficient
        # but works for the expected scale
        all_keys = self.list_keys("prismind:session:")
        
        sessions = []
        suffix = f":{user}"
        
        for key in all_keys:
            if key.endswith(suffix):
                entry = self.get(key)
                if entry and entry.value:
                    sessions.append(SessionState.from_dict(entry.value))
        
        return sessions
