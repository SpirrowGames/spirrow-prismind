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
