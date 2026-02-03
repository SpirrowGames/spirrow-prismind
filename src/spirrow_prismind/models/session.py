"""Session-related data models."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .document import DocReference


@dataclass
class SessionContext:
    """Context returned when starting a session."""

    # Basic info
    project: str
    project_name: str
    user: str
    started_at: datetime

    # Progress state (from MCP Memory Server)
    current_phase: str
    current_task: str
    last_completed: str
    blockers: list[str] = field(default_factory=list)

    # Recommended documents
    recommended_docs: list[DocReference] = field(default_factory=list)

    # Notes from last session
    notes: str = ""

    # Handoff information from previous session
    last_summary: str = ""
    next_action: str = ""


@dataclass
class SessionState:
    """State saved to MCP Memory Server."""

    project: str
    user: str
    current_phase: str
    current_task: str
    last_completed: str
    blockers: list[str] = field(default_factory=list)
    notes: str = ""
    last_summary: str = ""
    next_action: str = ""
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "project": self.project,
            "user": self.user,
            "current_phase": self.current_phase,
            "current_task": self.current_task,
            "last_completed": self.last_completed,
            "blockers": self.blockers,
            "notes": self.notes,
            "last_summary": self.last_summary,
            "next_action": self.next_action,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        """Create from dictionary."""
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now()

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
            updated_at=updated_at,
        )


@dataclass
class EndSessionResult:
    """Result of ending a session."""

    success: bool
    session_duration: timedelta = field(default_factory=lambda: timedelta(0))
    saved_to: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class SaveSessionResult:
    """Result of saving a session."""

    success: bool
    saved_to: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class SessionInfo:
    """Summary information about a session."""

    project: str
    user: str
    current_phase: str = ""
    current_task: str = ""
    last_completed: str = ""
    blockers: list[str] = field(default_factory=list)
    last_summary: str = ""
    next_action: str = ""
    updated_at: Optional[datetime] = None


@dataclass
class ListSessionsResult:
    """Result of listing sessions."""

    success: bool
    sessions: list[SessionInfo] = field(default_factory=list)
    total_count: int = 0
    message: str = ""


@dataclass
class DeleteSessionResult:
    """Result of deleting a session."""

    success: bool
    project: str = ""
    user: str = ""
    message: str = ""
