"""Memory Server client for session state management.

Supports both REST API and MCP/SSE protocols.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

import httpx

logger = logging.getLogger(__name__)


# ===================
# Data Classes
# ===================


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


# ===================
# Backend Interface
# ===================


class MemoryBackend(ABC):
    """Abstract base class for memory storage backends."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the backend is available."""
        ...

    @abstractmethod
    def get(self, key: str) -> Optional[MemoryEntry]:
        """Get a value by key."""
        ...

    @abstractmethod
    def set(self, key: str, value: Any) -> MemoryOperationResult:
        """Set a value."""
        ...

    @abstractmethod
    def delete(self, key: str) -> MemoryOperationResult:
        """Delete a key."""
        ...

    @abstractmethod
    def list_keys(self, prefix: Optional[str] = None) -> list[str]:
        """List keys with optional prefix filter."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Clean up resources."""
        ...


# ===================
# REST Backend
# ===================


class RestMemoryBackend(MemoryBackend):
    """REST API-based memory backend using httpx."""

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 10.0,
        connect_timeout: float = 3.0,
    ):
        """Initialize the REST memory backend.

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
        """Check if the Memory server is available."""
        try:
            httpx.get(
                f"{self.base_url}/health",
                timeout=timeout,
            )
            logger.info(f"REST Memory server connected: {self.base_url}")
            return True
        except Exception as e:
            logger.info(
                f"REST Memory server not available at {self.base_url}: {e} "
                "(Memory server is optional)"
            )
            return False

    @property
    def is_available(self) -> bool:
        """Check if the Memory server is available."""
        return self._available

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        """Make an HTTP request to the memory server."""
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

    def get(self, key: str) -> Optional[MemoryEntry]:
        """Get a value by key."""
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

    def set(self, key: str, value: Any) -> MemoryOperationResult:
        """Set a value."""
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
        """Delete a key."""
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
        """List all keys, optionally filtered by prefix."""
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


# ===================
# MCP/SSE Backend
# ===================


class McpMemoryBackend(MemoryBackend):
    """MCP-based memory backend using SSE transport."""

    def __init__(
        self,
        base_url: str = "http://localhost:8201",
        connect_timeout: float = 5.0,
    ):
        """Initialize the MCP memory backend.

        Args:
            base_url: Memory server URL (will append /sse if needed)
            connect_timeout: Connection timeout in seconds
        """
        # Ensure URL points to /sse endpoint
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/sse"):
            self.sse_url = f"{self.base_url}/sse"
        else:
            self.sse_url = self.base_url

        self._session = None
        self._read_stream = None
        self._write_stream = None
        self._streams_context = None
        self._session_context = None
        self._available = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tools: dict[str, str] = {}  # tool_name -> description

        # Initialize connection
        self._initialize_sync(connect_timeout)

    def _initialize_sync(self, timeout: float):
        """Initialize MCP connection synchronously."""
        try:
            # Create event loop for MCP operations
            try:
                self._loop = asyncio.get_event_loop()
                if self._loop.is_closed():
                    self._loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self._loop)
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

            # Run async initialization with timeout
            self._loop.run_until_complete(
                asyncio.wait_for(self._connect_async(), timeout=timeout)
            )
            self._available = True
        except asyncio.TimeoutError:
            logger.info(
                f"MCP Memory server connection timeout at {self.sse_url} "
                "(Memory server is optional)"
            )
            self._available = False
        except Exception as e:
            logger.info(
                f"MCP Memory server not available at {self.sse_url}: {e} "
                "(Memory server is optional)"
            )
            self._available = False

    async def _connect_async(self):
        """Establish MCP connection asynchronously."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        # Connect via SSE
        self._streams_context = sse_client(url=self.sse_url)
        streams = await self._streams_context.__aenter__()
        self._read_stream, self._write_stream = streams

        # Create session
        self._session_context = ClientSession(self._read_stream, self._write_stream)
        self._session = await self._session_context.__aenter__()

        # Initialize and discover tools
        await self._session.initialize()

        # Get available tools
        tools_result = await self._session.list_tools()
        for tool in tools_result.tools:
            self._tools[tool.name] = tool.description or ""

        logger.info(
            f"MCP Memory server connected: {self.sse_url} "
            f"(tools: {list(self._tools.keys())})"
        )

    def _run_async(self, coro):
        """Run async coroutine from sync context."""
        if self._loop is None or self._loop.is_closed():
            return None
        return self._loop.run_until_complete(coro)

    @property
    def is_available(self) -> bool:
        """Check if the MCP server is available."""
        return self._available

    def close(self):
        """Clean up MCP connection."""
        if self._loop and not self._loop.is_closed():
            try:
                if self._session_context:
                    self._loop.run_until_complete(
                        self._session_context.__aexit__(None, None, None)
                    )
                if self._streams_context:
                    self._loop.run_until_complete(
                        self._streams_context.__aexit__(None, None, None)
                    )
            except Exception as e:
                logger.warning(f"Error closing MCP connection: {e}")

    def _call_tool(self, tool_name: str, arguments: dict) -> Optional[str]:
        """Call an MCP tool and return the result text."""
        if not self._available or not self._session:
            return None

        try:
            result = self._run_async(
                self._session.call_tool(tool_name, arguments)
            )
            if result and result.content:
                # MCP tool results are typically TextContent
                return result.content[0].text
            return None
        except Exception as e:
            logger.error(f"MCP tool call '{tool_name}' failed: {e}")
            return None

    def get(self, key: str) -> Optional[MemoryEntry]:
        """Get a value by key via MCP tool call."""
        if not self._available:
            return None

        # Try common tool names for memory get
        for tool_name in ["memory_get", "get", "read"]:
            if tool_name in self._tools:
                result_text = self._call_tool(tool_name, {"key": key})
                if result_text:
                    try:
                        data = json.loads(result_text)
                        if data.get("found", True):  # Assume found if not specified
                            return MemoryEntry(
                                key=key,
                                value=data.get("value"),
                                created_at=data.get("created_at", ""),
                                updated_at=data.get("updated_at", ""),
                            )
                    except json.JSONDecodeError:
                        # If not JSON, treat as raw value
                        return MemoryEntry(key=key, value=result_text)
                return None

        logger.warning("No compatible 'get' tool found in MCP Memory server")
        return None

    def set(self, key: str, value: Any) -> MemoryOperationResult:
        """Set a value via MCP tool call."""
        if not self._available:
            return MemoryOperationResult(
                success=False, key=key, message="MCP not available"
            )

        # Serialize value to JSON if needed
        if not isinstance(value, str):
            value = json.dumps(value)

        # Try common tool names for memory set
        for tool_name in ["memory_set", "set", "write", "store"]:
            if tool_name in self._tools:
                result_text = self._call_tool(tool_name, {"key": key, "value": value})
                return MemoryOperationResult(
                    success=True,
                    key=key,
                    message=f"Value set via MCP ({tool_name})",
                )

        logger.warning("No compatible 'set' tool found in MCP Memory server")
        return MemoryOperationResult(
            success=False, key=key, message="No compatible set tool found"
        )

    def delete(self, key: str) -> MemoryOperationResult:
        """Delete a key via MCP tool call."""
        if not self._available:
            return MemoryOperationResult(
                success=False, key=key, message="MCP not available"
            )

        # Try common tool names for memory delete
        for tool_name in ["memory_delete", "delete", "remove"]:
            if tool_name in self._tools:
                self._call_tool(tool_name, {"key": key})
                return MemoryOperationResult(
                    success=True,
                    key=key,
                    message=f"Key deleted via MCP ({tool_name})",
                )

        logger.warning("No compatible 'delete' tool found in MCP Memory server")
        return MemoryOperationResult(
            success=False, key=key, message="No compatible delete tool found"
        )

    def list_keys(self, prefix: Optional[str] = None) -> list[str]:
        """List keys via MCP tool call."""
        if not self._available:
            return []

        # Try common tool names for memory list
        for tool_name in ["memory_list", "list", "list_keys", "keys"]:
            if tool_name in self._tools:
                args = {"prefix": prefix} if prefix else {}
                result_text = self._call_tool(tool_name, args)
                if result_text:
                    try:
                        data = json.loads(result_text)
                        return data.get("keys", [])
                    except json.JSONDecodeError:
                        pass
                return []

        logger.warning("No compatible 'list' tool found in MCP Memory server")
        return []


# ===================
# Unified Client
# ===================


class MemoryClient:
    """Client for Memory Server operations.

    Supports both REST and MCP protocols based on configuration.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 10.0,
        connect_timeout: float = 3.0,
        protocol: Literal["rest", "mcp"] = "rest",
    ):
        """Initialize the memory client.

        Args:
            base_url: Memory server URL
            timeout: Request timeout in seconds
            connect_timeout: Connection check timeout in seconds
            protocol: Protocol to use ("rest" or "mcp")
        """
        self._protocol = protocol

        if protocol == "mcp":
            self._backend: MemoryBackend = McpMemoryBackend(
                base_url=base_url,
                connect_timeout=connect_timeout,
            )
        else:
            self._backend = RestMemoryBackend(
                base_url=base_url,
                timeout=timeout,
                connect_timeout=connect_timeout,
            )

    @property
    def is_available(self) -> bool:
        """Check if the Memory server is available."""
        return self._backend.is_available

    def close(self):
        """Close the client."""
        self._backend.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ===================
    # Basic Operations (delegated to backend)
    # ===================

    def get(self, key: str) -> Optional[MemoryEntry]:
        """Get a value by key."""
        return self._backend.get(key)

    def set(self, key: str, value: Any) -> MemoryOperationResult:
        """Set a value."""
        return self._backend.set(key, value)

    def delete(self, key: str) -> MemoryOperationResult:
        """Delete a key."""
        return self._backend.delete(key)

    def list_keys(self, prefix: Optional[str] = None) -> list[str]:
        """List all keys, optionally filtered by prefix."""
        return self._backend.list_keys(prefix)

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

        # Handle both dict and string values
        if isinstance(entry.value, str):
            try:
                value = json.loads(entry.value)
            except json.JSONDecodeError:
                return None
        else:
            value = entry.value

        return SessionState.from_dict(value)

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

        # Handle both dict and string values
        if isinstance(entry.value, str):
            try:
                value = json.loads(entry.value)
            except json.JSONDecodeError:
                return None
        else:
            value = entry.value

        return CurrentProject.from_dict(value)

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
                if isinstance(entry.value, str):
                    try:
                        value = json.loads(entry.value)
                        sessions.append(SessionState.from_dict(value))
                    except json.JSONDecodeError:
                        pass
                else:
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
                    if isinstance(entry.value, str):
                        try:
                            value = json.loads(entry.value)
                            sessions.append(SessionState.from_dict(value))
                        except json.JSONDecodeError:
                            pass
                    else:
                        sessions.append(SessionState.from_dict(entry.value))

        return sessions
