"""Tests for DocumentTools."""

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass


@dataclass
class MockDocInfo:
    """Mock document info from Google Docs."""
    doc_id: str
    title: str
    url: str
    body_text: str = ""


@dataclass
class MockFileInfo:
    """Mock file info from Google Drive."""
    file_id: str
    name: str
    mime_type: str = "application/vnd.google-apps.document"
    parents: list = None
    web_view_link: str = ""
    created_time: str = ""
    modified_time: str = ""

    def __post_init__(self):
        if self.parents is None:
            self.parents = []


class TestGetDocument:
    """Tests for get_document method."""

    def test_get_document_no_query_or_id(self, document_tools):
        """Test get_document fails without query or doc_id."""
        result = document_tools.get_document()

        assert result.found is False
        assert "検索クエリまたはドキュメントID" in result.message

    def test_get_document_by_id(self, document_tools, mock_docs_client):
        """Test get_document by direct ID."""
        # Setup mock
        mock_docs_client.get_document.return_value = MockDocInfo(
            doc_id="doc123",
            title="Test Document",
            url="https://docs.google.com/doc123",
            body_text="Document content here",
        )

        result = document_tools.get_document(doc_id="doc123")

        assert result.found is True
        assert result.document is not None
        assert result.document.doc_id == "doc123"
        assert result.document.name == "Test Document"
        mock_docs_client.get_document.assert_called_once_with("doc123")

    def test_get_document_by_query_single_result(
        self, document_tools, mock_rag_client, mock_docs_client, project_tools
    ):
        """Test get_document by query with single result."""
        # Setup project
        project_tools.setup_project(
            project="doc_proj",
            name="Doc Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add catalog entry
        mock_rag_client.add_catalog_entry(
            doc_id="found_doc",
            name="Found Document",
            doc_type="設計書",
            project="doc_proj",
            phase_task="P1-T01",
            metadata={"source": "Google Docs"},
        )

        # Setup docs client
        mock_docs_client.get_document.return_value = MockDocInfo(
            doc_id="found_doc",
            title="Found Document",
            url="https://docs.google.com/found_doc",
            body_text="Content",
        )

        result = document_tools.get_document(query="Found Document")

        assert result.found is True
        assert result.document.doc_id == "found_doc"

    def test_get_document_by_query_multiple_results(
        self, document_tools, mock_rag_client, project_tools
    ):
        """Test get_document by query with multiple results."""
        # Setup project
        project_tools.setup_project(
            project="multi_proj",
            name="Multi Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add multiple catalog entries
        for i in range(3):
            mock_rag_client.add_catalog_entry(
                doc_id=f"multi_doc_{i}",
                name=f"Design Document {i}",
                doc_type="設計書",
                project="multi_proj",
                phase_task=f"P1-T0{i}",
                metadata={"source": "Google Docs"},
            )

        result = document_tools.get_document(query="Design Document")

        assert result.found is False
        assert len(result.candidates) >= 2
        assert "候補" in result.message

    def test_get_document_not_found(self, document_tools, project_tools):
        """Test get_document when nothing found."""
        project_tools.setup_project(
            project="empty_proj",
            name="Empty Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = document_tools.get_document(query="Nonexistent")

        assert result.found is False
        assert "見つかりません" in result.message


class TestCreateDocument:
    """Tests for create_document method."""

    def test_create_document_no_project(self, document_tools):
        """Test create_document fails without active project."""
        result = document_tools.create_document(
            name="New Doc",
            doc_type="設計書",
            content="Content",
            phase_task="P1-T01",
        )

        assert result.success is False
        assert result.doc_type == "設計書"
        assert result.unknown_doc_type is False
        assert "プロジェクトが選択されていません" in result.message

    def test_create_document_unknown_doc_type(
        self, document_tools, project_tools
    ):
        """Test create_document fails with unknown doc_type."""
        # Setup project
        project_tools.setup_project(
            project="unknown_type_proj",
            name="Unknown Type Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = document_tools.create_document(
            name="議事録テスト",
            doc_type="議事録",  # Not registered
            content="会議の内容",
            phase_task="P1-T01",
        )

        assert result.success is False
        assert result.unknown_doc_type is True
        assert result.doc_type == "議事録"
        assert result.doc_id == ""
        assert "登録されていません" in result.message
        assert "register_document_type" in result.message

    def test_create_document_success(
        self, document_tools, mock_docs_client, mock_drive_client, project_tools
    ):
        """Test successful document creation."""
        # Setup project
        project_tools.setup_project(
            project="create_proj",
            name="Create Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Setup mock - new implementation uses ensure_folder_path
        mock_drive_client.ensure_folder_path.return_value = (
            MockFileInfo(
                file_id="design_folder_id",
                name="設計書",
            ),
            False,  # created=False (folder already exists)
        )
        mock_drive_client.create_document.return_value = MockFileInfo(
            file_id="new_doc_id",
            name="New Document",
            web_view_link="https://docs.google.com/document/d/new_doc_id/edit",
        )
        # Mock for insert_text and batchUpdate
        mock_docs_client.insert_text.return_value = True
        mock_docs_client.service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

        result = document_tools.create_document(
            name="New Document",
            doc_type="設計書",
            content="# New Document\n\nContent here",
            phase_task="P1-T01",
            feature="Feature A",
            keywords=["keyword1", "keyword2"],
        )

        assert result.success is True
        assert result.doc_id == "new_doc_id"
        assert result.name == "New Document"
        assert result.doc_type == "設計書"
        assert result.unknown_doc_type is False
        assert "作成しました" in result.message
        # Verify ensure_folder_path was called
        mock_drive_client.ensure_folder_path.assert_called_once_with(
            path="設計書",
            parent_id="folder1",
        )
        # Verify the document was created in the correct folder
        mock_drive_client.create_document.assert_called_once_with(
            name="New Document",
            parent_id="design_folder_id",
        )

    def test_create_document_with_nested_folder_path(
        self, document_tools, mock_docs_client, mock_drive_client, mock_rag_client, project_tools
    ):
        """Test document creation with nested folder path like '設計/詳細設計'."""
        from spirrow_prismind.tools.project_tools import ProjectTools

        # Setup project with custom document type having nested folder
        result = project_tools.setup_project(
            project="nested_proj",
            name="Nested Folder Project",
            spreadsheet_id="sheet1",
            root_folder_id="root_folder",
            create_sheets=False,
            create_folders=False,
        )
        assert result.success is True, f"setup_project failed: {result.message}"

        # Add custom document type directly to fallback storage
        # The project should now exist in fallback storage
        nested_doc_type = {
            "type_id": "detailed_design",
            "name": "詳細設計書",
            "folder_name": "設計/詳細設計",
            "template_doc_id": "",
            "description": "詳細設計ドキュメント",
            "fields": [],
            "is_builtin": False,
        }

        # Get the project from fallback storage and update document_types
        if "nested_proj" in ProjectTools._fallback_projects:
            ProjectTools._fallback_projects["nested_proj"]["document_types"] = [nested_doc_type]
        else:
            # Fallback: add the project manually if setup didn't save to fallback
            ProjectTools._fallback_projects["nested_proj"] = {
                "project_id": "nested_proj",
                "name": "Nested Folder Project",
                "spreadsheet_id": "sheet1",
                "root_folder_id": "root_folder",
                "document_types": [nested_doc_type],
            }
            ProjectTools._fallback_current_project["test_user"] = "nested_proj"

        # Setup mock for nested folder creation
        mock_drive_client.ensure_folder_path.return_value = (
            MockFileInfo(
                file_id="nested_folder_id",
                name="詳細設計",
            ),
            True,  # created=True (folders were created)
        )
        mock_drive_client.create_document.return_value = MockFileInfo(
            file_id="nested_doc_id",
            name="Detailed Design Doc",
            web_view_link="https://docs.google.com/document/d/nested_doc_id/edit",
        )
        mock_docs_client.insert_text.return_value = True
        mock_docs_client.service.documents.return_value.batchUpdate.return_value.execute.return_value = {}

        result = document_tools.create_document(
            name="Detailed Design Doc",
            doc_type="詳細設計書",
            content="詳細設計の内容",
            phase_task="P2-T01",
        )

        assert result.success is True
        assert result.doc_id == "nested_doc_id"
        assert result.doc_type == "詳細設計書"
        # Verify ensure_folder_path was called with nested path
        mock_drive_client.ensure_folder_path.assert_called_with(
            path="設計/詳細設計",
            parent_id="root_folder",
        )


class TestUpdateDocument:
    """Tests for update_document method."""

    def test_update_document_content(
        self, document_tools, mock_docs_client, mock_rag_client, project_tools
    ):
        """Test updating document content."""
        # Setup project and catalog entry
        project_tools.setup_project(
            project="update_proj",
            name="Update Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_rag_client.add_catalog_entry(
            doc_id="update_doc",
            name="Update Doc",
            doc_type="設計書",
            project="update_proj",
            phase_task="P1-T01",
            metadata={},
        )

        result = document_tools.update_document(
            doc_id="update_doc",
            content="New content",
            append=False,
        )

        assert result.success is True
        assert "content" in result.updated_fields
        mock_docs_client.replace_all_text.assert_called_once()

    def test_update_document_append(
        self, document_tools, mock_docs_client, mock_rag_client, project_tools
    ):
        """Test appending to document content."""
        project_tools.setup_project(
            project="append_proj",
            name="Append Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_rag_client.add_catalog_entry(
            doc_id="append_doc",
            name="Append Doc",
            doc_type="設計書",
            project="append_proj",
            phase_task="P1-T01",
            metadata={},
        )

        result = document_tools.update_document(
            doc_id="append_doc",
            content="Appended content",
            append=True,
        )

        assert result.success is True
        mock_docs_client.append_text.assert_called_once()


class TestGenerateKeywords:
    """Tests for _generate_keywords method."""

    def test_generate_keywords_from_name_and_content(self, document_tools):
        """Test keyword generation."""
        keywords = document_tools._generate_keywords(
            name="API Design Document",
            content="# Authentication\n\n## OAuth2 Flow\n\nImplementation details",
            feature="AuthFeature",
        )

        assert "API" in keywords
        assert "Design" in keywords
        assert "Document" in keywords
        assert "AuthFeature" in keywords
        assert "Authentication" in keywords
        assert "OAuth2" in keywords

    def test_generate_keywords_empty_content(self, document_tools):
        """Test keyword generation with empty content."""
        keywords = document_tools._generate_keywords(
            name="Simple Doc",
            content="",
            feature=None,
        )

        assert "Simple" in keywords
        assert "Doc" in keywords

    def test_generate_keywords_deduplication(self, document_tools):
        """Test keywords are deduplicated."""
        keywords = document_tools._generate_keywords(
            name="Test Test Test",
            content="# Test\n## Test",
            feature="Test",
        )

        # Should only have one "Test" despite appearing multiple times
        test_count = sum(1 for k in keywords if k.lower() == "test")
        assert test_count == 1


class TestDeleteDocument:
    """Tests for delete_document method."""

    def test_delete_document_not_found(self, document_tools, project_tools):
        """Test delete_document fails when document not found."""
        project_tools.setup_project(
            project="delete_proj",
            name="Delete Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = document_tools.delete_document(
            doc_id="nonexistent_doc",
            project="delete_proj",
        )

        assert result.success is False
        assert "見つかりません" in result.message

    def test_delete_document_wrong_project(
        self, document_tools, mock_rag_client, project_tools
    ):
        """Test delete_document fails when project doesn't match."""
        # Setup project
        project_tools.setup_project(
            project="project_a",
            name="Project A",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add catalog entry for a different project
        mock_rag_client.add_catalog_entry(
            doc_id="doc_in_b",
            name="Doc in B",
            doc_type="設計書",
            project="project_b",
            phase_task="P1-T01",
            metadata={},
        )

        # Try to delete with wrong project
        result = document_tools.delete_document(
            doc_id="doc_in_b",
            project="project_a",  # Wrong project
        )

        assert result.success is False
        assert "見つかりません" in result.message

    def test_delete_document_success(
        self, document_tools, mock_rag_client, mock_sheets_client, project_tools
    ):
        """Test successful document deletion."""
        # Setup project
        project_tools.setup_project(
            project="delete_success_proj",
            name="Delete Success Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add catalog entry
        mock_rag_client.add_catalog_entry(
            doc_id="delete_me",
            name="Delete Me",
            doc_type="設計書",
            project="delete_success_proj",
            phase_task="P1-T01",
            metadata={"source": "Google Docs"},
        )

        # Mock sheets operations
        mock_sheets_client.find_row_by_value.return_value = 5
        mock_sheets_client.delete_row.return_value = True

        result = document_tools.delete_document(
            doc_id="delete_me",
            project="delete_success_proj",
        )

        assert result.success is True
        assert result.catalog_deleted is True
        assert "削除しました" in result.message

    def test_delete_document_with_drive_file(
        self, document_tools, mock_rag_client, mock_drive_client, project_tools
    ):
        """Test document deletion including Drive file."""
        # Setup project
        project_tools.setup_project(
            project="drive_delete_proj",
            name="Drive Delete Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add catalog entry
        mock_rag_client.add_catalog_entry(
            doc_id="delete_with_drive",
            name="Delete With Drive",
            doc_type="設計書",
            project="drive_delete_proj",
            phase_task="P1-T01",
            metadata={},
        )

        # Mock Drive deletion
        mock_drive_client.delete_file.return_value = True

        result = document_tools.delete_document(
            doc_id="delete_with_drive",
            project="drive_delete_proj",
            delete_drive_file=True,
            soft_delete=False,
        )

        assert result.success is True
        assert result.drive_file_deleted is True
        mock_drive_client.delete_file.assert_called_once_with(
            "delete_with_drive", permanent=True
        )


class TestListDocuments:
    """Tests for list_documents method."""

    def test_list_documents_no_project(self, document_tools):
        """Test list_documents fails without project."""
        result = document_tools.list_documents()

        assert result.success is False
        assert "プロジェクトが選択されていません" in result.message

    def test_list_documents_empty(self, document_tools, project_tools):
        """Test list_documents returns empty when no documents."""
        project_tools.setup_project(
            project="empty_list_proj",
            name="Empty List Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = document_tools.list_documents()

        assert result.success is True
        assert len(result.documents) == 0
        assert result.total_count == 0

    def test_list_documents_with_filter(
        self, document_tools, mock_rag_client, project_tools
    ):
        """Test list_documents with doc_type filter."""
        # Setup project
        project_tools.setup_project(
            project="filter_proj",
            name="Filter Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add multiple catalog entries
        mock_rag_client.add_catalog_entry(
            doc_id="design_doc",
            name="Design Doc",
            doc_type="設計書",
            project="filter_proj",
            phase_task="P1-T01",
            metadata={"source": "Google Docs"},
        )
        mock_rag_client.add_catalog_entry(
            doc_id="procedure_doc",
            name="Procedure Doc",
            doc_type="実装手順書",
            project="filter_proj",
            phase_task="P2-T01",
            metadata={"source": "Google Docs"},
        )

        result = document_tools.list_documents(doc_type="設計書")

        assert result.success is True
        assert result.total_count == 1
        assert result.documents[0].doc_type == "設計書"

    def test_list_documents_pagination(
        self, document_tools, mock_rag_client, project_tools
    ):
        """Test list_documents pagination."""
        # Setup project
        project_tools.setup_project(
            project="pagination_proj",
            name="Pagination Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add multiple catalog entries
        for i in range(5):
            mock_rag_client.add_catalog_entry(
                doc_id=f"doc_{i}",
                name=f"Document {i}",
                doc_type="設計書",
                project="pagination_proj",
                phase_task=f"P1-T0{i}",
                metadata={"source": "Google Docs"},
            )

        # Test limit
        result = document_tools.list_documents(limit=2, offset=0)
        assert result.success is True
        assert len(result.documents) == 2
        assert result.total_count == 5

        # Test offset
        result2 = document_tools.list_documents(limit=2, offset=2)
        assert result2.success is True
        assert len(result2.documents) == 2
        assert result2.offset == 2


class TestUpdateDocumentExtended:
    """Tests for update_document with extended fields."""

    def test_update_document_doc_type_change(
        self, document_tools, mock_rag_client, mock_drive_client, project_tools
    ):
        """Test updating document with doc_type change moves file."""
        # Setup project
        project_tools.setup_project(
            project="update_type_proj",
            name="Update Type Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add catalog entry
        mock_rag_client.add_catalog_entry(
            doc_id="change_type_doc",
            name="Change Type Doc",
            doc_type="設計書",
            project="update_type_proj",
            phase_task="P1-T01",
            metadata={"source": "Google Docs"},
        )

        # Mock Drive operations
        mock_drive_client.ensure_folder_path.return_value = (
            MockFileInfo(file_id="procedure_folder", name="実装手順書"),
            False,
        )
        mock_drive_client.move_file.return_value = MockFileInfo(
            file_id="change_type_doc",
            name="Change Type Doc",
        )

        result = document_tools.update_document(
            doc_id="change_type_doc",
            metadata={"doc_type": "実装手順書"},
        )

        assert result.success is True
        assert "doc_type" in result.updated_fields
        mock_drive_client.move_file.assert_called_once()

    def test_update_document_phase_task_change(
        self, document_tools, mock_rag_client, mock_sheets_client, project_tools
    ):
        """Test updating document with phase_task change."""
        # Setup project
        project_tools.setup_project(
            project="update_phase_proj",
            name="Update Phase Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add catalog entry
        mock_rag_client.add_catalog_entry(
            doc_id="change_phase_doc",
            name="Change Phase Doc",
            doc_type="設計書",
            project="update_phase_proj",
            phase_task="P1-T01",
            metadata={"source": "Google Docs"},
        )

        # Mock Sheets operations
        mock_sheets_client.find_row_by_value.return_value = 3
        mock_sheets_client.get_sheet_values.return_value = [[
            "Change Phase Doc", "Google Docs", "change_phase_doc",
            "設計書", "update_phase_proj", "P1-T01", "", "", "", "", "", "", ""
        ]]
        mock_sheets_client.update_row.return_value = {}

        result = document_tools.update_document(
            doc_id="change_phase_doc",
            metadata={"phase_task": "P2-T01"},
        )

        assert result.success is True
        assert "phase_task" in result.updated_fields
