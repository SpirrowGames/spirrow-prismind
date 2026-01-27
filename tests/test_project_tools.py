"""Tests for ProjectTools."""

import pytest


class TestSetupProject:
    """Tests for setup_project method."""

    def test_setup_project_success(self, project_tools, mock_rag_client, mock_memory_client):
        """Test successful project setup."""
        result = project_tools.setup_project(
            project="test_proj",
            name="Test Project",
            spreadsheet_id="sheet123",
            root_folder_id="folder456",
            description="A test project",
            create_sheets=False,
            create_folders=False,
        )

        assert result.success is True
        assert result.project_id == "test_proj"
        assert result.name == "Test Project"
        assert "セットアップしました" in result.message

        # Verify project was saved to RAG
        config_doc = mock_rag_client.get_project_config("test_proj")
        assert config_doc is not None
        assert config_doc.metadata["name"] == "Test Project"

        # Verify current project was set in memory
        current = mock_memory_client.get_current_project("test_user")
        assert current is not None
        assert current.project_id == "test_proj"

    def test_setup_project_duplicate_id(self, project_tools, mock_rag_client):
        """Test setup fails with duplicate project ID."""
        # First setup
        project_tools.setup_project(
            project="dup_proj",
            name="First Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Try duplicate
        result = project_tools.setup_project(
            project="dup_proj",
            name="Second Project",
            spreadsheet_id="sheet2",
            root_folder_id="folder2",
            create_sheets=False,
            create_folders=False,
        )

        assert result.success is False
        assert result.duplicate_id is True
        assert "既に存在します" in result.message

    def test_setup_project_similar_projects_warning(self, project_tools, mock_rag_client):
        """Test setup warns about similar projects."""
        # Setup first project
        project_tools.setup_project(
            project="proj_a",
            name="Game Development Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            description="Game development project description",
            create_sheets=False,
            create_folders=False,
            force=True,
        )

        # Setup similar project without force
        result = project_tools.setup_project(
            project="proj_b",
            name="Game Development",
            spreadsheet_id="sheet2",
            root_folder_id="folder2",
            description="Game development project",
            create_sheets=False,
            create_folders=False,
            force=False,
            similarity_threshold=0.3,  # Low threshold for test
        )

        # Should require confirmation due to similarity
        assert result.success is False
        assert result.requires_confirmation is True or result.duplicate_name != ""

    def test_setup_project_with_force(self, project_tools, mock_rag_client):
        """Test setup proceeds with force flag despite similarities."""
        # Setup first project
        project_tools.setup_project(
            project="proj_c",
            name="API Server Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            description="API server",
            create_sheets=False,
            create_folders=False,
            force=True,
        )

        # Setup similar project with force
        result = project_tools.setup_project(
            project="proj_d",
            name="API Server Project 2",
            spreadsheet_id="sheet2",
            root_folder_id="folder2",
            description="Another API server",
            create_sheets=False,
            create_folders=False,
            force=True,
        )

        assert result.success is True
        assert result.project_id == "proj_d"

    def test_setup_project_duplicate_name_blocked(self, project_tools, mock_rag_client):
        """Test setup fails with duplicate project name even with force=True."""
        # Setup first project
        project_tools.setup_project(
            project="name_proj1",
            name="Duplicate Name Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Try to create project with same name but different ID (should fail)
        result = project_tools.setup_project(
            project="name_proj2",
            name="Duplicate Name Test",  # Same name
            spreadsheet_id="sheet2",
            root_folder_id="folder2",
            create_sheets=False,
            create_folders=False,
            force=True,  # Even with force, duplicate name should be blocked
        )

        assert result.success is False
        assert result.duplicate_name == "name_proj1"
        assert "同名のプロジェクト" in result.message

    def test_setup_project_similar_name_allowed_with_force(self, project_tools, mock_rag_client):
        """Test setup allows similar (but not identical) names with force=True."""
        # Setup first project
        project_tools.setup_project(
            project="similar_proj1",
            name="My Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Create project with similar but different name (should succeed with force)
        result = project_tools.setup_project(
            project="similar_proj2",
            name="My Project 2",  # Similar but not identical
            spreadsheet_id="sheet2",
            root_folder_id="folder2",
            create_sheets=False,
            create_folders=False,
            force=True,
        )

        assert result.success is True
        assert result.project_id == "similar_proj2"


class TestSwitchProject:
    """Tests for switch_project method."""

    def test_switch_project_success(self, project_tools, mock_rag_client, mock_memory_client):
        """Test successful project switch."""
        # Setup a project first
        project_tools.setup_project(
            project="switch_proj",
            name="Switch Test Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Switch to it
        result = project_tools.switch_project("switch_proj")

        assert result.success is True
        assert result.project_id == "switch_proj"
        assert result.name == "Switch Test Project"
        assert "切り替えました" in result.message

        # Verify memory was updated
        current = mock_memory_client.get_current_project("test_user")
        assert current.project_id == "switch_proj"

    def test_switch_project_not_found(self, project_tools):
        """Test switch fails for non-existent project."""
        result = project_tools.switch_project("nonexistent")

        assert result.success is False
        assert "見つかりません" in result.message


class TestListProjects:
    """Tests for list_projects method."""

    def test_list_projects_empty(self, project_tools):
        """Test listing with no projects."""
        result = project_tools.list_projects()

        assert result.success is True
        assert len(result.projects) == 0
        assert result.current_project == ""

    def test_list_projects_multiple(self, project_tools, mock_rag_client):
        """Test listing multiple projects."""
        # Setup projects
        for i in range(3):
            project_tools.setup_project(
                project=f"list_proj_{i}",
                name=f"List Project {i}",
                spreadsheet_id=f"sheet{i}",
                root_folder_id=f"folder{i}",
                create_sheets=False,
                create_folders=False,
                force=True,
            )

        result = project_tools.list_projects()

        assert result.success is True
        assert len(result.projects) == 3
        assert result.current_project == "list_proj_2"  # Last created is current


class TestUpdateProject:
    """Tests for update_project method."""

    def test_update_project_name(self, project_tools, mock_rag_client):
        """Test updating project name."""
        # Setup project
        project_tools.setup_project(
            project="update_proj",
            name="Original Name",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Update name
        result = project_tools.update_project(
            project="update_proj",
            name="Updated Name",
        )

        assert result.success is True
        assert "name" in result.updated_fields
        assert "更新しました" in result.message

        # Verify change
        config = mock_rag_client.get_project_config("update_proj")
        assert config.metadata["name"] == "Updated Name"

    def test_update_project_not_found(self, project_tools):
        """Test update fails for non-existent project."""
        result = project_tools.update_project(
            project="nonexistent",
            name="New Name",
        )

        assert result.success is False
        assert "見つかりません" in result.message

    def test_update_project_no_changes(self, project_tools, mock_rag_client):
        """Test update with no actual changes."""
        # Setup project
        project_tools.setup_project(
            project="no_change_proj",
            name="Same Name",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Update with same values
        result = project_tools.update_project(
            project="no_change_proj",
            name="Same Name",
        )

        assert result.success is True
        assert len(result.updated_fields) == 0
        assert "更新する項目がありません" in result.message


class TestDeleteProject:
    """Tests for delete_project method."""

    def test_delete_project_requires_confirmation(self, project_tools):
        """Test delete requires confirmation."""
        result = project_tools.delete_project("any_proj", confirm=False)

        assert result.success is False
        assert "confirm=True" in result.message

    def test_delete_project_success(self, project_tools, mock_rag_client):
        """Test successful project deletion."""
        # Setup project
        project_tools.setup_project(
            project="delete_proj",
            name="Delete Me",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Delete with confirmation
        result = project_tools.delete_project("delete_proj", confirm=True)

        assert result.success is True
        assert "削除しました" in result.message

        # Verify deleted
        config = mock_rag_client.get_project_config("delete_proj")
        assert config is None

    def test_delete_project_not_found(self, project_tools):
        """Test delete fails for non-existent project."""
        result = project_tools.delete_project("nonexistent", confirm=True)

        assert result.success is False
        assert "見つかりません" in result.message

    def test_delete_project_with_drive_folder(self, project_tools, mock_drive_client):
        """Test delete with Google Drive folder deletion."""
        # Setup project
        project_tools.setup_project(
            project="drive_delete_proj",
            name="Drive Delete Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder123",
            create_sheets=False,
            create_folders=False,
        )

        # Delete with drive folder deletion
        result = project_tools.delete_project(
            "drive_delete_proj",
            confirm=True,
            delete_drive_folder=True,
        )

        assert result.success is True
        assert result.drive_folder_deleted is True
        assert "Driveフォルダも削除" in result.message

        # Verify drive.delete_file was called
        mock_drive_client.delete_file.assert_called_once_with("folder123", permanent=True)

    def test_delete_project_without_drive_folder(self, project_tools, mock_drive_client):
        """Test delete without Google Drive folder deletion."""
        # Setup project
        project_tools.setup_project(
            project="no_drive_delete",
            name="No Drive Delete",
            spreadsheet_id="sheet1",
            root_folder_id="folder456",
            create_sheets=False,
            create_folders=False,
        )

        # Delete without drive folder deletion (default)
        result = project_tools.delete_project("no_drive_delete", confirm=True)

        assert result.success is True
        assert result.drive_folder_deleted is False

        # Verify drive.delete_file was NOT called
        mock_drive_client.delete_file.assert_not_called()


class TestGetProjectConfig:
    """Tests for get_project_config method."""

    def test_get_project_config_by_id(self, project_tools):
        """Test getting config by project ID."""
        # Setup project
        project_tools.setup_project(
            project="config_proj",
            name="Config Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        config = project_tools.get_project_config("config_proj")

        assert config is not None
        assert config.project_id == "config_proj"
        assert config.name == "Config Test"

    def test_get_project_config_current(self, project_tools, mock_memory_client):
        """Test getting config for current project."""
        # Setup and set as current
        project_tools.setup_project(
            project="current_proj",
            name="Current Test",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Get without specifying project
        config = project_tools.get_project_config()

        assert config is not None
        assert config.project_id == "current_proj"

    def test_get_project_config_not_found(self, project_tools):
        """Test getting config for non-existent project."""
        config = project_tools.get_project_config("nonexistent")

        assert config is None
