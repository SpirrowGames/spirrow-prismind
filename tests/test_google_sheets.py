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
