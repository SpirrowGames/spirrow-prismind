"""Google Docs API integration for document creation and editing."""

import logging
from dataclasses import dataclass
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


@dataclass
class DocumentInfo:
    """Information about a Google Doc."""
    doc_id: str
    title: str
    url: str
    revision_id: str = ""


@dataclass
class DocumentContent:
    """Content of a Google Doc."""
    doc_id: str
    title: str
    body_text: str
    url: str


class GoogleDocsClient:
    """Client for Google Docs API operations."""

    SCOPES = ["https://www.googleapis.com/auth/documents"]

    def __init__(self, credentials: Credentials):
        """Initialize the client with credentials.
        
        Args:
            credentials: OAuth2 credentials with Docs API scope
        """
        self.credentials = credentials
        self._service = None

    @property
    def service(self):
        """Lazy initialization of the Docs service."""
        if self._service is None:
            self._service = build("docs", "v1", credentials=self.credentials)
        return self._service

    def create_document(self, title: str) -> DocumentInfo:
        """Create a new Google Doc.
        
        Args:
            title: Title of the new document
            
        Returns:
            DocumentInfo with the created document's details
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            doc = self.service.documents().create(body={"title": title}).execute()
            
            doc_id = doc.get("documentId", "")
            return DocumentInfo(
                doc_id=doc_id,
                title=doc.get("title", title),
                url=f"https://docs.google.com/document/d/{doc_id}/edit",
                revision_id=doc.get("revisionId", ""),
            )
        except HttpError as e:
            logger.error(f"Failed to create document '{title}': {e}")
            raise

    def get_document(self, doc_id: str) -> DocumentContent:
        """Get a document's content.
        
        Args:
            doc_id: The document ID
            
        Returns:
            DocumentContent with the document's text content
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            doc = self.service.documents().get(documentId=doc_id).execute()
            
            # Extract text from the document body
            body_text = self._extract_text(doc.get("body", {}))
            
            return DocumentContent(
                doc_id=doc_id,
                title=doc.get("title", ""),
                body_text=body_text,
                url=f"https://docs.google.com/document/d/{doc_id}/edit",
            )
        except HttpError as e:
            logger.error(f"Failed to get document '{doc_id}': {e}")
            raise

    def _extract_text(self, body: dict) -> str:
        """Extract plain text from document body.
        
        Args:
            body: The document body structure
            
        Returns:
            Extracted text content
        """
        text_parts = []
        content = body.get("content", [])
        
        for element in content:
            if "paragraph" in element:
                paragraph = element["paragraph"]
                for para_element in paragraph.get("elements", []):
                    if "textRun" in para_element:
                        text_parts.append(para_element["textRun"].get("content", ""))
            elif "table" in element:
                # Handle tables
                table = element["table"]
                for row in table.get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        cell_text = self._extract_text({"content": cell.get("content", [])})
                        text_parts.append(cell_text)
                        text_parts.append("\t")
                    text_parts.append("\n")
        
        return "".join(text_parts)

    def insert_text(
        self,
        doc_id: str,
        text: str,
        index: int = 1,
    ) -> bool:
        """Insert text at a specific position.
        
        Args:
            doc_id: The document ID
            text: Text to insert
            index: Position to insert (1 = beginning of document)
            
        Returns:
            True if successful
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            requests = [
                {
                    "insertText": {
                        "location": {"index": index},
                        "text": text,
                    }
                }
            ]
            
            self.service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests},
            ).execute()
            
            return True
        except HttpError as e:
            logger.error(f"Failed to insert text in document '{doc_id}': {e}")
            raise

    def append_text(self, doc_id: str, text: str) -> bool:
        """Append text to the end of the document.
        
        Args:
            doc_id: The document ID
            text: Text to append
            
        Returns:
            True if successful
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            # Get current document to find end index
            doc = self.service.documents().get(documentId=doc_id).execute()
            body = doc.get("body", {})
            content = body.get("content", [])
            
            # Find the end index
            end_index = 1
            if content:
                last_element = content[-1]
                end_index = last_element.get("endIndex", 1) - 1
            
            return self.insert_text(doc_id, text, end_index)
        except HttpError as e:
            logger.error(f"Failed to append text to document '{doc_id}': {e}")
            raise

    def replace_all_text(self, doc_id: str, new_text: str) -> bool:
        """Replace all content in the document.
        
        Args:
            doc_id: The document ID
            new_text: New text content
            
        Returns:
            True if successful
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            # Get current document
            doc = self.service.documents().get(documentId=doc_id).execute()
            body = doc.get("body", {})
            content = body.get("content", [])
            
            requests = []
            
            # Find content range (excluding the final newline)
            if content and len(content) > 1:
                # Delete existing content (keep first element which is usually empty)
                start_index = 1
                end_index = content[-1].get("endIndex", 1) - 1
                
                if end_index > start_index:
                    requests.append({
                        "deleteContentRange": {
                            "range": {
                                "startIndex": start_index,
                                "endIndex": end_index,
                            }
                        }
                    })
            
            # Insert new text
            requests.append({
                "insertText": {
                    "location": {"index": 1},
                    "text": new_text,
                }
            })
            
            if requests:
                self.service.documents().batchUpdate(
                    documentId=doc_id,
                    body={"requests": requests},
                ).execute()
            
            return True
        except HttpError as e:
            logger.error(f"Failed to replace content in document '{doc_id}': {e}")
            raise

    def update_title(self, doc_id: str, new_title: str) -> bool:
        """Update the document title.
        
        Note: This requires Drive API to change the file name.
        The Docs API title is read-only.
        
        Args:
            doc_id: The document ID
            new_title: New title
            
        Returns:
            True (title update requires Drive API)
        """
        logger.warning(
            f"Document title update requires Drive API. "
            f"Use GoogleDriveClient.rename_file('{doc_id}', '{new_title}') instead."
        )
        return False

    def insert_heading(
        self,
        doc_id: str,
        text: str,
        heading_level: int = 1,
        index: int = 1,
    ) -> bool:
        """Insert a heading at a specific position.
        
        Args:
            doc_id: The document ID
            text: Heading text
            heading_level: Heading level (1-6)
            index: Position to insert
            
        Returns:
            True if successful
            
        Raises:
            HttpError: If the API request fails
        """
        try:
            heading_text = text if text.endswith("\n") else text + "\n"
            
            requests = [
                # Insert text
                {
                    "insertText": {
                        "location": {"index": index},
                        "text": heading_text,
                    }
                },
                # Apply heading style
                {
                    "updateParagraphStyle": {
                        "range": {
                            "startIndex": index,
                            "endIndex": index + len(heading_text),
                        },
                        "paragraphStyle": {
                            "namedStyleType": f"HEADING_{min(heading_level, 6)}",
                        },
                        "fields": "namedStyleType",
                    }
                },
            ]
            
            self.service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests},
            ).execute()
            
            return True
        except HttpError as e:
            logger.error(f"Failed to insert heading in document '{doc_id}': {e}")
            raise

    def create_document_with_content(
        self,
        title: str,
        content: str,
        heading: Optional[str] = None,
    ) -> DocumentInfo:
        """Create a new document with initial content.
        
        Args:
            title: Document title
            content: Initial content
            heading: Optional heading to add at the top
            
        Returns:
            DocumentInfo with the created document's details
            
        Raises:
            HttpError: If the API request fails
        """
        # Create the document
        doc_info = self.create_document(title)
        
        try:
            requests = []
            current_index = 1
            
            # Add heading if provided
            if heading:
                heading_text = heading if heading.endswith("\n") else heading + "\n"
                requests.extend([
                    {
                        "insertText": {
                            "location": {"index": current_index},
                            "text": heading_text,
                        }
                    },
                    {
                        "updateParagraphStyle": {
                            "range": {
                                "startIndex": current_index,
                                "endIndex": current_index + len(heading_text),
                            },
                            "paragraphStyle": {
                                "namedStyleType": "HEADING_1",
                            },
                            "fields": "namedStyleType",
                        }
                    },
                ])
                current_index += len(heading_text)
            
            # Add content
            if content:
                requests.append({
                    "insertText": {
                        "location": {"index": current_index},
                        "text": content,
                    }
                })
            
            if requests:
                self.service.documents().batchUpdate(
                    documentId=doc_info.doc_id,
                    body={"requests": requests},
                ).execute()
            
            return doc_info
        except HttpError as e:
            logger.error(f"Failed to add content to new document: {e}")
            # Document was created but content failed - still return the doc info
            return doc_info
