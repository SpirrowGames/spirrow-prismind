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
