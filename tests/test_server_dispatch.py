"""Regression tests for MCP tool dispatch in PrismindServer.

Background: The dispatch handler in server.py was dropping extended fields
(priority, category, blocked_by, user) when forwarding `add_task` and
`update_task_status` calls to the underlying ProgressTools. This led to
silent data loss — the magickit caller saw the field in the response
(because the response is built in magickit), but Google Sheets never
received the value.

These tests pin the contract: the dispatch must pass every documented
field through to the implementation, and the input schemas must declare
the fields so MCP validation does not silently strip them.
"""

import asyncio
from unittest.mock import MagicMock

from spirrow_prismind.server import PrismindServer, TOOLS


def _make_server_with_mock_progress() -> tuple[PrismindServer, MagicMock]:
    """Return a PrismindServer wired to a mocked ProgressTools.

    Skips real initialization by setting _initialized = True.
    """
    server = PrismindServer()
    server._initialized = True

    # The dispatcher checks `not self._project_tools` for tools that require
    # Google auth and bails early; satisfy that with a sentinel mock.
    server._project_tools = MagicMock()

    progress = MagicMock()
    server._progress_tools = progress

    # Default return values that satisfy the response-building code paths.
    progress.add_task.return_value = MagicMock(
        success=True,
        project="test",
        task_id="T01",
        updated_fields=["phase", "task_id", "name", "status"],
        message="ok",
    )
    progress.update_task_status.return_value = MagicMock(
        success=True,
        project="test",
        task_id="T01",
        updated_fields=["status"],
        message="ok",
    )
    return server, progress


def _tool_schema(tool_name: str) -> dict:
    """Look up the inputSchema dict for a Tool by name."""
    for tool in TOOLS:
        if tool.name == tool_name:
            return tool.inputSchema
    raise AssertionError(f"Tool {tool_name!r} not declared in TOOLS")


class TestAddTaskDispatch:
    """Verify add_task dispatch forwards all extended fields."""

    def test_dispatch_forwards_priority_category_blocked_by_user(self):
        server, progress = _make_server_with_mock_progress()

        asyncio.run(
            server._dispatch_tool(
                "add_task",
                {
                    "phase": "design",
                    "task_id": "T99",
                    "name": "Test Task",
                    "description": "desc",
                    "priority": "high",
                    "category": "feature",
                    "blocked_by": ["T01", "T02"],
                    "project": "p1",
                    "user": "u1",
                },
            )
        )

        progress.add_task.assert_called_once()
        kwargs = progress.add_task.call_args.kwargs
        assert kwargs["phase"] == "design"
        assert kwargs["task_id"] == "T99"
        assert kwargs["name"] == "Test Task"
        assert kwargs["description"] == "desc"
        assert kwargs["priority"] == "high"
        assert kwargs["category"] == "feature"
        assert kwargs["blocked_by"] == ["T01", "T02"]
        assert kwargs["project"] == "p1"
        assert kwargs["user"] == "u1"

    def test_dispatch_omits_unspecified_fields_as_none(self):
        """When caller does not supply optional fields, dispatch must pass
        None / default rather than fabricating values."""
        server, progress = _make_server_with_mock_progress()

        asyncio.run(
            server._dispatch_tool(
                "add_task",
                {
                    "phase": "design",
                    "task_id": "T99",
                    "name": "Minimal Task",
                },
            )
        )

        progress.add_task.assert_called_once()
        kwargs = progress.add_task.call_args.kwargs
        # Optional fields should not silently coerce to wrong defaults
        # (e.g. priority must not be hard-coded to "medium" at dispatch).
        assert kwargs.get("priority") in (None, "medium")
        assert kwargs.get("category") in (None, "")
        assert kwargs.get("blocked_by") in (None, [])
        assert kwargs.get("user") is None


class TestAddTaskInputSchema:
    """Verify the MCP input schema declares all fields the dispatch handles."""

    def test_schema_declares_extended_fields(self):
        schema = _tool_schema("add_task")
        properties = schema.get("properties", {})
        for field in ("priority", "category", "blocked_by", "user"):
            assert field in properties, (
                f"add_task input schema must declare {field!r} so MCP "
                f"validators do not strip it. Current schema lists "
                f"{sorted(properties.keys())}."
            )


class TestUpdateTaskStatusDispatch:
    """Verify update_task_status dispatch forwards all extended fields.

    update_task_status is the underlying call for start_task / complete_task /
    block_task convenience wrappers; the wrappers do not currently pass these
    fields, but if a future caller does, dispatch must not drop them.
    """

    def test_dispatch_forwards_priority_category_blocked_by_user(self):
        server, progress = _make_server_with_mock_progress()

        asyncio.run(
            server._dispatch_tool(
                "update_task_status",
                {
                    "task_id": "T01",
                    "status": "in_progress",
                    "phase": "design",
                    "blockers": ["b1"],
                    "notes": "n",
                    "priority": "high",
                    "category": "bug",
                    "blocked_by": ["T00"],
                    "project": "p1",
                    "user": "u1",
                },
            )
        )

        progress.update_task_status.assert_called_once()
        kwargs = progress.update_task_status.call_args.kwargs
        assert kwargs["task_id"] == "T01"
        assert kwargs["status"] == "in_progress"
        assert kwargs["blockers"] == ["b1"]
        assert kwargs["notes"] == "n"
        assert kwargs["priority"] == "high"
        assert kwargs["category"] == "bug"
        assert kwargs["blocked_by"] == ["T00"]
        assert kwargs["user"] == "u1"


class TestUpdateTaskStatusInputSchema:
    def test_schema_declares_extended_fields(self):
        schema = _tool_schema("update_task_status")
        properties = schema.get("properties", {})
        for field in ("priority", "category", "blocked_by", "user"):
            assert field in properties, (
                f"update_task_status input schema must declare {field!r}. "
                f"Current schema lists {sorted(properties.keys())}."
            )


class TestUpsertIdentityDispatch:
    """Verify upsert_identity dispatch forwards all fields and shapes the response."""

    def test_dispatch_forwards_fields_and_returns_identity(self):
        from spirrow_prismind.models import IdentityInfo, UpsertIdentityResult

        server = PrismindServer()
        server._initialized = True
        server._project_tools = MagicMock()
        session = MagicMock()
        server._session_tools = session

        identity = IdentityInfo(
            identity_name="ident-1",
            user="test_user",
            display_name="Test",
            allowed_roles=["proposer", "reviewer"],
            default_role="proposer",
            notes="hi",
            created_at="2026-05-28T00:00:00",
            updated_at="2026-05-28T00:00:01",
        )
        session.upsert_identity.return_value = UpsertIdentityResult(
            success=True, identity=identity, created=True, message="ok",
        )

        result = asyncio.run(
            server._dispatch_tool(
                "upsert_identity",
                {
                    "identity_name": "ident-1",
                    "allowed_roles": ["proposer", "reviewer"],
                    "default_role": "proposer",
                    "display_name": "Test",
                    "notes": "hi",
                    "user": "test_user",
                },
            )
        )

        session.upsert_identity.assert_called_once()
        kwargs = session.upsert_identity.call_args.kwargs
        for field in (
            "identity_name", "allowed_roles", "default_role",
            "display_name", "notes", "user",
        ):
            assert field in kwargs, f"upsert_identity dispatch dropped {field!r}"

        assert result["success"] is True
        assert result["created"] is True
        assert result["identity"]["identity_name"] == "ident-1"
        assert result["identity"]["allowed_roles"] == ["proposer", "reviewer"]

    def test_input_schema_declares_required_and_optional_fields(self):
        schema = _tool_schema("upsert_identity")
        properties = schema.get("properties", {})
        for field in (
            "identity_name", "allowed_roles", "default_role",
            "display_name", "notes", "user",
        ):
            assert field in properties, (
                f"upsert_identity input schema must declare {field!r}. "
                f"Current schema lists {sorted(properties.keys())}."
            )
        assert schema.get("required") == ["identity_name"]


class TestListContextAuthorsDispatchIdentity:
    """list_context_authors response must surface the joined identity field."""

    def test_response_includes_identity_field(self):
        from datetime import datetime

        from spirrow_prismind.models import (
            ContextAuthor,
            ContextAuthorsResult,
            IdentityInfo,
        )

        server = PrismindServer()
        server._initialized = True
        server._project_tools = MagicMock()
        session = MagicMock()
        server._session_tools = session

        identity = IdentityInfo(
            identity_name="ident-1",
            user="u",
            display_name="Disp",
            allowed_roles=["proposer"],
            default_role="proposer",
        )
        session.list_context_authors.return_value = ContextAuthorsResult(
            success=True,
            project="p1",
            authors=[
                ContextAuthor(
                    author="ident-1",
                    user="u",
                    current_phase="P1",
                    current_task="T1",
                    updated_at=datetime(2026, 5, 28, 0, 0, 0),
                    identity=identity,
                ),
                ContextAuthor(
                    author="other",
                    user="u",
                    updated_at=datetime(2026, 5, 27, 0, 0, 0),
                    identity=None,
                ),
            ],
            total_count=2,
            message="",
        )

        result = asyncio.run(
            server._dispatch_tool("list_context_authors", {"project": "p1"})
        )

        assert result["success"] is True
        assert len(result["authors"]) == 2
        with_ident = result["authors"][0]
        assert with_ident["identity"] is not None
        assert with_ident["identity"]["allowed_roles"] == ["proposer"]
        assert with_ident["identity"]["default_role"] == "proposer"

        without_ident = result["authors"][1]
        assert without_ident["identity"] is None


class TestUpdateTaskDispatchUnaffected:
    """Sanity: update_task dispatch was already correct — pin the behavior."""

    def test_dispatch_forwards_all_fields(self):
        server, progress = _make_server_with_mock_progress()
        progress.update_task.return_value = MagicMock(
            success=True,
            project="test",
            task_id="T01",
            updated_fields=["category"],
            phase_moved=False,
            old_phase="design",
            new_phase="design",
            message="ok",
        )

        asyncio.run(
            server._dispatch_tool(
                "update_task",
                {
                    "task_id": "T01",
                    "phase": "design",
                    "name": "n",
                    "description": "d",
                    "status": "in_progress",
                    "priority": "low",
                    "category": "test",
                    "blocked_by": ["T00"],
                    "blockers": ["x"],
                    "new_phase": "implementation",
                    "project": "p1",
                    "user": "u1",
                },
            )
        )

        progress.update_task.assert_called_once()
        kwargs = progress.update_task.call_args.kwargs
        for field in (
            "task_id", "phase", "name", "description", "status",
            "priority", "category", "blocked_by", "blockers", "new_phase",
            "project", "user",
        ):
            assert field in kwargs, f"update_task dispatch dropped {field!r}"
