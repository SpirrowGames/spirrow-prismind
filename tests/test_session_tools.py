"""Tests for SessionTools."""

import pytest
from datetime import datetime, timedelta


class TestStartSession:
    """Tests for start_session method."""

    def test_start_session_with_project(self, session_tools, project_tools, mock_memory_client):
        """Test starting session with existing project."""
        # Setup project first
        project_tools.setup_project(
            project="session_proj",
            name="Session Test Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Start session
        context = session_tools.start_session(project="session_proj")

        assert context.project == "session_proj"
        assert context.project_name == "Session Test Project"
        assert context.user == "test_user"
        assert context.started_at is not None
        assert session_tools.is_session_active is True

    def test_start_session_uses_current_project(self, session_tools, project_tools, mock_memory_client):
        """Test starting session uses current project if not specified."""
        # Setup and switch to project
        project_tools.setup_project(
            project="current_session",
            name="Current Session Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Start session without specifying project
        context = session_tools.start_session()

        assert context.project == "current_session"
        assert context.project_name == "Current Session Project"

    def test_start_session_no_project(self, session_tools):
        """Test starting session without any project."""
        context = session_tools.start_session()

        assert context.project == ""
        assert "プロジェクトが指定されていません" in context.notes

    def test_start_session_project_not_found(self, session_tools):
        """Test starting session with non-existent project."""
        context = session_tools.start_session(project="nonexistent")

        assert context.project == "nonexistent"
        assert "設定が見つかりません" in context.notes

    def test_start_session_restores_state(self, session_tools, project_tools, mock_memory_client):
        """Test starting session restores saved state."""
        from spirrow_prismind.integrations.memory_client import SessionState

        # Setup project
        project_tools.setup_project(
            project="restore_proj",
            name="Restore Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Save some state
        state = SessionState(
            project="restore_proj",
            user="test_user",
            current_phase="Phase 2",
            current_task="T03: Implementation",
            last_completed="T02",
            blockers=["Waiting for API"],
            notes="Previous session notes",
        )
        mock_memory_client.save_session_state(state)

        # Start session
        context = session_tools.start_session(project="restore_proj")

        assert context.current_phase == "Phase 2"
        assert context.current_task == "T03: Implementation"
        assert context.last_completed == "T02"
        assert "Waiting for API" in context.blockers
        assert context.notes == "Previous session notes"


class TestEndSession:
    """Tests for end_session method."""

    def test_end_session_success(self, session_tools, project_tools, mock_memory_client):
        """Test ending session saves state."""
        # Setup and start session
        project_tools.setup_project(
            project="end_proj",
            name="End Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="end_proj")

        # End session
        result = session_tools.end_session(
            summary="Completed task A and B",
            next_action="Start task C",
            blockers=["Need review"],
            notes="Important notes",
        )

        assert result.success is True
        assert len(result.saved_to) > 0
        assert "保存しました" in result.message
        assert session_tools.is_session_active is False

        # Verify state was saved
        state = mock_memory_client.get_session_state("end_proj", "test_user")
        assert state is not None
        assert state.last_summary == "Completed task A and B"
        assert state.next_action == "Start task C"
        assert "Need review" in state.blockers

    def test_end_session_no_active_session(self, session_tools):
        """Test ending session when no session is active."""
        result = session_tools.end_session()

        assert result.success is False
        assert "アクティブなセッションがありません" in result.message

    def test_end_session_with_explicit_project(self, session_tools, project_tools, mock_memory_client):
        """Test ending session with explicit project parameter."""
        # Setup two projects
        project_tools.setup_project(
            project="proj_a",
            name="Project A",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        project_tools.setup_project(
            project="proj_b",
            name="Project B",
            spreadsheet_id="sheet2",
            root_folder_id="folder2",
            create_sheets=False,
            create_folders=False,
        )

        # Start session on proj_a
        session_tools.start_session(project="proj_a")

        # End session with explicit project=proj_b (different from current)
        result = session_tools.end_session(
            summary="Work on proj_b",
            next_action="Continue proj_b",
            project="proj_b",
        )

        assert result.success is True

        # Verify state was saved to proj_b
        state = mock_memory_client.get_session_state("proj_b", "test_user")
        assert state is not None
        assert state.last_summary == "Work on proj_b"

    def test_end_session_uses_current_when_project_none(self, session_tools, project_tools, mock_memory_client):
        """Test end_session uses current project when project is None."""
        # Setup and start session
        project_tools.setup_project(
            project="current_proj",
            name="Current Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="current_proj")

        # End session without project parameter
        result = session_tools.end_session(
            summary="Work done",
            project=None,  # Explicitly None
        )

        assert result.success is True

        # Verify state was saved to current project
        state = mock_memory_client.get_session_state("current_proj", "test_user")
        assert state is not None
        assert state.last_summary == "Work done"


class TestSaveSession:
    """Tests for save_session method."""

    def test_save_session_updates_state(self, session_tools, project_tools, mock_memory_client):
        """Test saving session updates state without ending."""
        # Setup and start session
        project_tools.setup_project(
            project="save_proj",
            name="Save Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="save_proj")

        # Save session
        result = session_tools.save_session(
            summary="Work in progress",
            current_phase="Phase 3",
            current_task="T05",
        )

        assert result.success is True
        assert len(result.saved_to) > 0
        assert session_tools.is_session_active is True  # Session still active

        # Verify state was updated
        state = mock_memory_client.get_session_state("save_proj", "test_user")
        assert state is not None
        assert state.current_phase == "Phase 3"
        assert state.current_task == "T05"

    def test_save_session_no_project(self, session_tools):
        """Test saving session without active project."""
        result = session_tools.save_session()

        assert result.success is False
        assert "アクティブなプロジェクトがありません" in result.message

    def test_save_session_with_explicit_project(self, session_tools, project_tools, mock_memory_client):
        """Test saving session with explicit project parameter."""
        # Setup two projects
        project_tools.setup_project(
            project="save_proj_a",
            name="Save Project A",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        project_tools.setup_project(
            project="save_proj_b",
            name="Save Project B",
            spreadsheet_id="sheet2",
            root_folder_id="folder2",
            create_sheets=False,
            create_folders=False,
        )

        # Start session on save_proj_a
        session_tools.start_session(project="save_proj_a")

        # Save session with explicit project=save_proj_b
        result = session_tools.save_session(
            summary="Work on proj_b",
            current_phase="Phase 2",
            project="save_proj_b",
        )

        assert result.success is True

        # Verify state was saved to save_proj_b
        state = mock_memory_client.get_session_state("save_proj_b", "test_user")
        assert state is not None
        assert state.last_summary == "Work on proj_b"
        assert state.current_phase == "Phase 2"

    def test_save_session_uses_current_when_project_omitted(self, session_tools, project_tools, mock_memory_client):
        """Test save_session uses current project when project is omitted."""
        # Setup and start session
        project_tools.setup_project(
            project="save_current_proj",
            name="Save Current Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="save_current_proj")

        # Save session without project parameter
        result = session_tools.save_session(
            summary="Work in progress",
            current_phase="Phase 4",
        )

        assert result.success is True

        # Verify state was saved to current project
        state = mock_memory_client.get_session_state("save_current_proj", "test_user")
        assert state is not None
        assert state.last_summary == "Work in progress"
        assert state.current_phase == "Phase 4"


class TestUpdateProgress:
    """Tests for update_progress method."""

    def test_update_progress_current_task(self, session_tools, project_tools, mock_memory_client):
        """Test updating current task."""
        # Setup and start session
        project_tools.setup_project(
            project="progress_proj",
            name="Progress Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="progress_proj")

        # Update progress
        result = session_tools.update_progress(
            current_phase="Phase 4",
            current_task="T10",
            completed_task="T09",
        )

        assert result.success is True

        # Verify state
        state = mock_memory_client.get_session_state("progress_proj", "test_user")
        assert state.current_phase == "Phase 4"
        assert state.current_task == "T10"
        assert state.last_completed == "T09"

    def test_update_progress_blockers(self, session_tools, project_tools, mock_memory_client):
        """Test updating blockers."""
        # Setup and start session
        project_tools.setup_project(
            project="blocker_proj",
            name="Blocker Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="blocker_proj")

        # Update with blockers
        result = session_tools.update_progress(
            blockers=["Blocker 1", "Blocker 2"],
        )

        assert result.success is True

        # Verify blockers
        state = mock_memory_client.get_session_state("blocker_proj", "test_user")
        assert len(state.blockers) == 2
        assert "Blocker 1" in state.blockers

    def test_update_progress_with_explicit_project(self, session_tools, project_tools, mock_memory_client):
        """Test updating progress with explicit project parameter."""
        # Setup two projects
        project_tools.setup_project(
            project="progress_proj_a",
            name="Progress Project A",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        project_tools.setup_project(
            project="progress_proj_b",
            name="Progress Project B",
            spreadsheet_id="sheet2",
            root_folder_id="folder2",
            create_sheets=False,
            create_folders=False,
        )

        # Start session on progress_proj_a
        session_tools.start_session(project="progress_proj_a")

        # Update progress with explicit project=progress_proj_b
        result = session_tools.update_progress(
            current_phase="Phase 5",
            current_task="T15",
            completed_task="T14",
            project="progress_proj_b",
        )

        assert result.success is True

        # Verify state was saved to progress_proj_b
        state = mock_memory_client.get_session_state("progress_proj_b", "test_user")
        assert state is not None
        assert state.current_phase == "Phase 5"
        assert state.current_task == "T15"
        assert state.last_completed == "T14"

    def test_update_progress_uses_current_when_project_omitted(self, session_tools, project_tools, mock_memory_client):
        """Test update_progress uses current project when project is omitted."""
        # Setup and start session
        project_tools.setup_project(
            project="progress_current_proj",
            name="Progress Current Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="progress_current_proj")

        # Update progress without project parameter
        result = session_tools.update_progress(
            current_phase="Phase 6",
            current_task="T20",
        )

        assert result.success is True

        # Verify state was saved to current project
        state = mock_memory_client.get_session_state("progress_current_proj", "test_user")
        assert state is not None
        assert state.current_phase == "Phase 6"
        assert state.current_task == "T20"


class TestSessionDuration:
    """Tests for session duration tracking."""

    def test_session_duration_tracking(self, session_tools, project_tools):
        """Test session duration is tracked."""
        # Setup and start session
        project_tools.setup_project(
            project="duration_proj",
            name="Duration Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="duration_proj")

        # Check duration is being tracked
        duration = session_tools.current_session_duration
        assert duration is not None
        assert isinstance(duration, timedelta)

    def test_session_duration_format(self, session_tools):
        """Test duration formatting."""
        # Test various durations
        assert session_tools._format_duration(timedelta(seconds=30)) == "30秒"
        assert session_tools._format_duration(timedelta(minutes=5)) == "5分"
        assert session_tools._format_duration(timedelta(hours=2, minutes=30)) == "2時間30分"
        assert session_tools._format_duration(timedelta(hours=1, minutes=5, seconds=10)) == "1時間5分10秒"


class TestIsSessionActive:
    """Tests for is_session_active property."""

    def test_session_inactive_by_default(self, session_tools):
        """Test session is inactive by default."""
        assert session_tools.is_session_active is False

    def test_session_active_after_start(self, session_tools, project_tools):
        """Test session is active after start."""
        project_tools.setup_project(
            project="active_proj",
            name="Active Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="active_proj")

        assert session_tools.is_session_active is True

    def test_session_inactive_after_end(self, session_tools, project_tools):
        """Test session is inactive after end."""
        project_tools.setup_project(
            project="inactive_proj",
            name="Inactive Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="inactive_proj")
        session_tools.end_session()

        assert session_tools.is_session_active is False


class TestHandoffRestore:
    """Tests for handoff information restoration (last_summary, next_action)."""

    def test_handoff_info_restored_on_start_session(self, session_tools, project_tools, mock_memory_client):
        """Test that last_summary and next_action are restored when starting a new session."""
        from spirrow_prismind.integrations.memory_client import SessionState

        # Setup project
        project_tools.setup_project(
            project="handoff_proj",
            name="Handoff Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Simulate previous session's end_session by saving state with handoff info
        state = SessionState(
            project="handoff_proj",
            user="test_user",
            current_phase="Phase 3",
            current_task="T07: Review",
            last_completed="T06",
            blockers=["Waiting for approval"],
            notes="Remember to check edge cases",
            last_summary="Completed API implementation and unit tests",
            next_action="Start integration testing with frontend",
        )
        mock_memory_client.save_session_state(state)

        # Start new session - should restore handoff info
        context = session_tools.start_session(project="handoff_proj")

        assert context.last_summary == "Completed API implementation and unit tests"
        assert context.next_action == "Start integration testing with frontend"
        assert context.notes == "Remember to check edge cases"
        assert context.current_phase == "Phase 3"

    def test_end_session_saves_handoff_info(self, session_tools, project_tools, mock_memory_client):
        """Test that end_session correctly saves last_summary and next_action."""
        # Setup and start session
        project_tools.setup_project(
            project="end_handoff_proj",
            name="End Handoff Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="end_handoff_proj")

        # End session with handoff info
        result = session_tools.end_session(
            summary="Finished implementing feature X",
            next_action="Deploy to staging and test",
            blockers=["Need staging credentials"],
            notes="Config changes needed for production",
        )

        assert result.success is True

        # Verify state was saved with handoff info
        state = mock_memory_client.get_session_state("end_handoff_proj", "test_user")
        assert state is not None
        assert state.last_summary == "Finished implementing feature X"
        assert state.next_action == "Deploy to staging and test"
        assert state.notes == "Config changes needed for production"

    def test_full_handoff_cycle(self, session_tools, project_tools, mock_memory_client):
        """Test complete handoff cycle: start -> end -> start (new session)."""
        # Setup project
        project_tools.setup_project(
            project="cycle_proj",
            name="Cycle Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Session 1: Start and end with handoff info
        session_tools.start_session(project="cycle_proj")
        session_tools.end_session(
            summary="Session 1 completed task A",
            next_action="Continue with task B",
            notes="Important: check the logs",
        )

        # Session 2: Start and verify handoff info is restored
        context = session_tools.start_session(project="cycle_proj")

        assert context.last_summary == "Session 1 completed task A"
        assert context.next_action == "Continue with task B"
        assert context.notes == "Important: check the logs"


class TestListSessions:
    """Tests for list_sessions method."""

    def test_list_sessions_empty(self, session_tools):
        """Test listing sessions when none exist."""
        result = session_tools.list_sessions()

        assert result.success is True
        assert result.total_count == 0
        assert len(result.sessions) == 0

    def test_list_sessions_returns_all_for_user(self, session_tools, project_tools, mock_memory_client):
        """Test listing all sessions for a user."""
        # Setup multiple projects and sessions
        for proj in ["list_proj_a", "list_proj_b", "list_proj_c"]:
            project_tools.setup_project(
                project=proj,
                name=f"List Test {proj}",
                spreadsheet_id="sheet1",
                root_folder_id="folder1",
                create_sheets=False,
                create_folders=False,
            )
            session_tools.start_session(project=proj)
            session_tools.end_session(summary=f"Summary for {proj}")

        # List all sessions
        result = session_tools.list_sessions()

        assert result.success is True
        assert result.total_count == 3
        assert len(result.sessions) == 3

        # Check all projects are present
        projects = {s.project for s in result.sessions}
        assert "list_proj_a" in projects
        assert "list_proj_b" in projects
        assert "list_proj_c" in projects

    def test_list_sessions_filter_by_project(self, session_tools, project_tools, mock_memory_client):
        """Test listing sessions filtered by project."""
        # Setup two projects
        for proj in ["filter_proj_a", "filter_proj_b"]:
            project_tools.setup_project(
                project=proj,
                name=f"Filter Test {proj}",
                spreadsheet_id="sheet1",
                root_folder_id="folder1",
                create_sheets=False,
                create_folders=False,
            )
            session_tools.start_session(project=proj)
            session_tools.end_session(summary=f"Summary for {proj}")

        # List sessions for specific project
        result = session_tools.list_sessions(project="filter_proj_a")

        assert result.success is True
        assert result.total_count == 1
        assert result.sessions[0].project == "filter_proj_a"


class TestDeleteSession:
    """Tests for delete_session method."""

    def test_delete_session_success(self, session_tools, project_tools, mock_memory_client):
        """Test deleting an existing session."""
        # Setup and create a session
        project_tools.setup_project(
            project="delete_proj",
            name="Delete Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )
        session_tools.start_session(project="delete_proj")
        session_tools.end_session(summary="Session to delete")

        # Verify session exists
        state = mock_memory_client.get_session_state("delete_proj", "test_user")
        assert state is not None

        # Delete the session
        result = session_tools.delete_session(project="delete_proj")

        assert result.success is True
        assert result.project == "delete_proj"
        assert "削除しました" in result.message

        # Verify session is deleted
        state = mock_memory_client.get_session_state("delete_proj", "test_user")
        assert state is None

    def test_delete_session_not_found(self, session_tools):
        """Test deleting a non-existent session."""
        result = session_tools.delete_session(project="nonexistent_proj")

        assert result.success is False
        assert "見つかりません" in result.message

    def test_delete_session_no_project(self, session_tools):
        """Test deleting without project ID."""
        result = session_tools.delete_session(project="")

        assert result.success is False
        assert "指定されていません" in result.message

    def test_delete_session_cleans_up_for_list(self, session_tools, project_tools, mock_memory_client):
        """Test that deleted session is no longer listed."""
        # Setup multiple sessions
        for proj in ["cleanup_a", "cleanup_b"]:
            project_tools.setup_project(
                project=proj,
                name=f"Cleanup Test {proj}",
                spreadsheet_id="sheet1",
                root_folder_id="folder1",
                create_sheets=False,
                create_folders=False,
            )
            session_tools.start_session(project=proj)
            session_tools.end_session(summary=f"Summary for {proj}")

        # Verify both sessions exist
        list_result = session_tools.list_sessions()
        assert list_result.total_count == 2

        # Delete one session
        delete_result = session_tools.delete_session(project="cleanup_a")
        assert delete_result.success is True

        # Verify only one session remains
        list_result = session_tools.list_sessions()
        assert list_result.total_count == 1
        assert list_result.sessions[0].project == "cleanup_b"


class TestContextAuthorPartition:
    """Tests for context-author partitioning of session state."""

    def _setup(self, project_tools, project):
        project_tools.setup_project(
            project=project,
            name=f"{project} name",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

    def test_authors_have_isolated_contexts(self, session_tools, project_tools):
        """Different authors save independent contexts under the same project."""
        self._setup(project_tools, "ap_proj")

        session_tools.save_session(
            project="ap_proj", summary="architect work",
            current_task="T-arch", author="claude.ai",
        )
        session_tools.save_session(
            project="ap_proj", summary="impl work",
            current_task="T-impl", author="claude-code",
        )

        arch = session_tools.start_session(project="ap_proj", author="claude.ai")
        impl = session_tools.start_session(project="ap_proj", author="claude-code")

        assert arch.author == "claude.ai"
        assert arch.current_task == "T-arch"
        assert arch.last_summary == "architect work"
        assert impl.author == "claude-code"
        assert impl.current_task == "T-impl"
        assert impl.last_summary == "impl work"

    def test_empty_author_keeps_legacy_context(self, session_tools, project_tools, mock_memory_client):
        """A no-author save uses the legacy key and is not seen by authored reads."""
        self._setup(project_tools, "legacy_proj")

        session_tools.save_session(
            project="legacy_proj", summary="legacy", current_task="T-legacy",
        )

        # Legacy key format preserved (no trailing author segment)
        assert mock_memory_client.get("prismind:session:legacy_proj:test_user") is not None

        default_ctx = session_tools.start_session(project="legacy_proj")
        assert default_ctx.current_task == "T-legacy"
        assert default_ctx.author == ""

        # An authored read does not pick up the legacy context
        authored = session_tools.start_session(project="legacy_proj", author="claude.ai")
        assert authored.current_task == ""

    def test_list_context_authors(self, session_tools, project_tools):
        """list_context_authors returns the distinct authors saved for a project."""
        self._setup(project_tools, "lca_proj")

        session_tools.save_session(project="lca_proj", summary="a", author="claude.ai")
        session_tools.save_session(project="lca_proj", summary="b", author="claude-code")
        session_tools.save_session(project="lca_proj", summary="c")  # default/legacy

        result = session_tools.list_context_authors(project="lca_proj")

        assert result.success is True
        assert result.total_count == 3
        authors = {a.author for a in result.authors}
        assert authors == {"claude.ai", "claude-code", ""}

    def test_list_context_authors_requires_project(self, session_tools):
        """list_context_authors fails fast without a project."""
        result = session_tools.list_context_authors(project="")
        assert result.success is False

    def test_delete_session_targets_author(self, session_tools, project_tools):
        """delete_session removes only the targeted author's context."""
        self._setup(project_tools, "del_proj")
        session_tools.save_session(project="del_proj", summary="a", author="claude.ai")
        session_tools.save_session(project="del_proj", summary="b", author="claude-code")

        session_tools.delete_session(project="del_proj", author="claude.ai")

        remaining = {a.author for a in session_tools.list_context_authors(project="del_proj").authors}
        assert remaining == {"claude-code"}


class TestUpsertIdentity:
    """Tests for upsert_identity and identity join on list_context_authors.

    Shape locked by msg-002 §1.1 / msg-005 D-5 (α) and revised by
    ADR-2026-05-29-12: ``independence_class`` is required on every upsert,
    ``allowed_roles`` is required unless ``keep_allowed_roles=True``,
    ``embodiment`` is **DEPRECATED** (optional, default None, no enum
    validation; runtime self-declared at Magickit level).
    """

    def _setup(self, project_tools, project):
        project_tools.setup_project(
            project=project,
            name=f"{project} name",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

    def test_upsert_identity_creates_record(self, session_tools, mock_memory_client):
        """A fresh upsert returns created=True and persists the required fields.

        ``embodiment`` defaults to None per ADR-12; it is no longer
        declared at upsert time.
        """
        result = session_tools.upsert_identity(
            identity_name="Heisenberg",
            independence_class="main-chain",
            allowed_roles=["proposer", "reviewer", "implementer"],
            persona_description="Heisenberg persona note",
        )

        assert result.success is True
        assert result.created is True
        assert result.identity is not None
        assert result.identity.identity_name == "Heisenberg"
        assert result.identity.allowed_roles == ["proposer", "reviewer", "implementer"]
        assert result.identity.independence_class == "main-chain"
        assert result.identity.persona_description == "Heisenberg persona note"
        # ADR-12: embodiment default is None on the identity record.
        assert result.identity.embodiment is None
        assert result.identity.created_at
        assert result.identity.updated_at

        # Verify persistence in the key space
        from spirrow_prismind.integrations.memory_client import Identity
        stored = mock_memory_client.get_identity("test_user", "Heisenberg")
        assert isinstance(stored, Identity)
        assert stored.allowed_roles == ["proposer", "reviewer", "implementer"]
        assert stored.embodiment is None
        assert stored.independence_class == "main-chain"

    def test_embodiment_deprecated_accepts_any_value(self, session_tools):
        """ADR-12: embodiment is no longer enum-validated at upsert time.

        Any value (or None) is accepted; the field is preserved on the
        record only for the staged migration window (step (i)). Runtime
        self-declaration on Magickit-level APIs is the new source.
        """
        # None (default behavior) accepted
        r = session_tools.upsert_identity(
            identity_name="ident-none",
            independence_class="main-chain",
            allowed_roles=["proposer"],
        )
        assert r.success is True
        assert r.identity.embodiment is None

        # A previously-invalid value also accepted (no enum check)
        r = session_tools.upsert_identity(
            identity_name="ident-arbitrary",
            independence_class="main-chain",
            allowed_roles=["proposer"],
            embodiment="cli_robot",
        )
        assert r.success is True
        assert r.identity.embodiment == "cli_robot"

    def test_independence_class_required_and_enum_validated(self, session_tools):
        """independence_class must be one of INDEPENDENCE_CLASS_VALUES."""
        r = session_tools.upsert_identity(
            identity_name="ident-1",
            independence_class="",
            allowed_roles=["proposer"],
        )
        assert r.success is False
        assert "independence_class" in r.message

        r = session_tools.upsert_identity(
            identity_name="ident-1",
            independence_class="hybrid",
            allowed_roles=["proposer"],
        )
        assert r.success is False
        assert "independence_class" in r.message

    def test_machine_is_a_valid_independence_class(self, session_tools):
        """`machine` is a legitimate independence_class value (spirrow-mindwire
        T-role-null-must-become-impossible msg-1706 §2). Prismind accepts it;
        semantic restrictions (e.g. must pair with allowed_roles=[]) belong
        to the client, not this validation gate."""
        r = session_tools.upsert_identity(
            identity_name="ident-machine-smoke",
            independence_class="machine",
            allowed_roles=[],
        )
        assert r.success is True
        assert r.identity.independence_class == "machine"
        # And a machine record with a role is legal at THIS layer -- the client
        # would refuse to construct it, but Prismind does not police it.
        r2 = session_tools.upsert_identity(
            identity_name="ident-machine-with-role",
            independence_class="machine",
            allowed_roles=["proposer"],
        )
        assert r2.success is True

    def test_allowed_roles_required_without_keep_flag(self, session_tools):
        """Omitting allowed_roles without keep_allowed_roles=True fails."""
        r = session_tools.upsert_identity(
            identity_name="ident-1",
            independence_class="main-chain",
        )
        assert r.success is False
        assert "allowed_roles" in r.message

    def test_keep_allowed_roles_preserves_existing(self, session_tools):
        """keep_allowed_roles=True preserves the list across update."""
        # Initial create
        first = session_tools.upsert_identity(
            identity_name="ident-1",
            independence_class="main-chain",
            allowed_roles=["proposer", "reviewer"],
            persona_description="orig",
        )
        assert first.success is True
        original_created = first.identity.created_at

        # Update with keep_allowed_roles, change persona_description
        updated = session_tools.upsert_identity(
            identity_name="ident-1",
            independence_class="main-chain",
            keep_allowed_roles=True,
            persona_description="new",
        )
        assert updated.success is True
        assert updated.created is False
        assert updated.identity.allowed_roles == ["proposer", "reviewer"]
        assert updated.identity.persona_description == "new"
        # created_at preserved
        assert updated.identity.created_at == original_created

    def test_keep_allowed_roles_and_list_conflict(self, session_tools):
        """Passing both allowed_roles and keep_allowed_roles=True fails."""
        r = session_tools.upsert_identity(
            identity_name="ident-1",
            independence_class="main-chain",
            allowed_roles=["proposer"],
            keep_allowed_roles=True,
        )
        assert r.success is False
        assert "keep_allowed_roles" in r.message and "allowed_roles" in r.message

    def test_keep_allowed_roles_on_new_identity_fails(self, session_tools):
        """keep_allowed_roles=True on a new identity fails (nothing to keep)."""
        r = session_tools.upsert_identity(
            identity_name="never-existed",
            independence_class="main-chain",
            keep_allowed_roles=True,
        )
        assert r.success is False
        assert "keep_allowed_roles" in r.message

    def test_explicit_empty_allowed_roles_legal(self, session_tools):
        """allowed_roles=[] is a legal explicit declaration of zero roles."""
        r = session_tools.upsert_identity(
            identity_name="silent-actor",
            independence_class="independent",
            allowed_roles=[],
        )
        assert r.success is True
        assert r.identity.allowed_roles == []

    def test_persona_description_preserve_on_none(self, session_tools):
        """persona_description=None preserves existing on update."""
        session_tools.upsert_identity(
            identity_name="ident-1",
            independence_class="main-chain",
            allowed_roles=["proposer"],
            persona_description="original",
        )
        updated = session_tools.upsert_identity(
            identity_name="ident-1",
            independence_class="main-chain",
            allowed_roles=["proposer"],
            # persona_description omitted -> preserve
        )
        assert updated.identity.persona_description == "original"

    def test_upsert_identity_requires_name(self, session_tools):
        """Empty identity_name fails fast (before enum validation)."""
        result = session_tools.upsert_identity(
            identity_name="",
            independence_class="main-chain",
            allowed_roles=["proposer"],
        )
        assert result.success is False

    def test_human_identity_response_omits_embodiment(self, session_tools):
        """ADR-12 §3 case 3: human records must NOT carry the embodiment
        key in their API response (key absent vs None semantics)."""
        result = session_tools.upsert_identity(
            identity_name="human",
            independence_class="human",
            allowed_roles=["human"],
        )
        assert result.success is True
        # The IdentityInfo.to_dict path serializer drops the key for human.
        serialized = result.identity.to_dict()
        assert "embodiment" not in serialized, (
            "human identity response must omit the embodiment key entirely "
            "(case 3 response-side omit); silent regression of this contract "
            "would let humans appear to carry a runtime embodiment they cannot have."
        )

    def test_list_context_authors_joins_identity(self, session_tools, project_tools):
        """list_context_authors attaches the identity record when one exists."""
        self._setup(project_tools, "join_proj")

        # Register identity, then save a session under the same author
        session_tools.upsert_identity(
            identity_name="Heisenberg",
            independence_class="main-chain",
            allowed_roles=["proposer", "reviewer", "implementer"],
            persona_description="Heisenberg",
        )
        session_tools.save_session(
            project="join_proj", summary="design", current_task="T-arch",
            author="Heisenberg",
        )
        # Save a second author with no identity record
        session_tools.save_session(
            project="join_proj", summary="impl", current_task="T-impl",
            author="claude-code",
        )

        result = session_tools.list_context_authors(project="join_proj")
        assert result.success is True

        by_author = {a.author: a for a in result.authors}
        ident_entry = by_author["Heisenberg"]
        assert ident_entry.identity is not None
        assert ident_entry.identity.allowed_roles == ["proposer", "reviewer", "implementer"]
        # ADR-12: embodiment defaults to None on identity records (deprecated).
        assert ident_entry.identity.embodiment is None
        assert ident_entry.identity.independence_class == "main-chain"
        assert ident_entry.identity.persona_description == "Heisenberg"

        no_ident_entry = by_author["claude-code"]
        assert no_ident_entry.identity is None

    def test_identity_is_cross_project(self, session_tools, project_tools):
        """The same identity surfaces under multiple projects."""
        self._setup(project_tools, "cp_a")
        self._setup(project_tools, "cp_b")

        session_tools.upsert_identity(
            identity_name="Heisenberg",
            independence_class="main-chain",
            allowed_roles=["proposer"],
        )
        session_tools.save_session(
            project="cp_a", summary="a", author="Heisenberg",
        )
        session_tools.save_session(
            project="cp_b", summary="b", author="Heisenberg",
        )

        a = session_tools.list_context_authors(project="cp_a").authors[0]
        b = session_tools.list_context_authors(project="cp_b").authors[0]
        assert a.identity is not None and a.identity.allowed_roles == ["proposer"]
        assert b.identity is not None and b.identity.allowed_roles == ["proposer"]
        assert a.identity.independence_class == "main-chain"

    def test_get_identity_returns_registered_record(self, session_tools):
        """get_identity resolves allowed_roles for a registered identity."""
        session_tools.upsert_identity(
            identity_name="Einstein",
            independence_class="independent",
            allowed_roles=["naysayer"],
            persona_description="独立 naysayer",
        )

        result = session_tools.get_identity(identity_name="Einstein")

        assert result.success is True
        assert result.found is True
        assert result.identity is not None
        assert result.identity.allowed_roles == ["naysayer"]
        assert result.identity.independence_class == "independent"

    def test_get_identity_unregistered_is_a_negative_answer_not_a_failure(
        self, session_tools
    ):
        """Missing record -> success=True, found=False.

        The distinction is load-bearing: Magickit's role gate treats
        found=False as "legacy / unregistered -> allow" but must fail
        closed on success=False. If a missing record reported
        success=False, every unregistered author would be blocked.
        """
        result = session_tools.get_identity(identity_name="NoSuchActor")

        assert result.success is True
        assert result.found is False
        assert result.identity is None

    def test_get_identity_requires_name(self, session_tools):
        """Empty identity_name is a failed lookup, not an empty answer."""
        result = session_tools.get_identity(identity_name="")

        assert result.success is False
        assert result.found is False

    def test_get_identity_finds_actor_with_no_session_state(
        self, session_tools, project_tools
    ):
        """The reason this tool exists (msg-017 I-2).

        ``list_context_authors`` enumerates SessionState partitions for one
        project, so an identity that never checkpointed there is absent from
        it. ``get_identity`` must still resolve that actor -- otherwise the
        role gate would silently skip exactly the actor it is meant to stop
        (``Einstein`` has no saved context in ``spirrow-magickit``).
        """
        self._setup(project_tools, "gi_proj")
        session_tools.upsert_identity(
            identity_name="Einstein",
            independence_class="independent",
            allowed_roles=["naysayer"],
        )
        # Someone else has session state in the project; Einstein does not.
        session_tools.save_session(
            project="gi_proj", summary="impl", author="Heisenberg",
        )

        authors = session_tools.list_context_authors(project="gi_proj").authors
        assert "Einstein" not in {a.author for a in authors}, (
            "precondition: the project-scoped listing must NOT surface Einstein"
        )

        direct = session_tools.get_identity(identity_name="Einstein")
        assert direct.found is True
        assert direct.identity.allowed_roles == ["naysayer"]

    def test_get_identity_reads_what_upsert_wrote_under_explicit_user(
        self, session_tools
    ):
        """Read and write must agree on the (user, identity_name) key."""
        session_tools.upsert_identity(
            identity_name="Bohr",
            independence_class="main-chain",
            allowed_roles=["proposer"],
            user="other_user",
        )

        assert session_tools.get_identity(
            identity_name="Bohr", user="other_user"
        ).found is True
        # ...and the default-user lookup must not see another user's record.
        assert session_tools.get_identity(identity_name="Bohr").found is False
