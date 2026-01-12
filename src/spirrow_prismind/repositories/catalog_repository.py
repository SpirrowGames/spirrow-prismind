"""Catalog repository - manages the document catalog in Google Sheets."""

import os
from datetime import datetime
from typing import Optional

from ..integrations.google_sheets import GoogleSheetsClient
from ..models.catalog import (
    CATALOG_SHEET_HEADERS,
    CatalogEntry,
    SearchCatalogResult,
    SyncCatalogResult,
)


class CatalogRepository:
    """Repository for managing the document catalog."""

    SHEET_NAME = "目録"

    def __init__(
        self,
        sheets_client: Optional[GoogleSheetsClient] = None,
        spreadsheet_id: Optional[str] = None,
    ):
        """Initialize the catalog repository.

        Args:
            sheets_client: Google Sheets client (creates new if not provided)
            spreadsheet_id: ID of the catalog spreadsheet
        """
        self.sheets_client = sheets_client or GoogleSheetsClient()
        self.spreadsheet_id = spreadsheet_id or os.getenv("CATALOG_SHEET_ID", "")

    def _ensure_sheet_exists(self) -> None:
        """Ensure the catalog sheet exists with proper headers."""
        if not self.spreadsheet_id:
            raise ValueError("CATALOG_SHEET_ID not configured")

        try:
            sheet_names = self.sheets_client.get_sheet_names(self.spreadsheet_id)
            if self.SHEET_NAME not in sheet_names:
                # Sheet doesn't exist - would need to create it
                # For now, just warn
                raise ValueError(
                    f"Sheet '{self.SHEET_NAME}' not found. Please create it manually."
                )

            # Check if headers exist
            values = self.sheets_client.get_sheet_values(
                self.spreadsheet_id, f"{self.SHEET_NAME}!A1:M1"
            )
            if not values or values[0] != CATALOG_SHEET_HEADERS:
                # Set headers
                self.sheets_client.update_sheet_values(
                    self.spreadsheet_id,
                    f"{self.SHEET_NAME}!A1:M1",
                    [CATALOG_SHEET_HEADERS],
                )
        except Exception as e:
            raise RuntimeError(f"Failed to ensure catalog sheet: {e}")

    def get_all_entries(self) -> list[CatalogEntry]:
        """Get all catalog entries.

        Returns:
            List of all catalog entries
        """
        values = self.sheets_client.get_sheet_values(
            self.spreadsheet_id, f"{self.SHEET_NAME}!A2:M"
        )
        return [CatalogEntry.from_sheet_row(row) for row in values if row]

    def get_entry_by_id(self, doc_id: str) -> Optional[CatalogEntry]:
        """Get a catalog entry by document ID.

        Args:
            doc_id: The document ID

        Returns:
            CatalogEntry if found, None otherwise
        """
        entries = self.get_all_entries()
        for entry in entries:
            if entry.doc_id == doc_id:
                return entry
        return None

    def add_entry(self, entry: CatalogEntry) -> bool:
        """Add a new catalog entry.

        Args:
            entry: The catalog entry to add

        Returns:
            True if successful
        """
        try:
            self.sheets_client.append_sheet_values(
                self.spreadsheet_id,
                f"{self.SHEET_NAME}!A:M",
                [entry.to_sheet_row()],
            )
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to add catalog entry: {e}")

    def update_entry(self, entry: CatalogEntry) -> bool:
        """Update an existing catalog entry.

        Args:
            entry: The catalog entry to update

        Returns:
            True if successful
        """
        # Find the row with this doc_id
        row_num = self.sheets_client.find_row_by_value(
            self.spreadsheet_id,
            self.SHEET_NAME,
            2,  # ID column (0-based)
            entry.doc_id,
        )

        if row_num is None:
            raise ValueError(f"Catalog entry not found: {entry.doc_id}")

        # Update the row
        self.sheets_client.update_row(
            self.spreadsheet_id,
            self.SHEET_NAME,
            row_num,
            entry.to_sheet_row(),
        )
        return True

    def search(
        self,
        project: Optional[str] = None,
        doc_type: Optional[str] = None,
        phase_task: Optional[str] = None,
        feature: Optional[str] = None,
        reference_timing: Optional[str] = None,
        status: str = "active",
        keywords: Optional[list[str]] = None,
        limit: int = 10,
    ) -> SearchCatalogResult:
        """Search the catalog with filters.

        Args:
            project: Filter by project
            doc_type: Filter by document type
            phase_task: Filter by phase/task
            feature: Filter by feature
            reference_timing: Filter by reference timing
            status: Filter by status (active/archived/all)
            keywords: Filter by keywords (any match)
            limit: Maximum results

        Returns:
            Search results
        """
        try:
            entries = self.get_all_entries()
            results = []

            for entry in entries:
                # Apply filters
                if project and entry.project != project:
                    continue
                if doc_type and entry.doc_type != doc_type:
                    continue
                if phase_task and entry.phase_task != phase_task:
                    continue
                if feature and entry.feature != feature:
                    continue
                if reference_timing and entry.reference_timing != reference_timing:
                    continue
                if status != "all" and entry.status != status:
                    continue
                if keywords:
                    # Check if any keyword matches
                    entry_keywords_lower = [k.lower() for k in entry.keywords]
                    if not any(k.lower() in entry_keywords_lower for k in keywords):
                        continue

                results.append(entry)

                if len(results) >= limit:
                    break

            return SearchCatalogResult(
                success=True,
                total_count=len(results),
                documents=results,
                message=f"Found {len(results)} documents",
            )
        except Exception as e:
            return SearchCatalogResult(
                success=False,
                message=f"Search failed: {e}",
            )

    def delete_entry(self, doc_id: str) -> bool:
        """Delete a catalog entry (sets status to archived).

        Args:
            doc_id: The document ID to delete

        Returns:
            True if successful
        """
        entry = self.get_entry_by_id(doc_id)
        if not entry:
            raise ValueError(f"Catalog entry not found: {doc_id}")

        entry.status = "archived"
        entry.updated_at = datetime.now()
        return self.update_entry(entry)
