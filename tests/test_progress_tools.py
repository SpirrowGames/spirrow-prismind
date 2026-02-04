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


class TestGetTask:
    """Tests for get_task method."""

    def test_get_task_no_project(self, progress_tools):
        """Test get_task fails without project."""
        result = progress_tools.get_task(task_id="T01")

        assert result.success is False
        assert "プロジェクトが選択されていません" in result.message

    def test_get_task_not_found(self, progress_tools, mock_sheets_client, project_tools):
        """Test get_task fails when task not found."""
        project_tools.setup_project(
            project="get_notfound",
            name="Get Not Found",
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

        result = progress_tools.get_task(task_id="T99", project="get_notfound")

        assert result.success is False
        assert "見つかりません" in result.message

    def test_get_task_success(self, progress_tools, mock_sheets_client, project_tools):
        """Test successful task retrieval."""
        project_tools.setup_project(
            project="get_success",
            name="Get Success",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考", "優先度", "カテゴリ", "依存タスク"],
                ["Phase 1", "T01", "Task 1", "in_progress", "", "", "Notes", "high", "bug", "T00"],
            ]
        }

        result = progress_tools.get_task(task_id="T01", project="get_success")

        assert result.success is True
        assert result.task is not None
        assert result.task.task_id == "T01"
        assert result.task.name == "Task 1"
        assert result.task.priority == "high"
        assert result.task.category == "bug"
        assert result.task.blocked_by == ["T00"]
        assert result.phase == "Phase 1"

    def test_get_task_ambiguous(self, progress_tools, mock_sheets_client, project_tools):
        """Test get_task fails when task exists in multiple phases without specifying phase."""
        project_tools.setup_project(
            project="get_ambig",
            name="Get Ambiguous",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス"],
                ["Phase 1", "T01", "Task 1", "completed"],
                ["Phase 2", "T01", "Task 1 v2", "not_started"],
            ]
        }

        result = progress_tools.get_task(task_id="T01", project="get_ambig")

        assert result.success is False
        assert "複数のフェーズに存在" in result.message

    def test_get_task_with_phase(self, progress_tools, mock_sheets_client, project_tools):
        """Test get_task succeeds with phase specified for ambiguous task."""
        project_tools.setup_project(
            project="get_phase",
            name="Get Phase",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス"],
                ["Phase 1", "T01", "Task 1", "completed"],
                ["Phase 2", "T01", "Task 1 v2", "not_started"],
            ]
        }

        result = progress_tools.get_task(task_id="T01", phase="Phase 2", project="get_phase")

        assert result.success is True
        assert result.task.name == "Task 1 v2"
        assert result.phase == "Phase 2"


class TestDeleteTask:
    """Tests for delete_task method."""

    def test_delete_task_no_project(self, progress_tools):
        """Test delete_task fails without project."""
        result = progress_tools.delete_task(task_id="T01")

        assert result.success is False
        assert "プロジェクトが選択されていません" in result.message

    def test_delete_task_not_found(self, progress_tools, mock_sheets_client, project_tools):
        """Test delete_task fails when task not found."""
        project_tools.setup_project(
            project="del_notfound",
            name="Delete Not Found",
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

        result = progress_tools.delete_task(task_id="T99", project="del_notfound")

        assert result.success is False
        assert "見つかりません" in result.message

    def test_delete_task_success(self, progress_tools, mock_sheets_client, project_tools):
        """Test successful task deletion."""
        project_tools.setup_project(
            project="del_success",
            name="Delete Success",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考", "優先度", "カテゴリ", "依存タスク"],
                ["Phase 1", "T01", "Task 1", "completed", "", "", "", "", "", ""],
            ]
        }

        result = progress_tools.delete_task(task_id="T01", project="del_success")

        assert result.success is True
        assert result.task_id == "T01"
        assert result.phase == "Phase 1"
        assert "削除しました" in result.message
        mock_sheets_client.update_range.assert_called()

    def test_delete_task_cleans_blocked_by(self, progress_tools, mock_sheets_client, project_tools):
        """Test delete_task cleans up blocked_by references."""
        project_tools.setup_project(
            project="del_deps",
            name="Delete Deps",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考", "優先度", "カテゴリ", "依存タスク"],
                ["Phase 1", "T01", "Task 1", "completed", "", "", "", "", "", ""],
                ["Phase 1", "T02", "Task 2", "not_started", "", "", "", "", "", "T01"],
                ["Phase 1", "T03", "Task 3", "not_started", "", "", "", "", "", "T01,T02"],
            ]
        }

        result = progress_tools.delete_task(task_id="T01", project="del_deps")

        assert result.success is True
        assert "T02" in result.dependent_tasks_updated
        assert "T03" in result.dependent_tasks_updated

    def test_delete_task_ambiguous(self, progress_tools, mock_sheets_client, project_tools):
        """Test delete_task fails when task exists in multiple phases."""
        project_tools.setup_project(
            project="del_ambig",
            name="Delete Ambiguous",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス"],
                ["Phase 1", "T01", "Task 1", "completed"],
                ["Phase 2", "T01", "Task 1 v2", "not_started"],
            ]
        }

        result = progress_tools.delete_task(task_id="T01", project="del_ambig")

        assert result.success is False
        assert "複数のフェーズに存在" in result.message


class TestUpdateTask:
    """Tests for update_task method."""

    def test_update_task_no_project(self, progress_tools):
        """Test update_task fails without project."""
        result = progress_tools.update_task(task_id="T01")

        assert result.success is False
        assert "プロジェクトが選択されていません" in result.message

    def test_update_task_not_found(self, progress_tools, mock_sheets_client, project_tools):
        """Test update_task fails when task not found."""
        project_tools.setup_project(
            project="updt_notfound",
            name="Update Task Not Found",
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

        result = progress_tools.update_task(task_id="T99", project="updt_notfound")

        assert result.success is False
        assert "見つかりません" in result.message

    def test_update_task_invalid_status(self, progress_tools, mock_sheets_client, project_tools):
        """Test update_task fails with invalid status."""
        project_tools.setup_project(
            project="updt_inv_stat",
            name="Update Invalid Status",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = progress_tools.update_task(
            task_id="T01",
            status="invalid_status",
            project="updt_inv_stat",
        )

        assert result.success is False
        assert "無効なステータス" in result.message

    def test_update_task_invalid_priority(self, progress_tools, mock_sheets_client, project_tools):
        """Test update_task fails with invalid priority."""
        project_tools.setup_project(
            project="updt_inv_pri",
            name="Update Invalid Priority",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = progress_tools.update_task(
            task_id="T01",
            priority="invalid_priority",
            project="updt_inv_pri",
        )

        assert result.success is False
        assert "無効な優先度" in result.message

    def test_update_task_name(self, progress_tools, mock_sheets_client, project_tools):
        """Test update_task can update name."""
        project_tools.setup_project(
            project="updt_name",
            name="Update Task Name",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考", "優先度", "カテゴリ", "依存タスク"],
                ["Phase 1", "T01", "Old Name", "not_started", "", "", "", "medium", "", ""],
            ]
        }

        result = progress_tools.update_task(
            task_id="T01",
            name="New Name",
            project="updt_name",
        )

        assert result.success is True
        assert "name" in result.updated_fields
        mock_sheets_client.update_range.assert_called()

    def test_update_task_move_phase(self, progress_tools, mock_sheets_client, project_tools):
        """Test update_task can move task to different phase."""
        project_tools.setup_project(
            project="updt_phase",
            name="Update Task Phase",
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

        result = progress_tools.update_task(
            task_id="T01",
            new_phase="Phase 2",
            project="updt_phase",
        )

        assert result.success is True
        assert result.phase_moved is True
        assert result.old_phase == "Phase 1"
        assert result.new_phase == "Phase 2"
        assert "phase" in result.updated_fields

    def test_update_task_multiple_fields(self, progress_tools, mock_sheets_client, project_tools):
        """Test update_task can update multiple fields at once."""
        project_tools.setup_project(
            project="updt_multi",
            name="Update Multi Fields",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {
            "values": [
                ["フェーズ", "タスクID", "タスク名", "ステータス", "ブロッカー", "完了日", "備考", "優先度", "カテゴリ", "依存タスク"],
                ["Phase 1", "T01", "Old Name", "not_started", "", "", "", "medium", "", ""],
            ]
        }

        result = progress_tools.update_task(
            task_id="T01",
            name="New Name",
            description="New description",
            priority="high",
            category="feature",
            status="in_progress",
            project="updt_multi",
        )

        assert result.success is True
        assert "name" in result.updated_fields
        assert "notes" in result.updated_fields
        assert "priority" in result.updated_fields
        assert "category" in result.updated_fields
        assert "status" in result.updated_fields

    def test_update_task_no_changes(self, progress_tools, mock_sheets_client, project_tools):
        """Test update_task with no changes."""
        project_tools.setup_project(
            project="updt_nochange",
            name="Update No Change",
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

        result = progress_tools.update_task(
            task_id="T01",
            project="updt_nochange",
        )

        assert result.success is True
        assert result.updated_fields == []
        assert "更新するフィールドがありません" in result.message
