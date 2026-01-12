"""Tests for CatalogTools."""

import pytest
from datetime import datetime


class TestSearchCatalog:
    """Tests for search_catalog method."""

    def test_search_catalog_empty(self, catalog_tools, project_tools):
        """Test search on empty catalog."""
        project_tools.setup_project(
            project="empty_cat",
            name="Empty Catalog",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = catalog_tools.search_catalog(query="anything")

        assert result.success is True
        assert result.total_count == 0
        assert len(result.documents) == 0

    def test_search_catalog_by_query(self, catalog_tools, mock_rag_client, project_tools):
        """Test search catalog by query."""
        project_tools.setup_project(
            project="search_proj",
            name="Search Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add catalog entries
        mock_rag_client.add_catalog_entry(
            doc_id="design1",
            name="API Design Document",
            doc_type="設計書",
            project="search_proj",
            phase_task="P1-T01",
            metadata={"feature": "API", "status": "active"},
        )
        mock_rag_client.add_catalog_entry(
            doc_id="impl1",
            name="Implementation Guide",
            doc_type="実装手順書",
            project="search_proj",
            phase_task="P1-T02",
            metadata={"feature": "API", "status": "active"},
        )

        result = catalog_tools.search_catalog(query="API")

        assert result.success is True
        assert result.total_count >= 1

    def test_search_catalog_by_doc_type(self, catalog_tools, mock_rag_client, project_tools):
        """Test search catalog filtered by doc_type."""
        project_tools.setup_project(
            project="type_proj",
            name="Type Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_rag_client.add_catalog_entry(
            doc_id="design2",
            name="Design Doc",
            doc_type="設計書",
            project="type_proj",
            phase_task="P1-T01",
            metadata={"status": "active"},
        )
        mock_rag_client.add_catalog_entry(
            doc_id="impl2",
            name="Impl Doc",
            doc_type="実装手順書",
            project="type_proj",
            phase_task="P1-T01",
            metadata={"status": "active"},
        )

        result = catalog_tools.search_catalog(doc_type="設計書")

        assert result.success is True
        for doc in result.documents:
            assert doc.doc_type == "設計書"

    def test_search_catalog_by_phase_task(self, catalog_tools, mock_rag_client, project_tools):
        """Test search catalog filtered by phase_task."""
        project_tools.setup_project(
            project="phase_proj",
            name="Phase Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_rag_client.add_catalog_entry(
            doc_id="p1t1",
            name="Phase 1 Task 1",
            doc_type="設計書",
            project="phase_proj",
            phase_task="P1-T01",
            metadata={"status": "active"},
        )
        mock_rag_client.add_catalog_entry(
            doc_id="p2t1",
            name="Phase 2 Task 1",
            doc_type="設計書",
            project="phase_proj",
            phase_task="P2-T01",
            metadata={"status": "active"},
        )

        result = catalog_tools.search_catalog(phase_task="P1-T01")

        assert result.success is True
        for doc in result.documents:
            assert doc.phase_task == "P1-T01"

    def test_search_catalog_filter_by_status(self, catalog_tools, mock_rag_client, project_tools):
        """Test search catalog respects status filter."""
        project_tools.setup_project(
            project="status_proj",
            name="Status Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_rag_client.add_catalog_entry(
            doc_id="active_doc",
            name="Active Document",
            doc_type="設計書",
            project="status_proj",
            phase_task="P1-T01",
            metadata={"status": "active"},
        )
        mock_rag_client.add_catalog_entry(
            doc_id="archived_doc",
            name="Archived Document",
            doc_type="設計書",
            project="status_proj",
            phase_task="P1-T02",
            metadata={"status": "archived"},
        )

        # Search only active
        result = catalog_tools.search_catalog(status="active")

        assert result.success is True
        for doc in result.documents:
            # All should be from status_proj and active
            if doc.project == "status_proj":
                assert doc.doc_id == "active_doc"


class TestSyncCatalog:
    """Tests for sync_catalog method."""

    def test_sync_catalog_no_project(self, catalog_tools):
        """Test sync fails without project."""
        result = catalog_tools.sync_catalog()

        assert result.success is False
        assert "プロジェクトが選択されていません" in result.message

    def test_sync_catalog_project_not_found(self, catalog_tools):
        """Test sync fails for non-existent project."""
        result = catalog_tools.sync_catalog(project="nonexistent")

        assert result.success is False
        assert "設定が見つかりません" in result.message

    def test_sync_catalog_empty_sheet(self, catalog_tools, mock_sheets_client, project_tools):
        """Test sync with empty sheet."""
        project_tools.setup_project(
            project="sync_empty",
            name="Sync Empty",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_sheets_client.read_range.return_value = {"values": []}

        result = catalog_tools.sync_catalog(project="sync_empty")

        assert result.success is True
        assert result.synced_count == 0

    def test_sync_catalog_with_data(self, catalog_tools, mock_sheets_client, mock_rag_client, project_tools):
        """Test sync with actual data."""
        project_tools.setup_project(
            project="sync_data",
            name="Sync Data",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Mock sheet data
        mock_sheets_client.read_range.return_value = {
            "values": [
                ["ドキュメント名", "保存先", "ID", "種別", "プロジェクト", "フェーズタスク"],  # Header
                ["Doc 1", "Google Docs", "doc1", "設計書", "sync_data", "P1-T01"],
                ["Doc 2", "Google Docs", "doc2", "実装手順書", "sync_data", "P1-T02"],
            ]
        }

        result = catalog_tools.sync_catalog(project="sync_data")

        assert result.success is True
        assert result.synced_count == 2


class TestGetDocumentByPhaseTask:
    """Tests for get_document_by_phase_task method."""

    def test_get_document_by_phase_task(self, catalog_tools, mock_rag_client, project_tools):
        """Test getting documents by phase_task."""
        project_tools.setup_project(
            project="pt_proj",
            name="PT Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_rag_client.add_catalog_entry(
            doc_id="pt_doc1",
            name="PT Doc 1",
            doc_type="設計書",
            project="pt_proj",
            phase_task="P3-T05",
            metadata={"status": "active"},
        )

        documents = catalog_tools.get_document_by_phase_task("P3-T05")

        assert len(documents) >= 1
        assert all(d.phase_task == "P3-T05" for d in documents)

    def test_get_document_by_phase_task_with_type(self, catalog_tools, mock_rag_client, project_tools):
        """Test getting documents by phase_task and type."""
        project_tools.setup_project(
            project="ptt_proj",
            name="PTT Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_rag_client.add_catalog_entry(
            doc_id="ptt_design",
            name="Design Doc",
            doc_type="設計書",
            project="ptt_proj",
            phase_task="P4-T01",
            metadata={"status": "active"},
        )
        mock_rag_client.add_catalog_entry(
            doc_id="ptt_impl",
            name="Impl Doc",
            doc_type="実装手順書",
            project="ptt_proj",
            phase_task="P4-T01",
            metadata={"status": "active"},
        )

        documents = catalog_tools.get_document_by_phase_task("P4-T01", doc_type="設計書")

        assert all(d.doc_type == "設計書" for d in documents)


class TestGetDocumentsByFeature:
    """Tests for get_documents_by_feature method."""

    def test_get_documents_by_feature(self, catalog_tools, mock_rag_client, project_tools):
        """Test getting documents by feature."""
        project_tools.setup_project(
            project="feat_proj",
            name="Feature Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        mock_rag_client.add_catalog_entry(
            doc_id="feat_doc1",
            name="Feature Doc 1",
            doc_type="設計書",
            project="feat_proj",
            phase_task="P1-T01",
            metadata={"feature": "Authentication", "status": "active"},
        )
        mock_rag_client.add_catalog_entry(
            doc_id="feat_doc2",
            name="Feature Doc 2",
            doc_type="実装手順書",
            project="feat_proj",
            phase_task="P1-T02",
            metadata={"feature": "Authentication", "status": "active"},
        )

        documents = catalog_tools.get_documents_by_feature("Authentication")

        assert len(documents) >= 1
        for doc in documents:
            assert doc.feature == "Authentication"
