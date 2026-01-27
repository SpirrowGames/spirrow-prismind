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
        assert "プロジェクトが選択されていません" in result.message

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

        # Setup mock - new implementation uses Drive API to create document
        mock_drive_client.create_folder_if_not_exists.return_value = (
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
        assert "作成しました" in result.message
        # Verify the document was created in the correct folder
        mock_drive_client.create_document.assert_called_once_with(
            name="New Document",
            parent_id="design_folder_id",
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
