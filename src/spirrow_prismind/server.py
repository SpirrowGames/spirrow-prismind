"""Spirrow-Prismind MCP Server."""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)

from .config import load_config
from .integrations import (
    GoogleDocsClient,
    GoogleDriveClient,
    GoogleSheetsClient,
    MemoryClient,
    RAGClient,
)
from .tools import (
    CatalogTools,
    DocumentTools,
    KnowledgeTools,
    ProgressTools,
    ProjectTools,
    SessionTools,
    SetupTools,
)

logger = logging.getLogger(__name__)

# Tool definitions
TOOLS = [
    # Setup Wizard
    Tool(
        name="get_setup_status",
        description="Get the configuration status of Spirrow-Prismind. Shows required and optional settings with their configured/unconfigured state.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="configure",
        description="Update Spirrow-Prismind configuration. Writes settings to config.toml.",
        inputSchema={
            "type": "object",
            "properties": {
                "setting": {
                    "type": "string",
                    "description": "Setting name (e.g., google.credentials_path, services.memory_server_url, session.user_name)",
                },
                "value": {
                    "type": "string",
                    "description": "Setting value",
                },
            },
            "required": ["setting", "value"],
        },
    ),
    Tool(
        name="check_services_status",
        description="Check connection status of RAG and Memory servers. Verifies server availability and collection/schema auto-creation status. Use detailed=true for protocol, latency, and other detailed info.",
        inputSchema={
            "type": "object",
            "properties": {
                "detailed": {
                    "type": "boolean",
                    "description": "Get detailed info (protocol, latency_ms, last_checked)",
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="get_connection_info",
        description="Get current connection information. Shows connection status, latency, and version info for Memory Server, RAG Server, and Google services.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="export_server_config",
        description="Export server configuration for team sharing. Outputs in TOML format excluding sensitive information (paths).",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="import_server_config",
        description="Import shared server configuration. Validates settings and reports any errors.",
        inputSchema={
            "type": "object",
            "properties": {
                "config": {
                    "type": "string",
                    "description": "Configuration content in TOML format",
                },
            },
            "required": ["config"],
        },
    ),
    # Session Management
    Tool(
        name="start_session",
        description="Start a session and load saved state. Uses current project if project is not specified.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project ID (uses current project if omitted)",
                },
            },
        },
    ),
    Tool(
        name="end_session",
        description="End the session and save state.",
        inputSchema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Work summary for this session",
                },
                "next_action": {
                    "type": "string",
                    "description": "Next action to take",
                },
                "blockers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of blockers (obstacles)",
                },
                "notes": {
                    "type": "string",
                    "description": "Notes for the next session",
                },
            },
        },
    ),
    Tool(
        name="save_session",
        description="Save session state without ending the session.",
        inputSchema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Work summary",
                },
                "next_action": {
                    "type": "string",
                    "description": "Next action to take",
                },
                "blockers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of blockers",
                },
                "notes": {
                    "type": "string",
                    "description": "Notes",
                },
                "current_phase": {
                    "type": "string",
                    "description": "Current phase",
                },
                "current_task": {
                    "type": "string",
                    "description": "Current task",
                },
            },
        },
    ),
    # Project Management
    Tool(
        name="setup_project",
        description="Set up a new project. If spreadsheet_id and root_folder_id are omitted, automatically creates them under the projects_folder_id configured in config.toml.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project ID (alphanumeric)",
                },
                "name": {
                    "type": "string",
                    "description": "Project display name",
                },
                "spreadsheet_id": {
                    "type": "string",
                    "description": "Google Sheets ID (auto-created if omitted)",
                },
                "root_folder_id": {
                    "type": "string",
                    "description": "Google Drive root folder ID (auto-created if omitted)",
                },
                "description": {
                    "type": "string",
                    "description": "Project description",
                },
                "create_sheets": {
                    "type": "boolean",
                    "description": "Auto-create sheets",
                    "default": True,
                },
                "create_folders": {
                    "type": "boolean",
                    "description": "Auto-create folders",
                    "default": True,
                },
                "force": {
                    "type": "boolean",
                    "description": "Skip confirmation and force create",
                    "default": False,
                },
            },
            "required": ["project", "name"],
        },
    ),
    Tool(
        name="switch_project",
        description="Switch to a different project.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Target project ID to switch to",
                },
            },
            "required": ["project"],
        },
    ),
    Tool(
        name="list_projects",
        description="Get a list of registered projects.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="update_project",
        description="Update project settings.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project ID",
                },
                "name": {
                    "type": "string",
                    "description": "New display name",
                },
                "description": {
                    "type": "string",
                    "description": "New description",
                },
                "spreadsheet_id": {
                    "type": "string",
                    "description": "New Spreadsheet ID",
                },
                "root_folder_id": {
                    "type": "string",
                    "description": "New root folder ID",
                },
                "status": {
                    "type": "string",
                    "description": "Project status (active, archived, etc.)",
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Project categories list",
                },
                "phases": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Project phases list",
                },
                "template": {
                    "type": "string",
                    "description": "Template type (game, mcp-server, web-app, etc.)",
                },
            },
            "required": ["project"],
        },
    ),
    Tool(
        name="delete_project",
        description="Delete project settings. Optionally delete the Google Drive folder as well.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project ID",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Delete confirmation (true to execute deletion)",
                    "default": False,
                },
                "delete_drive_folder": {
                    "type": "boolean",
                    "description": "If true, permanently delete the Google Drive folder (cannot be undone)",
                    "default": False,
                },
            },
            "required": ["project"],
        },
    ),
    Tool(
        name="sync_projects_from_drive",
        description="Sync folder list under projects_folder_id in Google Drive with RAG. Uses Drive as master to add/remove projects.",
        inputSchema={
            "type": "object",
            "properties": {
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, only report differences without making actual changes",
                    "default": False,
                },
            },
        },
    ),
    # Document Operations
    Tool(
        name="get_document",
        description="Search and retrieve a document.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "doc_id": {
                    "type": "string",
                    "description": "Document ID (direct specification)",
                },
                "doc_type": {
                    "type": "string",
                    "description": "Document type filter",
                },
                "phase_task": {
                    "type": "string",
                    "description": "Phase-task filter (e.g., P4-T01)",
                },
                "project": {
                    "type": "string",
                    "description": "Project ID (uses current project if omitted)",
                },
            },
        },
    ),
    Tool(
        name="create_document",
        description="Create a new document and register it in the catalog.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Document name",
                },
                "doc_type": {
                    "type": "string",
                    "description": "Document type (design_doc/implementation_guide/etc.)",
                },
                "content": {
                    "type": "string",
                    "description": "Document content",
                },
                "phase_task": {
                    "type": "string",
                    "description": "Phase-task (e.g., P4-T01)",
                },
                "feature": {
                    "type": "string",
                    "description": "Feature name",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Search keywords",
                },
                "project": {
                    "type": "string",
                    "description": "Project ID (uses current project if omitted)",
                },
            },
            "required": ["name", "doc_type", "content", "phase_task"],
        },
    ),
    Tool(
        name="update_document",
        description="Update a document.",
        inputSchema={
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "Document ID",
                },
                "content": {
                    "type": "string",
                    "description": "New content",
                },
                "append": {
                    "type": "boolean",
                    "description": "Append mode (false to replace)",
                    "default": False,
                },
                "doc_type": {
                    "type": "string",
                    "description": "New document type (moves to corresponding folder)",
                },
                "phase_task": {
                    "type": "string",
                    "description": "New phase-task value",
                },
                "feature": {
                    "type": "string",
                    "description": "New feature value",
                },
                "project": {
                    "type": "string",
                    "description": "Project ID (uses current project if omitted)",
                },
            },
            "required": ["doc_id"],
        },
    ),
    Tool(
        name="delete_document",
        description="Delete a document and its catalog entries. Requires project name to prevent accidental deletion.",
        inputSchema={
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "Document ID to delete",
                },
                "project": {
                    "type": "string",
                    "description": "Project name (required for safety)",
                },
                "delete_drive_file": {
                    "type": "boolean",
                    "description": "If true, also delete the Google Drive file",
                    "default": False,
                },
                "soft_delete": {
                    "type": "boolean",
                    "description": "If true, move to trash. If false, permanently delete.",
                    "default": True,
                },
            },
            "required": ["doc_id", "project"],
        },
    ),
    Tool(
        name="list_documents",
        description="List documents in a project with filtering and pagination.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project ID (uses current project if omitted)",
                },
                "doc_type": {
                    "type": "string",
                    "description": "Filter by document type",
                },
                "phase_task": {
                    "type": "string",
                    "description": "Filter by phase-task",
                },
                "feature": {
                    "type": "string",
                    "description": "Filter by feature",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 50,
                },
                "offset": {
                    "type": "integer",
                    "description": "Skip first N results",
                    "default": 0,
                },
                "sort_by": {
                    "type": "string",
                    "description": "Field to sort by (updated_at, name)",
                    "default": "updated_at",
                },
                "sort_order": {
                    "type": "string",
                    "description": "Sort order (asc, desc)",
                    "default": "desc",
                },
            },
        },
    ),
    # Document Type Management
    Tool(
        name="list_document_types",
        description="Get a list of available document types. Returns both global types (shared across projects) and project-specific types. When same type_id exists in both, project type takes precedence.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="register_document_type",
        description="Register a new document type. Use scope='global' for types shared across all projects, or scope='project' for project-specific types.",
        inputSchema={
            "type": "object",
            "properties": {
                "type_id": {
                    "type": "string",
                    "description": "Type ID (alphanumeric and underscore, e.g., meeting_notes)",
                },
                "name": {
                    "type": "string",
                    "description": "Display name (e.g., Meeting Notes)",
                },
                "folder_name": {
                    "type": "string",
                    "description": "Folder name in Google Drive",
                },
                "scope": {
                    "type": "string",
                    "enum": ["global", "project"],
                    "description": "Type scope: 'global' for shared across projects, 'project' for current project only",
                    "default": "global",
                },
                "template_doc_id": {
                    "type": "string",
                    "description": "Google Docs template ID (optional)",
                },
                "description": {
                    "type": "string",
                    "description": "Document type description",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Custom metadata fields",
                },
                "create_folder": {
                    "type": "boolean",
                    "description": "Auto-create folder (only applies to project scope)",
                    "default": True,
                },
            },
            "required": ["type_id", "name", "folder_name"],
        },
    ),
    Tool(
        name="delete_document_type",
        description="Delete a document type. Use scope='global' for global types, or scope='project' for project-specific types.",
        inputSchema={
            "type": "object",
            "properties": {
                "type_id": {
                    "type": "string",
                    "description": "Type ID to delete",
                },
                "scope": {
                    "type": "string",
                    "enum": ["global", "project"],
                    "description": "Type scope to delete from: 'global' or 'project'",
                    "default": "global",
                },
            },
            "required": ["type_id"],
        },
    ),
    Tool(
        name="find_similar_document_type",
        description="Find a document type semantically similar to the query. Uses RAG-based semantic search (BGE-M3 embeddings) for multilingual matching. For example, 'api仕様' can match 'api_spec'.",
        inputSchema={
            "type": "object",
            "properties": {
                "type_query": {
                    "type": "string",
                    "description": "Search query (type name, ID, or description in any language)",
                },
                "threshold": {
                    "type": "number",
                    "description": "Minimum similarity score (0.0-1.0)",
                    "default": 0.75,
                },
            },
            "required": ["type_query"],
        },
    ),
    # Catalog Operations
    Tool(
        name="search_catalog",
        description="Search the document catalog.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "doc_type": {
                    "type": "string",
                    "description": "Document type filter",
                },
                "phase_task": {
                    "type": "string",
                    "description": "Phase-task filter",
                },
                "feature": {
                    "type": "string",
                    "description": "Feature filter",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 10,
                },
            },
        },
    ),
    Tool(
        name="sync_catalog",
        description="Sync the catalog from Google Sheets to RAG cache.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project ID (uses current project if omitted)",
                },
            },
        },
    ),
    # Knowledge Operations
    Tool(
        name="add_knowledge",
        description="Add a knowledge entry to RAG. Store insights, tips, best practices, and lessons learned.",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Knowledge content",
                },
                "category": {
                    "type": "string",
                    "description": "Category (problem_solving/tech_tips/best_practices/pitfalls/design_patterns/other)",
                },
                "project": {
                    "type": "string",
                    "description": "Related project (omit for general knowledge)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Search tags",
                },
                "source": {
                    "type": "string",
                    "description": "Information source",
                },
            },
            "required": ["content", "category"],
        },
    ),
    Tool(
        name="search_knowledge",
        description="Search knowledge entries. Find relevant insights, tips, and lessons learned.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "category": {
                    "type": "string",
                    "description": "Category filter",
                },
                "project": {
                    "type": "string",
                    "description": "Project filter",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tag filter (AND condition)",
                },
                "include_general": {
                    "type": "boolean",
                    "description": "Include general (non-project) knowledge",
                    "default": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="update_knowledge",
        description="Update an existing knowledge entry.",
        inputSchema={
            "type": "object",
            "properties": {
                "knowledge_id": {
                    "type": "string",
                    "description": "Knowledge entry ID to update",
                },
                "content": {
                    "type": "string",
                    "description": "New content (omit to keep unchanged)",
                },
                "category": {
                    "type": "string",
                    "description": "New category (omit to keep unchanged)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New tags (omit to keep unchanged)",
                },
                "source": {
                    "type": "string",
                    "description": "New source (omit to keep unchanged)",
                },
            },
            "required": ["knowledge_id"],
        },
    ),
    # Progress Management
    Tool(
        name="get_progress",
        description="Get project progress from Google Sheets.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project ID (uses current project if omitted)",
                },
                "phase": {
                    "type": "string",
                    "description": "Phase filter (omit for all phases)",
                },
            },
        },
    ),
    Tool(
        name="update_task_status",
        description="Update task status in Google Sheets.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID (e.g., T01)",
                },
                "status": {
                    "type": "string",
                    "description": "New status (not_started/in_progress/completed/blocked)",
                },
                "phase": {
                    "type": "string",
                    "description": "Phase name (specify when task_id is ambiguous)",
                },
                "blockers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Blocker list",
                },
                "notes": {
                    "type": "string",
                    "description": "Notes",
                },
                "project": {
                    "type": "string",
                    "description": "Project ID",
                },
            },
            "required": ["task_id", "status"],
        },
    ),
    Tool(
        name="add_task",
        description="Add a new task to the progress sheet.",
        inputSchema={
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "description": "Phase name (e.g., Phase 4)",
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID (e.g., T01)",
                },
                "name": {
                    "type": "string",
                    "description": "Task name",
                },
                "description": {
                    "type": "string",
                    "description": "Task description",
                },
                "project": {
                    "type": "string",
                    "description": "Project ID",
                },
            },
            "required": ["phase", "task_id", "name"],
        },
    ),
    # Summary Operations
    Tool(
        name="update_summary",
        description="Update the project summary sheet with information like description, current phase, and task counts.",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project ID (uses current project if omitted)",
                },
                "description": {
                    "type": "string",
                    "description": "Project description",
                },
                "current_phase": {
                    "type": "string",
                    "description": "Current phase name",
                },
                "completed_tasks": {
                    "type": "integer",
                    "description": "Number of completed tasks",
                },
                "total_tasks": {
                    "type": "integer",
                    "description": "Total number of tasks",
                },
                "custom_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Custom key-value pairs to add/update",
                },
            },
        },
    ),
]


class PrismindServer:
    """Spirrow-Prismind MCP Server."""

    def __init__(self):
        """Initialize the server."""
        self.server = Server("spirrow-prismind")
        self.config = None
        self._initialized = False
        
        # Clients (initialized lazily)
        self._rag_client: Optional[RAGClient] = None
        self._memory_client: Optional[MemoryClient] = None
        self._sheets_client: Optional[GoogleSheetsClient] = None
        self._docs_client: Optional[GoogleDocsClient] = None
        self._drive_client: Optional[GoogleDriveClient] = None
        
        # Tools (initialized lazily)
        self._setup_tools: Optional[SetupTools] = None
        self._project_tools: Optional[ProjectTools] = None
        self._session_tools: Optional[SessionTools] = None
        self._document_tools: Optional[DocumentTools] = None
        self._catalog_tools: Optional[CatalogTools] = None
        self._knowledge_tools: Optional[KnowledgeTools] = None
        self._progress_tools: Optional[ProgressTools] = None

        # Register handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register MCP handlers."""
        
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return TOOLS
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            return await self._handle_tool_call(name, arguments)

    async def _ensure_initialized(self, timeout: float = 30.0):
        """Ensure the server is initialized.

        Args:
            timeout: Initialization timeout in seconds
        """
        if self._initialized:
            return

        import asyncio
        try:
            await asyncio.wait_for(self._do_initialization(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"Server initialization timed out after {timeout} seconds")
            self._initialized = True  # Mark as initialized to prevent retry loops
            raise RuntimeError(f"Initialization timeout after {timeout}s. Check credentials and server connections.")

    async def _do_initialization(self):
        """Perform actual initialization."""
        
        # Load config
        config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
        self.config = load_config(Path(config_path))
        
        # Initialize clients (they will check connectivity and mark themselves as unavailable if needed)
        self._rag_client = RAGClient(
            base_url=self.config.rag_url,
            collection_name=self.config.rag_collection,
            connect_timeout=3.0,
        )

        self._memory_client = MemoryClient(
            base_url=self.config.memory_url,
            connect_timeout=3.0,
            protocol=self.config.memory_type,
        )

        # Log service availability (RAG/Memory are optional)
        if not self._rag_client.is_available:
            logger.info(
                "RAG server is not available (optional). "
                "Project data will be stored locally. "
                "Knowledge/catalog search features will be limited."
            )
        if not self._memory_client.is_available:
            logger.info(
                "Memory server is not available (optional). "
                "Session state will use local file storage."
            )
        
        # Google clients require OAuth credentials
        # For now, we'll use a placeholder - actual implementation
        # would load credentials from file or environment
        credentials = self._load_google_credentials()
        
        if credentials:
            self._sheets_client = GoogleSheetsClient(credentials)
            self._docs_client = GoogleDocsClient(credentials)
            self._drive_client = GoogleDriveClient(credentials)
        
        # Initialize tools
        if self._sheets_client and self._drive_client:
            self._project_tools = ProjectTools(
                rag_client=self._rag_client,
                memory_client=self._memory_client,
                sheets_client=self._sheets_client,
                drive_client=self._drive_client,
                user_name=self.config.user_name,
                projects_folder_id=self.config.projects_folder_id,
            )
            
            self._session_tools = SessionTools(
                rag_client=self._rag_client,
                memory_client=self._memory_client,
                sheets_client=self._sheets_client,
                project_tools=self._project_tools,
                user_name=self.config.user_name,
            )
            
            self._document_tools = DocumentTools(
                docs_client=self._docs_client,
                drive_client=self._drive_client,
                sheets_client=self._sheets_client,
                rag_client=self._rag_client,
                project_tools=self._project_tools,
                user_name=self.config.user_name,
            )
            
            self._catalog_tools = CatalogTools(
                rag_client=self._rag_client,
                sheets_client=self._sheets_client,
                project_tools=self._project_tools,
                user_name=self.config.user_name,
            )

            self._progress_tools = ProgressTools(
                sheets_client=self._sheets_client,
                memory_client=self._memory_client,
                project_tools=self._project_tools,
                user_name=self.config.user_name,
            )

        self._knowledge_tools = KnowledgeTools(
            rag_client=self._rag_client,
            project_tools=self._project_tools,
            memory_client=self._memory_client,
            user_name=self.config.user_name,
        )
        
        self._initialized = True

    def _load_google_credentials(self):
        """Load Google OAuth credentials."""
        # Use paths from config.toml, with environment variable override
        config_dir = Path(os.environ.get("PRISMIND_CONFIG", "config.toml")).parent

        # Resolve credentials path
        credentials_path = os.environ.get("GOOGLE_CREDENTIALS_PATH")
        if not credentials_path and self.config:
            cred_path = Path(self.config.google.credentials_path)
            if not cred_path.is_absolute():
                cred_path = config_dir / cred_path
            credentials_path = str(cred_path)
        if not credentials_path:
            credentials_path = str(Path.home() / ".config" / "prismind" / "credentials.json")

        # Resolve token path
        token_path = os.environ.get("GOOGLE_TOKEN_PATH")
        if not token_path and self.config:
            tok_path = Path(self.config.google.token_path)
            if not tok_path.is_absolute():
                tok_path = config_dir / tok_path
            token_path = str(tok_path)
        if not token_path:
            token_path = str(Path.home() / ".config" / "prismind" / "token.json")
        
        logger.info(f"Looking for credentials at: {credentials_path}")
        logger.info(f"Looking for token at: {token_path}")

        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow

            SCOPES = [
                "https://www.googleapis.com/auth/documents",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/spreadsheets",
            ]

            creds = None

            # Load existing token
            if os.path.exists(token_path):
                logger.info(f"Found existing token at {token_path}")
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            
            # Refresh or get new credentials
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    logger.info("Refreshing expired token")
                    creds.refresh(Request())
                elif os.path.exists(credentials_path):
                    logger.info(f"Found credentials.json at {credentials_path}, starting OAuth flow")
                    logger.warning(
                        "OAuth requires browser authentication. "
                        "If running as MCP server, run 'python -c \"from spirrow_prismind.server import PrismindServer; import asyncio; asyncio.run(PrismindServer()._ensure_initialized())\"' first to authenticate."
                    )
                    flow = InstalledAppFlow.from_client_secrets_file(
                        credentials_path, SCOPES
                    )
                    # Set timeout for OAuth flow (60 seconds)
                    creds = flow.run_local_server(port=0, timeout_seconds=60)
                    logger.info("OAuth flow completed successfully")
                else:
                    logger.warning(
                        f"Google credentials not found at {credentials_path}. "
                        "Google API features will be disabled."
                    )
                    return None
                
                # Save the credentials for next run
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                with open(token_path, "w") as token:
                    token.write(creds.to_json())
            
            return creds
            
        except Exception as e:
            logger.warning(f"Failed to load Google credentials: {e}")
            return None

    async def _handle_tool_call(
        self,
        name: str,
        arguments: dict,
    ) -> list[TextContent]:
        """Handle a tool call."""
        await self._ensure_initialized()
        
        try:
            result = await self._dispatch_tool(name, arguments)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
        except Exception as e:
            logger.exception(f"Tool call failed: {name}")
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": str(e),
            }, ensure_ascii=False))]

    async def _dispatch_tool(self, name: str, args: dict) -> dict:
        """Dispatch tool call to appropriate handler."""

        # Setup tools - always available (before full initialization)
        if name == "get_setup_status":
            if not self._setup_tools:
                config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
                self._setup_tools = SetupTools(config_path)

            result = self._setup_tools.get_setup_status()
            return {
                "success": result.success,
                "ready": result.ready,
                "required_settings": [
                    {
                        "name": s.name,
                        "required": s.required,
                        "configured": s.configured,
                        "current_value": s.current_value,
                        "default_value": s.default_value,
                        "description": s.description,
                        "benefit": s.benefit,
                    }
                    for s in result.required_settings
                ],
                "optional_settings": [
                    {
                        "name": s.name,
                        "required": s.required,
                        "configured": s.configured,
                        "current_value": s.current_value,
                        "default_value": s.default_value,
                        "description": s.description,
                        "benefit": s.benefit,
                    }
                    for s in result.optional_settings
                ],
                "config_file_path": result.config_file_path,
                "config_file_exists": result.config_file_exists,
                "message": result.message,
            }

        elif name == "configure":
            if not self._setup_tools:
                config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
                self._setup_tools = SetupTools(config_path)

            result = self._setup_tools.configure(
                setting=args["setting"],
                value=args["value"],
            )
            return {
                "success": result.success,
                "setting_name": result.setting_name,
                "old_value": result.old_value,
                "new_value": result.new_value,
                "validation_errors": result.validation_errors,
                "message": result.message,
            }

        elif name == "check_services_status":
            if not self._setup_tools:
                config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
                self._setup_tools = SetupTools(config_path)

            detailed = args.get("detailed", False)
            result = self._setup_tools.check_services_status(detailed=detailed)
            services_data = []
            for s in result.services:
                service_dict = {
                    "name": s.name,
                    "available": s.available,
                    "url": s.url,
                    "message": s.message,
                }
                if detailed:
                    service_dict["protocol"] = s.protocol
                    service_dict["latency_ms"] = s.latency_ms
                    service_dict["version"] = s.version
                    service_dict["last_checked"] = s.last_checked
                services_data.append(service_dict)

            return {
                "success": result.success,
                "services": services_data,
                "all_available": result.all_required_available,
                "message": result.message,
            }

        elif name == "get_connection_info":
            if not self._setup_tools:
                config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
                self._setup_tools = SetupTools(config_path)

            result = self._setup_tools.get_connection_info()
            response = {
                "success": result.success,
                "message": result.message,
            }
            if result.memory_server:
                response["memory_server"] = {
                    "name": result.memory_server.name,
                    "url": result.memory_server.url,
                    "protocol": result.memory_server.protocol,
                    "status": result.memory_server.status,
                    "latency_ms": result.memory_server.latency_ms,
                    "version": result.memory_server.version,
                    "last_checked": result.memory_server.last_checked,
                }
            if result.rag_server:
                response["rag_server"] = {
                    "name": result.rag_server.name,
                    "url": result.rag_server.url,
                    "protocol": result.rag_server.protocol,
                    "status": result.rag_server.status,
                    "latency_ms": result.rag_server.latency_ms,
                    "version": result.rag_server.version,
                    "collection": result.rag_server.collection,
                    "last_checked": result.rag_server.last_checked,
                }
            if result.google:
                response["google"] = {
                    "authenticated": result.google.authenticated,
                    "user": result.google.user,
                    "scopes": result.google.scopes,
                }
            return response

        elif name == "export_server_config":
            if not self._setup_tools:
                config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
                self._setup_tools = SetupTools(config_path)

            result = self._setup_tools.export_server_config()
            return {
                "success": result.success,
                "config": result.config,
                "message": result.message,
            }

        elif name == "import_server_config":
            if not self._setup_tools:
                config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
                self._setup_tools = SetupTools(config_path)

            result = self._setup_tools.import_server_config(
                config=args["config"],
            )
            return {
                "success": result.success,
                "imported_settings": result.imported_settings,
                "skipped_settings": result.skipped_settings,
                "validation_errors": result.validation_errors,
                "message": result.message,
            }

        # Check if required tools are initialized
        google_required_tools = [
            "start_session", "end_session", "save_session", "update_summary",
            "setup_project", "switch_project", "list_projects",
            "update_project", "delete_project", "sync_projects_from_drive",
            "get_document", "create_document", "update_document",
            "delete_document", "list_documents",
            "list_document_types", "register_document_type", "delete_document_type",
            "find_similar_document_type",
            "search_catalog", "sync_catalog",
            "get_progress", "update_task_status", "add_task",
        ]

        if name in google_required_tools and not self._project_tools:
            return {
                "success": False,
                "error": "Google認証が完了していません。token.jsonが存在するか確認し、サーバーを再起動してください。",
            }

        # Session Management
        if name == "start_session":
            result = self._session_tools.start_session(
                project=args.get("project"),
            )
            return {
                "success": True,
                "project": result.project,
                "project_name": result.project_name,
                "current_phase": result.current_phase,
                "current_task": result.current_task,
                "last_completed": result.last_completed,
                "blockers": result.blockers,
                "recommended_docs": [
                    {"name": d.name, "doc_id": d.doc_id, "reason": d.reason}
                    for d in result.recommended_docs
                ],
                "notes": result.notes,
            }
        
        elif name == "end_session":
            result = self._session_tools.end_session(
                summary=args.get("summary"),
                next_action=args.get("next_action"),
                blockers=args.get("blockers"),
                notes=args.get("notes"),
            )
            return {
                "success": result.success,
                "session_duration": str(result.session_duration),
                "saved_to": result.saved_to,
                "message": result.message,
            }
        
        elif name == "save_session":
            result = self._session_tools.save_session(
                summary=args.get("summary"),
                next_action=args.get("next_action"),
                blockers=args.get("blockers"),
                notes=args.get("notes"),
                current_phase=args.get("current_phase"),
                current_task=args.get("current_task"),
            )
            return {
                "success": result.success,
                "saved_to": result.saved_to,
                "message": result.message,
            }
        
        # Project Management
        elif name == "setup_project":
            result = self._project_tools.setup_project(
                project=args["project"],
                name=args["name"],
                spreadsheet_id=args.get("spreadsheet_id"),
                root_folder_id=args.get("root_folder_id"),
                description=args.get("description", ""),
                create_sheets=args.get("create_sheets", True),
                create_folders=args.get("create_folders", True),
                force=args.get("force", False),
            )
            return {
                "success": result.success,
                "project_id": result.project_id,
                "name": result.name,
                "spreadsheet_id": result.spreadsheet_id,
                "root_folder_id": result.root_folder_id,
                "sheets_created": result.sheets_created,
                "folders_created": result.folders_created,
                "requires_confirmation": result.requires_confirmation,
                "duplicate_id": result.duplicate_id,
                "duplicate_name": result.duplicate_name,
                "similar_projects": [
                    {
                        "project_id": sp.project_id,
                        "name": sp.name,
                        "similarity": sp.similarity_percent,
                    }
                    for sp in result.similar_projects
                ],
                "message": result.message,
            }
        
        elif name == "switch_project":
            result = self._project_tools.switch_project(
                project=args["project"],
            )
            return {
                "success": result.success,
                "project_id": result.project_id,
                "name": result.name,
                "message": result.message,
            }
        
        elif name == "list_projects":
            result = self._project_tools.list_projects()
            return {
                "success": result.success,
                "projects": [
                    {
                        "project_id": p.project_id,
                        "name": p.name,
                        "description": p.description,
                        "updated_at": p.updated_at.isoformat(),
                        "status": p.status,
                    }
                    for p in result.projects
                ],
                "current_project": result.current_project,
                "message": result.message,
            }
        
        elif name == "update_project":
            result = self._project_tools.update_project(
                project=args["project"],
                name=args.get("name"),
                description=args.get("description"),
                spreadsheet_id=args.get("spreadsheet_id"),
                root_folder_id=args.get("root_folder_id"),
                status=args.get("status"),
                categories=args.get("categories"),
                phases=args.get("phases"),
                template=args.get("template"),
            )
            return {
                "success": result.success,
                "project_id": result.project_id,
                "updated_fields": result.updated_fields,
                "message": result.message,
            }
        
        elif name == "delete_project":
            result = self._project_tools.delete_project(
                project=args["project"],
                confirm=args.get("confirm", False),
                delete_drive_folder=args.get("delete_drive_folder", False),
            )
            return {
                "success": result.success,
                "project_id": result.project_id,
                "message": result.message,
                "drive_folder_deleted": result.drive_folder_deleted,
            }

        elif name == "sync_projects_from_drive":
            result = self._project_tools.sync_projects_from_drive(
                dry_run=args.get("dry_run", False),
            )
            return {
                "success": result.success,
                "added": result.added,
                "removed": result.removed,
                "unchanged": result.unchanged,
                "errors": result.errors,
                "message": result.message,
            }

        # Document Operations
        elif name == "get_document":
            result = self._document_tools.get_document(
                query=args.get("query"),
                doc_id=args.get("doc_id"),
                doc_type=args.get("doc_type"),
                phase_task=args.get("phase_task"),
                project=args.get("project"),
            )
            
            response = {
                "found": result.found,
                "message": result.message,
            }
            
            if result.document:
                response["document"] = {
                    "doc_id": result.document.doc_id,
                    "name": result.document.name,
                    "doc_type": result.document.doc_type,
                    "content": result.document.content,
                    "source": result.document.source,
                    "metadata": result.document.metadata,
                }
            
            if result.candidates:
                response["candidates"] = [
                    {"name": c.name, "doc_id": c.doc_id, "reason": c.reason}
                    for c in result.candidates
                ]
            
            return response
        
        elif name == "create_document":
            result = self._document_tools.create_document(
                name=args["name"],
                doc_type=args["doc_type"],
                content=args["content"],
                phase_task=args["phase_task"],
                feature=args.get("feature"),
                keywords=args.get("keywords"),
                project=args.get("project"),
            )
            return {
                "success": result.success,
                "doc_id": result.doc_id,
                "name": result.name,
                "doc_url": result.doc_url,
                "source": result.source,
                "catalog_registered": result.catalog_registered,
                "message": result.message,
            }
        
        elif name == "update_document":
            # Build metadata dict for extended fields
            metadata = {}
            if args.get("doc_type"):
                metadata["doc_type"] = args["doc_type"]
            if args.get("phase_task"):
                metadata["phase_task"] = args["phase_task"]
            if args.get("feature"):
                metadata["feature"] = args["feature"]

            result = self._document_tools.update_document(
                doc_id=args["doc_id"],
                content=args.get("content"),
                append=args.get("append", False),
                metadata=metadata if metadata else None,
                project=args.get("project"),
            )
            return {
                "success": result.success,
                "doc_id": result.doc_id,
                "updated_fields": result.updated_fields,
                "message": result.message,
            }

        elif name == "delete_document":
            result = self._document_tools.delete_document(
                doc_id=args["doc_id"],
                project=args["project"],
                delete_drive_file=args.get("delete_drive_file", False),
                soft_delete=args.get("soft_delete", True),
            )
            return {
                "success": result.success,
                "doc_id": result.doc_id,
                "project": result.project,
                "catalog_deleted": result.catalog_deleted,
                "sheet_row_deleted": result.sheet_row_deleted,
                "drive_file_deleted": result.drive_file_deleted,
                "knowledge_deleted_count": result.knowledge_deleted_count,
                "message": result.message,
            }

        elif name == "list_documents":
            result = self._document_tools.list_documents(
                project=args.get("project"),
                doc_type=args.get("doc_type"),
                phase_task=args.get("phase_task"),
                feature=args.get("feature"),
                limit=args.get("limit", 50),
                offset=args.get("offset", 0),
                sort_by=args.get("sort_by", "updated_at"),
                sort_order=args.get("sort_order", "desc"),
            )
            return {
                "success": result.success,
                "documents": [
                    {
                        "doc_id": d.doc_id,
                        "name": d.name,
                        "doc_type": d.doc_type,
                        "phase_task": d.phase_task,
                        "feature": d.feature,
                        "source": d.source,
                        "url": d.url,
                        "updated_at": d.updated_at,
                    }
                    for d in result.documents
                ],
                "total_count": result.total_count,
                "offset": result.offset,
                "limit": result.limit,
                "message": result.message,
            }

        # Document Type Management
        elif name == "list_document_types":
            result = self._document_tools.list_document_types()
            return {
                "success": result.success,
                "document_types": [
                    {
                        "type_id": dt.type_id,
                        "name": dt.name,
                        "folder_name": dt.folder_name,
                        "template_doc_id": dt.template_doc_id,
                        "description": dt.description,
                        "fields": dt.fields,
                        "is_global": dt.is_global,
                    }
                    for dt in result.document_types
                ],
                "message": result.message,
            }

        elif name == "register_document_type":
            result = self._document_tools.register_document_type(
                type_id=args["type_id"],
                name=args["name"],
                folder_name=args["folder_name"],
                scope=args.get("scope", "global"),
                template_doc_id=args.get("template_doc_id"),
                description=args.get("description"),
                fields=args.get("fields"),
                create_folder=args.get("create_folder", True),
            )
            return {
                "success": result.success,
                "type_id": result.type_id,
                "name": result.name,
                "folder_created": result.folder_created,
                "message": result.message,
            }

        elif name == "delete_document_type":
            result = self._document_tools.delete_document_type(
                type_id=args["type_id"],
                scope=args.get("scope", "global"),
            )
            return {
                "success": result.success,
                "type_id": result.type_id,
                "message": result.message,
            }

        elif name == "find_similar_document_type":
            result = self._document_tools.find_similar_document_type(
                type_query=args["type_query"],
                threshold=args.get("threshold", 0.75),
            )
            return result

        # Catalog Operations
        elif name == "search_catalog":
            result = self._catalog_tools.search_catalog(
                query=args.get("query"),
                doc_type=args.get("doc_type"),
                phase_task=args.get("phase_task"),
                feature=args.get("feature"),
                limit=args.get("limit", 10),
            )
            return {
                "success": result.success,
                "total_count": result.total_count,
                "documents": [
                    {
                        "doc_id": d.doc_id,
                        "name": d.name,
                        "doc_type": d.doc_type,
                        "phase_task": d.phase_task,
                        "feature": d.feature,
                        "source": d.source,
                    }
                    for d in result.documents
                ],
                "message": result.message,
            }
        
        elif name == "sync_catalog":
            result = self._catalog_tools.sync_catalog(
                project=args.get("project"),
            )
            return {
                "success": result.success,
                "synced_count": result.synced_count,
                "message": result.message,
            }
        
        # Knowledge Operations
        elif name == "add_knowledge":
            result = self._knowledge_tools.add_knowledge(
                content=args["content"],
                category=args["category"],
                project=args.get("project"),
                tags=args.get("tags"),
                source=args.get("source"),
            )
            return {
                "success": result.success,
                "knowledge_id": result.knowledge_id,
                "tags": result.tags,
                "message": result.message,
            }
        
        elif name == "search_knowledge":
            result = self._knowledge_tools.search_knowledge(
                query=args["query"],
                category=args.get("category"),
                project=args.get("project"),
                tags=args.get("tags"),
                include_general=args.get("include_general", True),
                limit=args.get("limit", 5),
            )
            return {
                "success": result.success,
                "total_count": result.total_count,
                "knowledge": [
                    {
                        "knowledge_id": k.knowledge_id,
                        "content": k.content,
                        "category": k.category,
                        "project": k.project,
                        "tags": k.tags,
                        "source": k.source,
                        "relevance_score": k.relevance_score,
                    }
                    for k in result.knowledge
                ],
                "message": result.message,
            }

        elif name == "update_knowledge":
            result = self._knowledge_tools.update_knowledge(
                knowledge_id=args["knowledge_id"],
                content=args.get("content"),
                category=args.get("category"),
                tags=args.get("tags"),
                source=args.get("source"),
            )
            return {
                "success": result.success,
                "knowledge_id": result.knowledge_id,
                "updated_fields": result.updated_fields,
                "message": result.message,
            }

        # Progress Management
        elif name == "get_progress":
            if not self._progress_tools:
                return {"success": False, "error": "Progress tools not initialized"}
            result = self._progress_tools.get_progress(
                project=args.get("project"),
                phase=args.get("phase"),
            )
            return {
                "success": result.success,
                "project": result.project,
                "current_phase": result.current_phase,
                "phases": [
                    {
                        "phase": p.phase,
                        "status": p.status,
                        "tasks": [
                            {
                                "task_id": t.task_id,
                                "name": t.name,
                                "status": t.status,
                                "blockers": t.blockers,
                                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                                "notes": t.notes,
                            }
                            for t in p.tasks
                        ],
                    }
                    for p in result.phases
                ],
                "message": result.message,
            }

        elif name == "update_task_status":
            if not self._progress_tools:
                return {"success": False, "error": "Progress tools not initialized"}
            result = self._progress_tools.update_task_status(
                task_id=args["task_id"],
                status=args["status"],
                phase=args.get("phase"),
                blockers=args.get("blockers"),
                notes=args.get("notes"),
                project=args.get("project"),
            )
            return {
                "success": result.success,
                "project": result.project,
                "task_id": result.task_id,
                "updated_fields": result.updated_fields,
                "message": result.message,
            }

        elif name == "add_task":
            if not self._progress_tools:
                return {"success": False, "error": "Progress tools not initialized"}
            result = self._progress_tools.add_task(
                phase=args["phase"],
                task_id=args["task_id"],
                name=args["name"],
                description=args.get("description", ""),
                project=args.get("project"),
            )
            return {
                "success": result.success,
                "project": result.project,
                "task_id": result.task_id,
                "updated_fields": result.updated_fields,
                "message": result.message,
            }

        # Summary Operations
        elif name == "update_summary":
            if not self._session_tools:
                return {"success": False, "error": "Session tools not initialized"}
            result = self._session_tools.update_summary(
                project=args.get("project"),
                description=args.get("description"),
                current_phase=args.get("current_phase"),
                completed_tasks=args.get("completed_tasks"),
                total_tasks=args.get("total_tasks"),
                custom_fields=args.get("custom_fields"),
            )
            return {
                "success": result.success,
                "project": result.project,
                "updated_fields": result.updated_fields,
                "message": result.message,
            }

        else:
            return {"success": False, "error": f"Unknown tool: {name}"}

    async def run(self):
        """Run the server."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


def main():
    """Entry point."""
    # Load config first to setup logging correctly
    config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
    config = load_config(Path(config_path))
    config.setup_logging()

    server = PrismindServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
