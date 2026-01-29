"""Tests for ProgressTools."""

import pytest
from datetime import datetime


class TestGetProgress:
    """Tests for get_progress method."""

    def test_get_progress_no_project(self, progress_tools):
        """Test get_progress fails without project."""
        result = progress_tools.get_progress()

        assert result.success is False
        assert "プロジェクトが選択されていません" in result.message

    def test_get_progress_project_not_found(self, progress_tools):
        """Test get_progress fails for non-existent project."""
        result = progress_tools.get_progress(project="nonexistent")

        assert result.success is False
        assert "設定が見つかりません" in result.message

    def test_get_progress_empty_sheet(self, progress_tools, mock_sheets_client, project_tools):
        """Test get_progress with empty sheet."""
        project_tools.setup_project(
            project="empty_prog",
            name="Empty Progress",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {"values": []}

        result = progress_tools.get_progress(project="empty_prog")

        assert result.success is True
        assert result.project == "empty_prog"
        assert len(result.phases) == 0

    def test_get_progress_with_data(self, progress_tools, mock_sheets_client, project_tools):
        """Test get_progress with actual data."""
        project_tools.setup_project(
            project="prog_data",
            name="Progress Data",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Mock sheet data
        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考"],
                ["Phase 1", "T01", "Task 1", "completed", "", "2024-01-15", ""],
                ["Phase 1", "T02", "Task 2", "in_progress", "", "", ""],
                ["Phase 2", "T01", "Task A", "not_started", "", "", ""],
            ]
        }

        result = progress_tools.get_progress(project="prog_data")

        assert result.success is True
        assert len(result.phases) == 2
        assert result.current_phase == "Phase 1"  # First in_progress

        # Check Phase 1
        phase1 = next(p for p in result.phases if p.phase == "Phase 1")
        assert phase1.status == "in_progress"
        assert len(phase1.tasks) == 2

    def test_get_progress_filter_by_phase(self, progress_tools, mock_sheets_client, project_tools):
        """Test get_progress filtered by phase."""
        project_tools.setup_project(
            project="prog_filter",
            name="Progress Filter",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス"],
                ["Phase 1", "T01", "Task 1", "completed"],
                ["Phase 2", "T01", "Task A", "not_started"],
                ["Phase 2", "T02", "Task B", "not_started"],
            ]
        }

        result = progress_tools.get_progress(project="prog_filter", phase="Phase 2")

        assert result.success is True
        assert len(result.phases) == 1
        assert result.phases[0].phase == "Phase 2"
        assert len(result.phases[0].tasks) == 2

    def test_get_progress_backward_compatible_old_sheet(self, progress_tools, mock_sheets_client, project_tools):
        """Test get_progress works with old sheets (A:G only, no extended columns)."""
        project_tools.setup_project(
            project="prog_compat",
            name="Progress Compat",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Old sheet format without H:J columns
        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考"],
                ["Phase 1", "T01", "Task 1", "in_progress", "", "", "Some notes"],
            ]
        }

        result = progress_tools.get_progress(project="prog_compat")

        assert result.success is True
        assert len(result.phases) == 1
        task = result.phases[0].tasks[0]
        # Verify default values for missing extended fields
        assert task.priority == "medium"
        assert task.category == ""
        assert task.blocked_by == []

    def test_get_progress_with_extended_fields(self, progress_tools, mock_sheets_client, project_tools):
        """Test get_progress with v2 extended columns."""
        project_tools.setup_project(
            project="prog_v2",
            name="Progress V2",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考", "優先度", "カテゴリ", "依存タスク"],
                ["Phase 1", "T01", "Task 1", "in_progress", "", "", "", "high", "bug", "T00,T02"],
            ]
        }

        result = progress_tools.get_progress(project="prog_v2")

        assert result.success is True
        task = result.phases[0].tasks[0]
        assert task.priority == "high"
        assert task.category == "bug"
        assert task.blocked_by == ["T00", "T02"]


class TestUpdateTaskStatus:
    """Tests for update_task_status method."""

    def test_update_task_status_invalid_status(self, progress_tools):
        """Test update fails with invalid status."""
        result = progress_tools.update_task_status(
            task_id="T01",
            status="invalid_status",
        )

        assert result.success is False
        assert "無効なステータス" in result.message

    def test_update_task_status_no_project(self, progress_tools):
        """Test update fails without project."""
        result = progress_tools.update_task_status(
            task_id="T01",
            status="completed",
        )

        assert result.success is False
        assert "プロジェクトが選択されていません" in result.message

    def test_update_task_status_task_not_found(self, progress_tools, mock_sheets_client, project_tools):
        """Test update fails when task not found."""
        project_tools.setup_project(
            project="upd_notfound",
            name="Update Not Found",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス"],
                ["Phase 1", "T01", "Task 1", "not_started"],
            ]
        }

        result = progress_tools.update_task_status(
            task_id="T99",
            status="completed",
            project="upd_notfound",
        )

        assert result.success is False
        assert "見つかりません" in result.message

    def test_update_task_status_success(self, progress_tools, mock_sheets_client, project_tools):
        """Test successful status update."""
        project_tools.setup_project(
            project="upd_success",
            name="Update Success",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考"],
                ["Phase 1", "T01", "Task 1", "not_started", "", "", ""],
            ]
        }

        result = progress_tools.update_task_status(
            task_id="T01",
            status="in_progress",
            project="upd_success",
        )

        assert result.success is True
        assert result.task_id == "T01"
        assert "status" in result.updated_fields
        mock_sheets_client.update_range.assert_called_once()

    def test_update_task_status_completed_sets_date(self, progress_tools, mock_sheets_client, project_tools):
        """Test completing task sets completed_at date."""
        project_tools.setup_project(
            project="upd_complete",
            name="Update Complete",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考"],
                ["Phase 1", "T01", "Task 1", "in_progress", "", "", ""],
            ]
        }

        result = progress_tools.update_task_status(
            task_id="T01",
            status="completed",
            project="upd_complete",
        )

        assert result.success is True
        assert "completed_at" in result.updated_fields

    def test_update_task_status_with_blockers(self, progress_tools, mock_sheets_client, project_tools):
        """Test update with blockers."""
        project_tools.setup_project(
            project="upd_block",
            name="Update Blockers",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考"],
                ["Phase 1", "T01", "Task 1", "in_progress", "", "", ""],
            ]
        }

        result = progress_tools.update_task_status(
            task_id="T01",
            status="blocked",
            blockers=["Waiting for API", "Need review"],
            project="upd_block",
        )

        assert result.success is True
        assert "blockers" in result.updated_fields

    def test_update_task_status_with_extended_fields(self, progress_tools, mock_sheets_client, project_tools):
        """Test update with v2 extended fields (priority, category, blocked_by)."""
        project_tools.setup_project(
            project="upd_extended",
            name="Update Extended",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考", "優先度", "カテゴリ", "依存タスク"],
                ["Phase 1", "T01", "Task 1", "not_started", "", "", "", "medium", "", ""],
            ]
        }

        result = progress_tools.update_task_status(
            task_id="T01",
            status="in_progress",
            priority="high",
            category="bug",
            blocked_by=["T00", "T02"],
            project="upd_extended",
        )

        assert result.success is True
        assert "status" in result.updated_fields
        assert "priority" in result.updated_fields
        assert "category" in result.updated_fields
        assert "blocked_by" in result.updated_fields

    def test_update_task_status_invalid_priority_ignored(self, progress_tools, mock_sheets_client, project_tools):
        """Test that invalid priority is ignored."""
        project_tools.setup_project(
            project="upd_pri_inv",
            name="Update Priority Invalid",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考", "優先度", "カテゴリ", "依存タスク"],
                ["Phase 1", "T01", "Task 1", "not_started", "", "", "", "medium", "", ""],
            ]
        }

        result = progress_tools.update_task_status(
            task_id="T01",
            status="in_progress",
            priority="invalid",  # Invalid priority should be ignored
            project="upd_pri_inv",
        )

        assert result.success is True
        assert "priority" not in result.updated_fields  # Invalid priority not updated


class TestAddTask:
    """Tests for add_task method."""

    def test_add_task_no_project(self, progress_tools):
        """Test add_task fails without project."""
        result = progress_tools.add_task(
            phase="Phase 1",
            task_id="T01",
            name="New Task",
        )

        assert result.success is False
        assert "プロジェクトが選択されていません" in result.message

    def test_add_task_success(self, progress_tools, mock_sheets_client, project_tools):
        """Test successful task addition."""
        project_tools.setup_project(
            project="add_task",
            name="Add Task",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = progress_tools.add_task(
            phase="Phase 1",
            task_id="T01",
            name="New Task",
            description="Task description",
            project="add_task",
        )

        assert result.success is True
        assert result.task_id == "T01"
        assert "追加しました" in result.message
        mock_sheets_client.append_rows.assert_called_once()

    def test_add_task_with_extended_fields(self, progress_tools, mock_sheets_client, project_tools):
        """Test task addition with v2 extended fields."""
        project_tools.setup_project(
            project="add_task_v2",
            name="Add Task V2",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = progress_tools.add_task(
            phase="Phase 1",
            task_id="T01",
            name="New Feature Task",
            description="Implement new feature",
            priority="high",
            category="feature",
            blocked_by=["T00"],
            project="add_task_v2",
        )

        assert result.success is True
        assert result.task_id == "T01"

        # Verify the row data passed to append_rows
        call_args = mock_sheets_client.append_rows.call_args
        row = call_args.kwargs["values"][0]
        assert row[0] == "Phase 1"  # phase
        assert row[1] == "T01"  # task_id
        assert row[2] == "New Feature Task"  # name
        assert row[3] == "not_started"  # status
        assert row[7] == "high"  # priority
        assert row[8] == "feature"  # category
        assert row[9] == "T00"  # blocked_by

    def test_add_task_invalid_priority_defaults_to_medium(self, progress_tools, mock_sheets_client, project_tools):
        """Test that invalid priority defaults to medium."""
        project_tools.setup_project(
            project="add_task_pri",
            name="Add Task Priority",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = progress_tools.add_task(
            phase="Phase 1",
            task_id="T01",
            name="Task",
            priority="invalid",
            project="add_task_pri",
        )

        assert result.success is True
        call_args = mock_sheets_client.append_rows.call_args
        row = call_args.kwargs["values"][0]
        assert row[7] == "medium"  # priority defaults to medium


class TestConvenienceMethods:
    """Tests for convenience methods."""

    def test_complete_task(self, progress_tools, mock_sheets_client, project_tools):
        """Test complete_task convenience method."""
        project_tools.setup_project(
            project="conv_complete",
            name="Conv Complete",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考"],
                ["Phase 1", "T01", "Task 1", "in_progress", "", "", ""],
            ]
        }

        result = progress_tools.complete_task(
            task_id="T01",
            notes="Completed successfully",
            project="conv_complete",
        )

        assert result.success is True

    def test_start_task(self, progress_tools, mock_sheets_client, project_tools):
        """Test start_task convenience method."""
        project_tools.setup_project(
            project="conv_start",
            name="Conv Start",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考"],
                ["Phase 1", "T01", "Task 1", "not_started", "", "", ""],
            ]
        }

        result = progress_tools.start_task(
            task_id="T01",
            project="conv_start",
        )

        assert result.success is True

    def test_block_task(self, progress_tools, mock_sheets_client, project_tools):
        """Test block_task convenience method."""
        project_tools.setup_project(
            project="conv_block",
            name="Conv Block",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考"],
                ["Phase 1", "T01", "Task 1", "in_progress", "", "", ""],
            ]
        }

        result = progress_tools.block_task(
            task_id="T01",
            blockers=["External dependency"],
            project="conv_block",
        )

        assert result.success is True
        assert "blockers" in result.updated_fields
