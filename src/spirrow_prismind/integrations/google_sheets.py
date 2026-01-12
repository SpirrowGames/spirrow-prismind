"""Google Sheets API integration."""

import os
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the token.json file.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class GoogleSheetsClient:
    """Client for Google Sheets API operations."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
    ):
        """Initialize the Google Sheets client.

        Args:
            credentials_path: Path to credentials.json file
            token_path: Path to store/load token.json
        """
        self.credentials_path = credentials_path or os.getenv(
            "GOOGLE_CREDENTIALS_PATH", "credentials.json"
        )
        self.token_path = token_path or os.getenv("GOOGLE_TOKEN_PATH", "token.json")
        self._service = None
        self._creds = None

    def _get_credentials(self) -> Credentials:
        """Get or refresh Google API credentials."""
        creds = None

        # Load existing token
        if Path(self.token_path).exists():
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not Path(self.credentials_path).exists():
                    raise FileNotFoundError(
                        f"Credentials file not found: {self.credentials_path}. "
                        "Please download from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save the credentials for next run
            with open(self.token_path, "w") as token:
                token.write(creds.to_json())

        return creds

    @property
    def service(self):
        """Get the Sheets API service, initializing if needed."""
        if self._service is None:
            self._creds = self._get_credentials()
            self._service = build("sheets", "v4", credentials=self._creds)
        return self._service

    def get_sheet_values(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> list[list[Any]]:
        """Get values from a spreadsheet range.

        Args:
            spreadsheet_id: The spreadsheet ID
            range_name: A1 notation of range (e.g., "Sheet1!A1:D10")

        Returns:
            List of rows, each row is a list of cell values
        """
        try:
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range_name)
                .execute()
            )
            return result.get("values", [])
        except HttpError as e:
            raise RuntimeError(f"Failed to get sheet values: {e}")

    def update_sheet_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        """Update values in a spreadsheet range.

        Args:
            spreadsheet_id: The spreadsheet ID
            range_name: A1 notation of range
            values: 2D list of values to write
            value_input_option: How to interpret input (USER_ENTERED or RAW)

        Returns:
            API response
        """
        try:
            body = {"values": values}
            result = (
                self.service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption=value_input_option,
                    body=body,
                )
                .execute()
            )
            return result
        except HttpError as e:
            raise RuntimeError(f"Failed to update sheet values: {e}")

    def append_sheet_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        """Append values to a spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID
            range_name: A1 notation of range to append after
            values: 2D list of values to append
            value_input_option: How to interpret input

        Returns:
            API response
        """
        try:
            body = {"values": values}
            result = (
                self.service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=range_name,
                    valueInputOption=value_input_option,
                    insertDataOption="INSERT_ROWS",
                    body=body,
                )
                .execute()
            )
            return result
        except HttpError as e:
            raise RuntimeError(f"Failed to append sheet values: {e}")

    def clear_sheet_range(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> dict:
        """Clear values in a spreadsheet range.

        Args:
            spreadsheet_id: The spreadsheet ID
            range_name: A1 notation of range to clear

        Returns:
            API response
        """
        try:
            result = (
                self.service.spreadsheets()
                .values()
                .clear(spreadsheetId=spreadsheet_id, range=range_name)
                .execute()
            )
            return result
        except HttpError as e:
            raise RuntimeError(f"Failed to clear sheet range: {e}")

    def get_spreadsheet_info(self, spreadsheet_id: str) -> dict:
        """Get spreadsheet metadata.

        Args:
            spreadsheet_id: The spreadsheet ID

        Returns:
            Spreadsheet metadata
        """
        try:
            result = (
                self.service.spreadsheets()
                .get(spreadsheetId=spreadsheet_id)
                .execute()
            )
            return result
        except HttpError as e:
            raise RuntimeError(f"Failed to get spreadsheet info: {e}")

    def get_sheet_names(self, spreadsheet_id: str) -> list[str]:
        """Get all sheet names in a spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID

        Returns:
            List of sheet names
        """
        info = self.get_spreadsheet_info(spreadsheet_id)
        return [sheet["properties"]["title"] for sheet in info.get("sheets", [])]

    def find_row_by_value(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        column_index: int,
        value: str,
    ) -> Optional[int]:
        """Find the row number where a column contains a specific value.

        Args:
            spreadsheet_id: The spreadsheet ID
            sheet_name: Name of the sheet
            column_index: 0-based column index to search
            value: Value to find

        Returns:
            1-based row number if found, None otherwise
        """
        values = self.get_sheet_values(spreadsheet_id, f"{sheet_name}!A:Z")
        for i, row in enumerate(values):
            if len(row) > column_index and row[column_index] == value:
                return i + 1  # Convert to 1-based
        return None

    def update_row(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        row_number: int,
        values: list[Any],
    ) -> dict:
        """Update a specific row.

        Args:
            spreadsheet_id: The spreadsheet ID
            sheet_name: Name of the sheet
            row_number: 1-based row number
            values: List of values for the row

        Returns:
            API response
        """
        # Calculate the range based on number of values
        end_col = chr(ord("A") + len(values) - 1)
        range_name = f"{sheet_name}!A{row_number}:{end_col}{row_number}"
        return self.update_sheet_values(spreadsheet_id, range_name, [values])
