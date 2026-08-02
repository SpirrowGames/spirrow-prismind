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

    # Context-author partition this context belongs to ("" = default/legacy)
    author: str = ""


@dataclass
class SessionState:
    """State saved to MCP Memory Server.

    ``embodiment`` (ADR-2026-05-29-12) is the self-declared runtime form of
    the calling agent at the moment of the latest checkpoint / resume.
    """

    project: str
    user: str
    current_phase: str
    current_task: str
    last_completed: str
    blockers: list[str] = field(default_factory=list)
    notes: str = ""
    last_summary: str = ""
    next_action: str = ""
    author: str = ""
    updated_at: datetime = field(default_factory=datetime.now)
    embodiment: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "project": self.project,
            "user": self.user,
            "author": self.author,
            "current_phase": self.current_phase,
            "current_task": self.current_task,
            "last_completed": self.last_completed,
            "blockers": self.blockers,
            "notes": self.notes,
            "last_summary": self.last_summary,
            "next_action": self.next_action,
            "updated_at": self.updated_at.isoformat(),
            "embodiment": self.embodiment,
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
            author=data.get("author", ""),
            updated_at=updated_at,
            embodiment=data.get("embodiment"),
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
    author: str = ""
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


@dataclass
class IdentityInfo:
    """Identity record attached to a context author when one is registered.

    Shape locked by msg-002 §1.1 / msg-005 D-5 (α) on
    T-magickit-identity-extension, revised by ADR-2026-05-29-12 on
    T-embodiment-self-declared: ``embodiment`` is now ``Optional[str]``
    (deprecated on identity, self-declared at runtime). For human
    identities the response-side serializer omits the key entirely
    (see ``_identity_to_response_dict`` in memory_client).
    """

    identity_name: str = ""
    user: str = ""
    allowed_roles: list[str] = field(default_factory=list)
    embodiment: Optional[str] = None  # DEPRECATED -- ADR-2026-05-29-12
    independence_class: str = ""
    persona_description: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        """Serialize for API response.

        Applies ADR-2026-05-29-12 §3 "case 3" human-omit: human identities
        omit the ``embodiment`` key entirely (not None). The pinned test
        ``test_human_identity_response_omits_embodiment`` fails if a human
        record ever leaks the key, catching silent regression.
        """
        out: dict = {
            "identity_name": self.identity_name,
            "user": self.user,
            "allowed_roles": list(self.allowed_roles),
            "independence_class": self.independence_class,
            "persona_description": self.persona_description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        # Avoid importing memory_client here -- keep the constant inline
        # (it is intentionally short and matches the upstream definition).
        if self.identity_name not in ("human",):
            out["embodiment"] = self.embodiment
        return out


@dataclass
class ContextAuthor:
    """A distinct context author that has saved state for a project."""

    author: str = ""
    user: str = ""
    current_phase: str = ""
    current_task: str = ""
    updated_at: Optional[datetime] = None
    identity: Optional[IdentityInfo] = None


@dataclass
class ContextAuthorsResult:
    """Result of listing the context authors saved for a project."""

    success: bool
    project: str = ""
    authors: list[ContextAuthor] = field(default_factory=list)
    total_count: int = 0
    message: str = ""


@dataclass
class UpsertIdentityResult:
    """Result of upsert_identity."""

    success: bool
    identity: Optional[IdentityInfo] = None
    created: bool = False
    message: str = ""


@dataclass
class GetIdentityResult:
    """Result of get_identity (single identity lookup by name).

    ``found`` is the load-bearing field and is deliberately separate from
    ``success``: Magickit's role × allowed_roles gate must distinguish
    "this identity is not registered" (``success=True, found=False`` ->
    legacy skip, the post is allowed) from "the lookup itself failed"
    (``success=False`` -> the gate could not run, so the post must not
    silently proceed as if it had). Collapsing the two into
    ``identity is None`` would make an outage indistinguishable from a
    permissive verdict.
    """

    success: bool
    found: bool = False
    identity: Optional[IdentityInfo] = None
    message: str = ""
