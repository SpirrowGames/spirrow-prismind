"""Tests for Google Sheets integration."""

import pytest
from unittest.mock import MagicMock, patch

from spirrow_prismind.integrations.google_sheets import GoogleSheetsClient


class TestGoogleSheetsClient:
    """Test cases for GoogleSheetsClient."""

    @patch("spirrow_prismind.integrations.google_sheets.build")
    @patch("spirrow_prismind.integrations.google_sheets.Credentials")
    def test_get_sheet_values(self, mock_creds, mock_build):
        """Test getting values from a sheet."""
        # Setup mock
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_creds.from_authorized_user_file.return_value = MagicMock(valid=True)

        mock_service.spreadsheets().values().get().execute.return_value = {
            "values": [["A1", "B1"], ["A2", "B2"]]
        }

        # Test
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", MagicMock()):
                client = GoogleSheetsClient(
                    credentials_path="test_creds.json",
                    token_path="test_token.json",
                )
                # Mock the credentials loading
                client._creds = MagicMock(valid=True)
                client._service = mock_service

                values = client.get_sheet_values("test_id", "Sheet1!A1:B2")

        assert values == [["A1", "B1"], ["A2", "B2"]]


class TestGoogleSheetsClientSheetOperations:
    """Test cases for GoogleSheetsClient sheet operations."""

    @patch("spirrow_prismind.integrations.google_sheets.build")
    def test_create_sheet(self, mock_build):
        """Test creating a new sheet."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.spreadsheets().batchUpdate().execute.return_value = {
            "replies": [{"addSheet": {"properties": {"sheetId": 12345, "title": "NewSheet"}}}]
        }

        client = GoogleSheetsClient.__new__(GoogleSheetsClient)
        client._service = mock_service

        result = client.create_sheet("spreadsheet123", "NewSheet")

        # Verify batchUpdate was called with correct parameters
        mock_service.spreadsheets().batchUpdate.assert_called()
        call_args = mock_service.spreadsheets().batchUpdate.call_args
        assert call_args[1]["spreadsheetId"] == "spreadsheet123"
        assert "addSheet" in str(call_args[1]["body"])

    @patch("spirrow_prismind.integrations.google_sheets.build")
    def test_rename_sheet(self, mock_build):
        """Test renaming a sheet."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.spreadsheets().batchUpdate().execute.return_value = {"replies": [{}]}

        client = GoogleSheetsClient.__new__(GoogleSheetsClient)
        client._service = mock_service

        result = client.rename_sheet("spreadsheet123", 0, "RenamedSheet")

        # Verify batchUpdate was called with correct parameters
        mock_service.spreadsheets().batchUpdate.assert_called()
        call_args = mock_service.spreadsheets().batchUpdate.call_args
        assert call_args[1]["spreadsheetId"] == "spreadsheet123"
        assert "updateSheetProperties" in str(call_args[1]["body"])

    @patch("spirrow_prismind.integrations.google_sheets.build")
    def test_get_first_sheet_id(self, mock_build):
        """Test getting the first sheet ID."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.spreadsheets().get().execute.return_value = {
            "sheets": [
                {"properties": {"sheetId": 0, "title": "Sheet1"}},
                {"properties": {"sheetId": 1, "title": "Sheet2"}},
            ]
        }

        client = GoogleSheetsClient.__new__(GoogleSheetsClient)
        client._service = mock_service

        sheet_id = client.get_first_sheet_id("spreadsheet123")

        assert sheet_id == 0

    @patch("spirrow_prismind.integrations.google_sheets.build")
    def test_initialize_project_sheets(self, mock_build):
        """Test initializing project sheets."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Mock get spreadsheet info
        mock_service.spreadsheets().get().execute.return_value = {
            "sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}]
        }
        # Mock batchUpdate for rename and create
        mock_service.spreadsheets().batchUpdate().execute.return_value = {"replies": [{}]}

        client = GoogleSheetsClient.__new__(GoogleSheetsClient)
        client._service = mock_service

        sheets = client.initialize_project_sheets(
            spreadsheet_id="spreadsheet123",
            summary_name="Summary",
            progress_name="Progress",
            catalog_name="Catalog",
        )

        assert sheets == ["Summary", "Progress", "Catalog"]
        # Verify batchUpdate was called multiple times (for rename + creates)
        assert mock_service.spreadsheets().batchUpdate.call_count >= 3

    @patch("spirrow_prismind.integrations.google_sheets.build")
    def test_read_range(self, mock_build):
        """Test reading a range."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.spreadsheets().values().get().execute.return_value = {
            "values": [["A1", "B1"], ["A2", "B2"]]
        }

        client = GoogleSheetsClient.__new__(GoogleSheetsClient)
        client._service = mock_service

        result = client.read_range("spreadsheet123", "Sheet1!A1:B2")

        assert result["values"] == [["A1", "B1"], ["A2", "B2"]]

    @patch("spirrow_prismind.integrations.google_sheets.build")
    def test_update_range(self, mock_build):
        """Test updating a range (alias for update_sheet_values)."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.spreadsheets().values().update().execute.return_value = {
            "updatedCells": 4
        }

        client = GoogleSheetsClient.__new__(GoogleSheetsClient)
        client._service = mock_service

        result = client.update_range(
            "spreadsheet123",
            "Sheet1!A1:B2",
            [["A1", "B1"], ["A2", "B2"]],
        )

        assert result["updatedCells"] == 4

    @patch("spirrow_prismind.integrations.google_sheets.build")
    def test_append_rows(self, mock_build):
        """Test appending rows (alias for append_sheet_values)."""
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.spreadsheets().values().append().execute.return_value = {
            "updates": {"updatedRows": 2}
        }

        client = GoogleSheetsClient.__new__(GoogleSheetsClient)
        client._service = mock_service

        result = client.append_rows(
            "spreadsheet123",
            "Sheet1!A:B",
            [["A3", "B3"], ["A4", "B4"]],
        )

        assert result["updates"]["updatedRows"] == 2


class TestCatalogEntry:
    """Test cases for CatalogEntry model."""

    def test_to_sheet_row(self):
        """Test conversion to sheet row."""
        from datetime import datetime
        from spirrow_prismind.models.catalog import CatalogEntry

        entry = CatalogEntry(
            doc_id="doc123",
            name="Test Document",
            source="Google Docs",
            doc_type="設計書",
            project="TestProject",
            phase_task="P1-T01",
            feature="Feature1",
            keywords=["test", "document"],
            updated_at=datetime(2025, 1, 12),
        )

        row = entry.to_sheet_row()
        assert row[0] == "Test Document"
        assert row[1] == "Google Docs"
        assert row[2] == "doc123"
        assert row[3] == "設計書"
        assert row[4] == "TestProject"
        assert row[5] == "P1-T01"

    def test_from_sheet_row(self):
        """Test creation from sheet row."""
        from spirrow_prismind.models.catalog import CatalogEntry

        row = [
            "Test Document",
            "Google Docs",
            "doc123",
            "設計書",
            "TestProject",
            "P1-T01",
            "Feature1",
            "設計時",
            "doc456,doc789",
            "test,document",
            "2025-01-12T00:00:00",
            "user1",
            "active",
        ]

        entry = CatalogEntry.from_sheet_row(row)
        assert entry.name == "Test Document"
        assert entry.doc_id == "doc123"
        assert entry.keywords == ["test", "document"]
        assert entry.related_docs == ["doc456", "doc789"]


class TestSessionState:
    """Test cases for SessionState model."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        from datetime import datetime
        from spirrow_prismind.models.session import SessionState

        state = SessionState(
            project="TestProject",
            user="user1",
            current_phase="Phase 1",
            current_task="T01",
            last_completed="T00",
            blockers=["blocker1"],
            notes="test notes",
            updated_at=datetime(2025, 1, 12),
        )

        data = state.to_dict()
        assert data["project"] == "TestProject"
        assert data["current_phase"] == "Phase 1"
        assert data["blockers"] == ["blocker1"]

    def test_from_dict(self):
        """Test creation from dictionary."""
        from spirrow_prismind.models.session import SessionState

        data = {
            "project": "TestProject",
            "user": "user1",
            "current_phase": "Phase 1",
            "current_task": "T01",
            "last_completed": "T00",
            "blockers": ["blocker1"],
            "notes": "test notes",
            "updated_at": "2025-01-12T00:00:00",
        }

        state = SessionState.from_dict(data)
        assert state.project == "TestProject"
        assert state.current_phase == "Phase 1"
        assert len(state.blockers) == 1
