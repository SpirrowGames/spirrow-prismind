"""Google Drive API integration for folder operations and file management."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class MimeType(str, Enum):
    """Common MIME types for Google Drive."""
    FOLDER = "application/vnd.google-apps.folder"
    DOCUMENT = "application/vnd.google-apps.document"
    SPREADSHEET = "application/vnd.google-apps.spreadsheet"
    PRESENTATION = "application/vnd.google-apps.presentation"


@dataclass
class FileInfo:
    """Information about a file or folder in Google Drive."""
    file_id: str
    name: str
    mime_type: str
    parents: list[str] = field(default_factory=list)
    web_view_link: str = ""
    created_time: str = ""
    modified_time: str = ""

    @property
    def is_folder(self) -> bool:
        """Check if this is a folder."""
        return self.mime_type == MimeType.FOLDER

    @property
    def is_document(self) -> bool:
        """Check if this is a Google Doc."""
        return self.mime_type == MimeType.DOCUMENT


@dataclass
class FolderContents:
    """Contents of a folder."""
    folder_id: str
    folder_name: str
    files: list[FileInfo] = field(default_factory=list)
    subfolders: list[FileInfo] = field(default_factory=list)


class GoogleDriveClient:
    """Client for Google Drive API operations."""

    SCOPES = ["https://www.googleapis.com/auth/drive"]

    def __init__(self, credentials: Credentials):
        """Initialize the client with credentials.
        
        Args:
            credentials: OAuth2 credentials with Drive API scope
        """
        self.credentials = credentials
        self._service = None

    @property
    def service(self):
        """Lazy initialization of the Drive service."""
        if self._service is None:
            self._service = build("drive", "v3", credentials=self.credentials)
        return self._service

    def create_folder(
        self,
        name: str,
        parent_id: Optional[str] = None,
    ) -> FileInfo:
        """Create a new folder.
        
        Args:
            name: Folder name
            parent_id: Parent folder ID (None for root)
            
        Returns:
            FileInfo with the created folder's details
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            file_metadata = {
                "name": name,
                "mimeType": MimeType.FOLDER,
            }
            
            if parent_id:
                file_metadata["parents"] = [parent_id]
            
            folder = self.service.files().create(
                body=file_metadata,
                fields="id, name, mimeType, parents, webViewLink, createdTime, modifiedTime",
            ).execute()
            
            return FileInfo(
                file_id=folder.get("id", ""),
                name=folder.get("name", name),
                mime_type=folder.get("mimeType", MimeType.FOLDER),
                parents=folder.get("parents", []),
                web_view_link=folder.get("webViewLink", ""),
                created_time=folder.get("createdTime", ""),
                modified_time=folder.get("modifiedTime", ""),
            )
        except HttpError as e:
            logger.error(f"Failed to create folder '{name}': {e}")
            raise

    def get_file_info(self, file_id: str) -> FileInfo:
        """Get information about a file or folder.
        
        Args:
            file_id: The file/folder ID
            
        Returns:
            FileInfo with the file's details
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            file = self.service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, parents, webViewLink, createdTime, modifiedTime",
            ).execute()
            
            return FileInfo(
                file_id=file.get("id", ""),
                name=file.get("name", ""),
                mime_type=file.get("mimeType", ""),
                parents=file.get("parents", []),
                web_view_link=file.get("webViewLink", ""),
                created_time=file.get("createdTime", ""),
                modified_time=file.get("modifiedTime", ""),
            )
        except HttpError as e:
            logger.error(f"Failed to get file info for '{file_id}': {e}")
            raise

    def move_file(
        self,
        file_id: str,
        new_parent_id: str,
        remove_from_current: bool = True,
    ) -> FileInfo:
        """Move a file to a different folder.
        
        Args:
            file_id: The file ID to move
            new_parent_id: The destination folder ID
            remove_from_current: Whether to remove from current parent
            
        Returns:
            Updated FileInfo
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            # Get current parents
            file = self.service.files().get(
                fileId=file_id,
                fields="parents",
            ).execute()
            
            previous_parents = ",".join(file.get("parents", []))
            
            # Move the file
            update_params = {
                "fileId": file_id,
                "addParents": new_parent_id,
                "fields": "id, name, mimeType, parents, webViewLink, createdTime, modifiedTime",
            }
            
            if remove_from_current and previous_parents:
                update_params["removeParents"] = previous_parents
            
            updated_file = self.service.files().update(**update_params).execute()
            
            return FileInfo(
                file_id=updated_file.get("id", ""),
                name=updated_file.get("name", ""),
                mime_type=updated_file.get("mimeType", ""),
                parents=updated_file.get("parents", []),
                web_view_link=updated_file.get("webViewLink", ""),
                created_time=updated_file.get("createdTime", ""),
                modified_time=updated_file.get("modifiedTime", ""),
            )
        except HttpError as e:
            logger.error(f"Failed to move file '{file_id}': {e}")
            raise

    def rename_file(self, file_id: str, new_name: str) -> FileInfo:
        """Rename a file or folder.
        
        Args:
            file_id: The file/folder ID
            new_name: New name
            
        Returns:
            Updated FileInfo
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            updated_file = self.service.files().update(
                fileId=file_id,
                body={"name": new_name},
                fields="id, name, mimeType, parents, webViewLink, createdTime, modifiedTime",
            ).execute()
            
            return FileInfo(
                file_id=updated_file.get("id", ""),
                name=updated_file.get("name", ""),
                mime_type=updated_file.get("mimeType", ""),
                parents=updated_file.get("parents", []),
                web_view_link=updated_file.get("webViewLink", ""),
                created_time=updated_file.get("createdTime", ""),
                modified_time=updated_file.get("modifiedTime", ""),
            )
        except HttpError as e:
            logger.error(f"Failed to rename file '{file_id}': {e}")
            raise

    def list_folder_contents(
        self,
        folder_id: str,
        include_trashed: bool = False,
    ) -> FolderContents:
        """List contents of a folder.
        
        Args:
            folder_id: The folder ID
            include_trashed: Whether to include trashed files
            
        Returns:
            FolderContents with files and subfolders
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            # Get folder info
            folder_info = self.get_file_info(folder_id)
            
            # Build query
            query = f"'{folder_id}' in parents"
            if not include_trashed:
                query += " and trashed = false"
            
            # List files
            results = self.service.files().list(
                q=query,
                fields="files(id, name, mimeType, parents, webViewLink, createdTime, modifiedTime)",
                orderBy="folder, name",
            ).execute()
            
            files = []
            subfolders = []
            
            for item in results.get("files", []):
                file_info = FileInfo(
                    file_id=item.get("id", ""),
                    name=item.get("name", ""),
                    mime_type=item.get("mimeType", ""),
                    parents=item.get("parents", []),
                    web_view_link=item.get("webViewLink", ""),
                    created_time=item.get("createdTime", ""),
                    modified_time=item.get("modifiedTime", ""),
                )
                
                if file_info.is_folder:
                    subfolders.append(file_info)
                else:
                    files.append(file_info)
            
            return FolderContents(
                folder_id=folder_id,
                folder_name=folder_info.name,
                files=files,
                subfolders=subfolders,
            )
        except HttpError as e:
            logger.error(f"Failed to list folder contents for '{folder_id}': {e}")
            raise

    def find_folders_by_name(
        self,
        name: str,
        parent_id: Optional[str] = None,
    ) -> list[FileInfo]:
        """Find all folders with a given name.

        Args:
            name: Folder name to search for
            parent_id: Parent folder ID to search in (None for anywhere)

        Returns:
            List of FileInfo for all matching folders (sorted by creation time)

        Raises:
            HttpError: If the API request fails
        """
        try:
            # Escape single quotes in folder name for Drive API query
            escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
            query = f"name = '{escaped_name}' and mimeType = '{MimeType.FOLDER}' and trashed = false"

            if parent_id:
                query += f" and '{parent_id}' in parents"

            results = self.service.files().list(
                q=query,
                fields="files(id, name, mimeType, parents, webViewLink, createdTime, modifiedTime)",
                orderBy="createdTime",  # Oldest first
            ).execute()

            folders = []
            for item in results.get("files", []):
                folders.append(FileInfo(
                    file_id=item.get("id", ""),
                    name=item.get("name", ""),
                    mime_type=item.get("mimeType", ""),
                    parents=item.get("parents", []),
                    web_view_link=item.get("webViewLink", ""),
                    created_time=item.get("createdTime", ""),
                    modified_time=item.get("modifiedTime", ""),
                ))

            return folders
        except HttpError as e:
            logger.error(f"Failed to find folders '{name}': {e}")
            raise

    def find_folder_by_name(
        self,
        name: str,
        parent_id: Optional[str] = None,
    ) -> Optional[FileInfo]:
        """Find a folder by name.

        Args:
            name: Folder name to search for
            parent_id: Parent folder ID to search in (None for anywhere)

        Returns:
            FileInfo if found, None otherwise (returns oldest if multiple exist)

        Raises:
            HttpError: If the API request fails
        """
        folders = self.find_folders_by_name(name, parent_id)
        return folders[0] if folders else None

    def create_folder_if_not_exists(
        self,
        name: str,
        parent_id: Optional[str] = None,
    ) -> tuple[FileInfo, bool]:
        """Create a folder if it doesn't exist, with race condition protection.

        This method handles the case where concurrent requests might both try
        to create the same folder. After creating, it verifies no duplicates
        were created, and returns the oldest folder if any exist.

        Args:
            name: Folder name
            parent_id: Parent folder ID

        Returns:
            Tuple of (FileInfo, created) where created is True if newly created

        Raises:
            HttpError: If the API request fails
        """
        # First check for existing folder
        existing = self.find_folder_by_name(name, parent_id)
        if existing:
            return existing, False

        # Create the folder
        new_folder = self.create_folder(name, parent_id)

        # Post-creation check: verify for race condition duplicates
        # Small delay to allow other concurrent creates to complete
        all_folders = self.find_folders_by_name(name, parent_id)

        if len(all_folders) > 1:
            # Race condition detected - multiple folders with same name
            # Use the oldest folder (first in list, sorted by createdTime)
            canonical_folder = all_folders[0]
            logger.warning(
                f"Duplicate folders detected for '{name}' (count: {len(all_folders)}). "
                f"Using oldest folder: {canonical_folder.file_id}"
            )

            # Clean up duplicates by moving them to trash
            for duplicate in all_folders[1:]:
                try:
                    self.delete_file(duplicate.file_id, permanent=False)
                    logger.info(
                        f"Moved duplicate folder '{name}' ({duplicate.file_id}) to trash"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to trash duplicate folder {duplicate.file_id}: {e}"
                    )

            # Return the canonical folder
            # Set created=True only if our created folder is the canonical one
            was_created = canonical_folder.file_id == new_folder.file_id
            return canonical_folder, was_created

        return new_folder, True

    def ensure_folder_path(
        self,
        path: str,
        parent_id: str,
    ) -> tuple[Optional[FileInfo], bool]:
        """Ensure a folder path exists, creating folders as needed.

        Handles nested paths like "設計/詳細設計" by creating each
        folder in the hierarchy if it doesn't exist.

        Args:
            path: Folder path (e.g., "設計/詳細設計")
            parent_id: Parent folder ID

        Returns:
            Tuple of (final folder FileInfo, any folders created)
            Returns (None, False) if path is empty
        """
        if not path:
            return None, False

        parts = [p.strip() for p in path.split("/") if p.strip()]
        if not parts:
            return None, False

        current_parent = parent_id
        any_created = False
        final_folder: Optional[FileInfo] = None

        for folder_name in parts:
            folder_info, created = self.create_folder_if_not_exists(
                name=folder_name,
                parent_id=current_parent,
            )
            if created:
                any_created = True
                logger.info(f"Created folder '{folder_name}' in path '{path}'")
            current_parent = folder_info.file_id
            final_folder = folder_info

        return final_folder, any_created

    def delete_file(self, file_id: str, permanent: bool = False) -> bool:
        """Delete a file or folder.
        
        Args:
            file_id: The file/folder ID
            permanent: If True, permanently delete. If False, move to trash.
            
        Returns:
            True if successful
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            if permanent:
                self.service.files().delete(fileId=file_id).execute()
            else:
                self.service.files().update(
                    fileId=file_id,
                    body={"trashed": True},
                ).execute()
            
            return True
        except HttpError as e:
            logger.error(f"Failed to delete file '{file_id}': {e}")
            raise

    def search_files(
        self,
        query: str,
        mime_type: Optional[str] = None,
        parent_id: Optional[str] = None,
        max_results: int = 100,
    ) -> list[FileInfo]:
        """Search for files.
        
        Args:
            query: Search query (searches name and fullText)
            mime_type: Filter by MIME type
            parent_id: Filter by parent folder
            max_results: Maximum number of results
            
        Returns:
            List of matching FileInfo
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            # Build query
            q_parts = [f"fullText contains '{query}'", "trashed = false"]
            
            if mime_type:
                q_parts.append(f"mimeType = '{mime_type}'")
            
            if parent_id:
                q_parts.append(f"'{parent_id}' in parents")
            
            q = " and ".join(q_parts)
            
            results = self.service.files().list(
                q=q,
                fields="files(id, name, mimeType, parents, webViewLink, createdTime, modifiedTime)",
                pageSize=max_results,
                orderBy="modifiedTime desc",
            ).execute()
            
            return [
                FileInfo(
                    file_id=item.get("id", ""),
                    name=item.get("name", ""),
                    mime_type=item.get("mimeType", ""),
                    parents=item.get("parents", []),
                    web_view_link=item.get("webViewLink", ""),
                    created_time=item.get("createdTime", ""),
                    modified_time=item.get("modifiedTime", ""),
                )
                for item in results.get("files", [])
            ]
        except HttpError as e:
            logger.error(f"Failed to search files for '{query}': {e}")
            raise

    def create_folder_structure(
        self,
        root_parent_id: str,
        folder_names: list[str],
    ) -> dict[str, FileInfo]:
        """Create multiple folders under a parent.

        Args:
            root_parent_id: Parent folder ID
            folder_names: List of folder names to create

        Returns:
            Dict mapping folder name to FileInfo

        Raises:
            HttpError: If the API request fails
        """
        result = {}

        for name in folder_names:
            folder_info, _ = self.create_folder_if_not_exists(name, root_parent_id)
            result[name] = folder_info

        return result

    def create_spreadsheet(
        self,
        name: str,
        parent_id: Optional[str] = None,
    ) -> FileInfo:
        """Create a new Google Spreadsheet.

        Args:
            name: Spreadsheet name
            parent_id: Parent folder ID (None for root)

        Returns:
            FileInfo with the created spreadsheet's details

        Raises:
            HttpError: If the API request fails
        """
        try:
            file_metadata = {
                "name": name,
                "mimeType": MimeType.SPREADSHEET,
            }

            if parent_id:
                file_metadata["parents"] = [parent_id]

            spreadsheet = self.service.files().create(
                body=file_metadata,
                fields="id, name, mimeType, parents, webViewLink, createdTime, modifiedTime",
            ).execute()

            logger.info(f"Created spreadsheet '{name}' with ID: {spreadsheet.get('id')}")

            return FileInfo(
                file_id=spreadsheet.get("id", ""),
                name=spreadsheet.get("name", name),
                mime_type=spreadsheet.get("mimeType", MimeType.SPREADSHEET),
                parents=spreadsheet.get("parents", []),
                web_view_link=spreadsheet.get("webViewLink", ""),
                created_time=spreadsheet.get("createdTime", ""),
                modified_time=spreadsheet.get("modifiedTime", ""),
            )
        except HttpError as e:
            logger.error(f"Failed to create spreadsheet '{name}': {e}")
            raise

    def create_document(
        self,
        name: str,
        parent_id: Optional[str] = None,
    ) -> FileInfo:
        """Create a new Google Document.

        Args:
            name: Document name
            parent_id: Parent folder ID (None for root)

        Returns:
            FileInfo with the created document's details

        Raises:
            HttpError: If the API request fails
        """
        try:
            file_metadata = {
                "name": name,
                "mimeType": MimeType.DOCUMENT,
            }

            if parent_id:
                file_metadata["parents"] = [parent_id]

            document = self.service.files().create(
                body=file_metadata,
                fields="id, name, mimeType, parents, webViewLink, createdTime, modifiedTime",
            ).execute()

            logger.info(f"Created document '{name}' with ID: {document.get('id')}")

            return FileInfo(
                file_id=document.get("id", ""),
                name=document.get("name", name),
                mime_type=document.get("mimeType", MimeType.DOCUMENT),
                parents=document.get("parents", []),
                web_view_link=document.get("webViewLink", ""),
                created_time=document.get("createdTime", ""),
                modified_time=document.get("modifiedTime", ""),
            )
        except HttpError as e:
            logger.error(f"Failed to create document '{name}': {e}")
            raise

    def deduplicate_folders(
        self,
        parent_id: str,
        dry_run: bool = True,
    ) -> dict[str, list[FileInfo]]:
        """Find and optionally remove duplicate folders in a parent folder.

        This method identifies folders with the same name and optionally
        moves duplicates to trash, keeping only the oldest folder.

        Args:
            parent_id: Parent folder ID to scan for duplicates
            dry_run: If True, only report duplicates without deleting

        Returns:
            Dict mapping folder name to list of duplicate FileInfo objects
            (excludes the canonical/kept folder)

        Raises:
            HttpError: If the API request fails
        """
        try:
            # Get all folders in parent
            contents = self.list_folder_contents(parent_id)

            # Group by name
            name_to_folders: dict[str, list[FileInfo]] = {}
            for folder in contents.subfolders:
                if folder.name not in name_to_folders:
                    name_to_folders[folder.name] = []
                name_to_folders[folder.name].append(folder)

            # Find duplicates and process
            duplicates: dict[str, list[FileInfo]] = {}

            for name, folders in name_to_folders.items():
                if len(folders) > 1:
                    # Sort by creation time (oldest first)
                    sorted_folders = sorted(
                        folders,
                        key=lambda f: f.created_time or "",
                    )

                    canonical = sorted_folders[0]
                    dups = sorted_folders[1:]
                    duplicates[name] = dups

                    logger.info(
                        f"Found {len(dups)} duplicate(s) of folder '{name}'. "
                        f"Keeping: {canonical.file_id}"
                    )

                    if not dry_run:
                        for dup in dups:
                            try:
                                self.delete_file(dup.file_id, permanent=False)
                                logger.info(
                                    f"Moved duplicate folder '{name}' "
                                    f"({dup.file_id}) to trash"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to trash duplicate folder "
                                    f"{dup.file_id}: {e}"
                                )

            return duplicates
        except HttpError as e:
            logger.error(f"Failed to deduplicate folders in '{parent_id}': {e}")
            raise
