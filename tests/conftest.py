"""Pytest fixtures for Spirrow-Prismind tests."""

import pytest
from unittest.mock import MagicMock, patch

from tests.mocks import MockRAGClient, MockMemoryClient


@pytest.fixture
def mock_rag_client():
    """Create a mock RAG client."""
    return MockRAGClient()


@pytest.fixture
def mock_memory_client():
    """Create a mock Memory client."""
    return MockMemoryClient()


@pytest.fixture
def mock_sheets_client():
    """Create a mock Google Sheets client."""
    mock = MagicMock()
    mock.get_sheet_values.return_value = []
    mock.update_sheet_values.return_value = None
    mock.create_sheet.return_value = None
    return mock


@pytest.fixture
def mock_drive_client():
    """Create a mock Google Drive client."""
    mock = MagicMock()
    mock.create_folder_structure.return_value = {}
    mock.list_files.return_value = []
    return mock


@pytest.fixture
def mock_docs_client():
    """Create a mock Google Docs client."""
    mock = MagicMock()
    mock.get_document_text.return_value = ""
    mock.create_document.return_value = "new_doc_id"
    return mock


@pytest.fixture
def project_tools(mock_rag_client, mock_memory_client, mock_sheets_client, mock_drive_client):
    """Create ProjectTools with mock clients."""
    from spirrow_prismind.tools.project_tools import ProjectTools

    return ProjectTools(
        rag_client=mock_rag_client,
        memory_client=mock_memory_client,
        sheets_client=mock_sheets_client,
        drive_client=mock_drive_client,
        default_user="test_user",
    )


@pytest.fixture
def session_tools(mock_rag_client, mock_memory_client, mock_sheets_client, project_tools):
    """Create SessionTools with mock clients."""
    from spirrow_prismind.tools.session_tools import SessionTools

    return SessionTools(
        rag_client=mock_rag_client,
        memory_client=mock_memory_client,
        sheets_client=mock_sheets_client,
        project_tools=project_tools,
        default_user="test_user",
    )


@pytest.fixture
def document_tools(mock_rag_client, mock_sheets_client, mock_drive_client, mock_docs_client, project_tools):
    """Create DocumentTools with mock clients."""
    from spirrow_prismind.tools.document_tools import DocumentTools

    return DocumentTools(
        docs_client=mock_docs_client,
        drive_client=mock_drive_client,
        sheets_client=mock_sheets_client,
        rag_client=mock_rag_client,
        project_tools=project_tools,
        default_user="test_user",
    )


@pytest.fixture
def catalog_tools(mock_rag_client, mock_sheets_client, project_tools):
    """Create CatalogTools with mock clients."""
    from spirrow_prismind.tools.catalog_tools import CatalogTools

    return CatalogTools(
        rag_client=mock_rag_client,
        sheets_client=mock_sheets_client,
        project_tools=project_tools,
        default_user="test_user",
    )


@pytest.fixture
def knowledge_tools(mock_rag_client, project_tools):
    """Create KnowledgeTools with mock clients."""
    from spirrow_prismind.tools.knowledge_tools import KnowledgeTools

    return KnowledgeTools(
        rag_client=mock_rag_client,
        project_tools=project_tools,
        default_user="test_user",
    )


@pytest.fixture
def progress_tools(mock_sheets_client, mock_memory_client, project_tools):
    """Create ProgressTools with mock clients."""
    from spirrow_prismind.tools.progress_tools import ProgressTools

    return ProgressTools(
        sheets_client=mock_sheets_client,
        memory_client=mock_memory_client,
        project_tools=project_tools,
        default_user="test_user",
    )
