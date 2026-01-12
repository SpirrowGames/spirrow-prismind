"""Spirrow-Prismind data models."""

from .catalog import CatalogEntry, SearchCatalogResult, SyncCatalogResult
from .document import (
    CreateDocumentResult,
    DocReference,
    Document,
    DocumentResult,
    UpdateDocumentResult,
)
from .knowledge import AddKnowledgeResult, KnowledgeEntry, SearchKnowledgeResult
from .progress import (
    GetProgressResult,
    PhaseProgress,
    TaskDefinition,
    TaskProgress,
    UpdateProgressResult,
)
from .project import (
    DeleteProjectResult,
    DocsConfig,
    DriveConfig,
    ListProjectsResult,
    ProjectConfig,
    ProjectOptions,
    ProjectSummary,
    SetupProjectResult,
    SheetsConfig,
    SimilarProject,
    SwitchProjectResult,
    UpdateProjectResult,
)
from .session import (
    EndSessionResult,
    SaveSessionResult,
    SessionContext,
    SessionState,
)

__all__ = [
    # Catalog
    "CatalogEntry",
    "SearchCatalogResult",
    "SyncCatalogResult",
    # Document
    "CreateDocumentResult",
    "DocReference",
    "Document",
    "DocumentResult",
    "UpdateDocumentResult",
    # Knowledge
    "AddKnowledgeResult",
    "KnowledgeEntry",
    "SearchKnowledgeResult",
    # Progress
    "GetProgressResult",
    "PhaseProgress",
    "TaskDefinition",
    "TaskProgress",
    "UpdateProgressResult",
    # Project
    "DeleteProjectResult",
    "DocsConfig",
    "DriveConfig",
    "ListProjectsResult",
    "ProjectConfig",
    "ProjectOptions",
    "ProjectSummary",
    "SetupProjectResult",
    "SheetsConfig",
    "SimilarProject",
    "SwitchProjectResult",
    "UpdateProjectResult",
    # Session
    "EndSessionResult",
    "SaveSessionResult",
    "SessionContext",
    "SessionState",
]
