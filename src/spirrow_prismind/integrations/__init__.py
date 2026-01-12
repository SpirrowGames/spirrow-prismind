"""Integration modules for external services."""

from .google_docs import DocumentContent, DocumentInfo, GoogleDocsClient
from .google_drive import (
    FileInfo,
    FolderContents,
    GoogleDriveClient,
    MimeType,
)
from .google_sheets import GoogleSheetsClient
from .memory_client import (
    CurrentProject,
    MemoryClient,
    MemoryEntry,
    MemoryOperationResult,
    SessionState,
)
from .rag_client import (
    RAGClient,
    RAGDocument,
    RAGOperationResult,
    RAGSearchResult,
)

__all__ = [
    # Google Docs
    "DocumentContent",
    "DocumentInfo",
    "GoogleDocsClient",
    # Google Drive
    "FileInfo",
    "FolderContents",
    "GoogleDriveClient",
    "MimeType",
    # Google Sheets
    "GoogleSheetsClient",
    # Memory
    "CurrentProject",
    "MemoryClient",
    "MemoryEntry",
    "MemoryOperationResult",
    "SessionState",
    # RAG
    "RAGClient",
    "RAGDocument",
    "RAGOperationResult",
    "RAGSearchResult",
]
