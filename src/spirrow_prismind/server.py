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
    ProjectTools,
    SessionTools,
)

logger = logging.getLogger(__name__)

# Tool definitions
TOOLS = [
    # Session Management
    Tool(
        name="start_session",
        description="セッションを開始し、保存されていた状態を読み込みます。プロジェクトを指定しない場合は現在のプロジェクトを使用します。",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "プロジェクトID（省略時は現在のプロジェクト）",
                },
            },
        },
    ),
    Tool(
        name="end_session",
        description="セッションを終了し、状態を保存します。",
        inputSchema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "このセッションの作業サマリ",
                },
                "next_action": {
                    "type": "string",
                    "description": "次にやるべきこと",
                },
                "blockers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "ブロッカー（障害）のリスト",
                },
                "notes": {
                    "type": "string",
                    "description": "次回セッションへのメモ",
                },
            },
        },
    ),
    Tool(
        name="save_session",
        description="セッション状態を保存します（終了せずに保存）。",
        inputSchema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "作業サマリ",
                },
                "next_action": {
                    "type": "string",
                    "description": "次にやるべきこと",
                },
                "blockers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "ブロッカーのリスト",
                },
                "notes": {
                    "type": "string",
                    "description": "メモ",
                },
                "current_phase": {
                    "type": "string",
                    "description": "現在のフェーズ",
                },
                "current_task": {
                    "type": "string",
                    "description": "現在のタスク",
                },
            },
        },
    ),
    # Project Management
    Tool(
        name="setup_project",
        description="新しいプロジェクトをセットアップします。重複チェックと類似プロジェクト検索を行います。",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "プロジェクトID（英数字）",
                },
                "name": {
                    "type": "string",
                    "description": "プロジェクト表示名",
                },
                "spreadsheet_id": {
                    "type": "string",
                    "description": "Google Sheets ID",
                },
                "root_folder_id": {
                    "type": "string",
                    "description": "Google Drive ルートフォルダID",
                },
                "description": {
                    "type": "string",
                    "description": "プロジェクトの説明",
                },
                "create_sheets": {
                    "type": "boolean",
                    "description": "シートを自動作成するか",
                    "default": True,
                },
                "create_folders": {
                    "type": "boolean",
                    "description": "フォルダを自動作成するか",
                    "default": True,
                },
                "force": {
                    "type": "boolean",
                    "description": "確認をスキップして強制作成",
                    "default": False,
                },
            },
            "required": ["project", "name", "spreadsheet_id", "root_folder_id"],
        },
    ),
    Tool(
        name="switch_project",
        description="別のプロジェクトに切り替えます。",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "切り替え先のプロジェクトID",
                },
            },
            "required": ["project"],
        },
    ),
    Tool(
        name="list_projects",
        description="登録されているプロジェクト一覧を取得します。",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="update_project",
        description="プロジェクト設定を更新します。",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "プロジェクトID",
                },
                "name": {
                    "type": "string",
                    "description": "新しい表示名",
                },
                "description": {
                    "type": "string",
                    "description": "新しい説明",
                },
                "spreadsheet_id": {
                    "type": "string",
                    "description": "新しいSpreadsheet ID",
                },
                "root_folder_id": {
                    "type": "string",
                    "description": "新しいルートフォルダID",
                },
            },
            "required": ["project"],
        },
    ),
    Tool(
        name="delete_project",
        description="プロジェクト設定を削除します（実データは残ります）。",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "プロジェクトID",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "削除確認（trueで削除実行）",
                    "default": False,
                },
            },
            "required": ["project"],
        },
    ),
    # Document Operations
    Tool(
        name="get_document",
        description="ドキュメントを検索・取得します。",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索クエリ",
                },
                "doc_id": {
                    "type": "string",
                    "description": "ドキュメントID（直接指定）",
                },
                "doc_type": {
                    "type": "string",
                    "description": "ドキュメント種別フィルタ",
                },
                "phase_task": {
                    "type": "string",
                    "description": "フェーズタスクフィルタ（例: P4-T01）",
                },
            },
        },
    ),
    Tool(
        name="create_document",
        description="新しいドキュメントを作成し、目録に登録します。",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "ドキュメント名",
                },
                "doc_type": {
                    "type": "string",
                    "description": "ドキュメント種別（設計書/実装手順書/etc.）",
                },
                "content": {
                    "type": "string",
                    "description": "ドキュメント内容",
                },
                "phase_task": {
                    "type": "string",
                    "description": "フェーズタスク（例: P4-T01）",
                },
                "feature": {
                    "type": "string",
                    "description": "フィーチャー名",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "検索キーワード",
                },
            },
            "required": ["name", "doc_type", "content", "phase_task"],
        },
    ),
    Tool(
        name="update_document",
        description="ドキュメントを更新します。",
        inputSchema={
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "ドキュメントID",
                },
                "content": {
                    "type": "string",
                    "description": "新しい内容",
                },
                "append": {
                    "type": "boolean",
                    "description": "追記するか（falseで置換）",
                    "default": False,
                },
            },
            "required": ["doc_id"],
        },
    ),
    # Catalog Operations
    Tool(
        name="search_catalog",
        description="目録を検索します。",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索クエリ",
                },
                "doc_type": {
                    "type": "string",
                    "description": "ドキュメント種別フィルタ",
                },
                "phase_task": {
                    "type": "string",
                    "description": "フェーズタスクフィルタ",
                },
                "feature": {
                    "type": "string",
                    "description": "フィーチャーフィルタ",
                },
                "limit": {
                    "type": "integer",
                    "description": "最大件数",
                    "default": 10,
                },
            },
        },
    ),
    Tool(
        name="sync_catalog",
        description="Google Sheetsの目録をRAGキャッシュに同期します。",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "プロジェクトID（省略時は現在のプロジェクト）",
                },
            },
        },
    ),
    # Knowledge Operations
    Tool(
        name="add_knowledge",
        description="知見をRAGに登録します。",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "知見の内容",
                },
                "category": {
                    "type": "string",
                    "description": "カテゴリ（問題解決/技術Tips/ベストプラクティス/落とし穴/設計パターン/その他）",
                },
                "project": {
                    "type": "string",
                    "description": "関連プロジェクト（省略で汎用知見）",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "検索タグ",
                },
                "source": {
                    "type": "string",
                    "description": "情報源",
                },
            },
            "required": ["content", "category"],
        },
    ),
    Tool(
        name="search_knowledge",
        description="知見を検索します。",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索クエリ",
                },
                "category": {
                    "type": "string",
                    "description": "カテゴリフィルタ",
                },
                "project": {
                    "type": "string",
                    "description": "プロジェクトフィルタ",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "タグフィルタ（AND条件）",
                },
                "include_general": {
                    "type": "boolean",
                    "description": "汎用知見も含めるか",
                    "default": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "最大件数",
                    "default": 5,
                },
            },
            "required": ["query"],
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
        self._project_tools: Optional[ProjectTools] = None
        self._session_tools: Optional[SessionTools] = None
        self._document_tools: Optional[DocumentTools] = None
        self._catalog_tools: Optional[CatalogTools] = None
        self._knowledge_tools: Optional[KnowledgeTools] = None
        
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

    async def _ensure_initialized(self):
        """Ensure the server is initialized."""
        if self._initialized:
            return
        
        # Load config
        config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
        self.config = load_config(Path(config_path))
        
        # Initialize clients
        self._rag_client = RAGClient(
            base_url=self.config.rag_url,
            collection_name=self.config.rag_collection,
        )
        
        self._memory_client = MemoryClient(
            base_url=self.config.memory_url,
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
                default_user=self.config.default_user,
            )
            
            self._session_tools = SessionTools(
                rag_client=self._rag_client,
                memory_client=self._memory_client,
                sheets_client=self._sheets_client,
                project_tools=self._project_tools,
                default_user=self.config.default_user,
            )
            
            self._document_tools = DocumentTools(
                docs_client=self._docs_client,
                drive_client=self._drive_client,
                sheets_client=self._sheets_client,
                rag_client=self._rag_client,
                project_tools=self._project_tools,
                default_user=self.config.default_user,
            )
            
            self._catalog_tools = CatalogTools(
                rag_client=self._rag_client,
                sheets_client=self._sheets_client,
                project_tools=self._project_tools,
                default_user=self.config.default_user,
            )
        
        self._knowledge_tools = KnowledgeTools(
            rag_client=self._rag_client,
            project_tools=self._project_tools,
            default_user=self.config.default_user,
        )
        
        self._initialized = True

    def _load_google_credentials(self):
        """Load Google OAuth credentials."""
        credentials_path = os.environ.get(
            "GOOGLE_CREDENTIALS_PATH",
            str(Path.home() / ".config" / "prismind" / "credentials.json"),
        )
        
        token_path = os.environ.get(
            "GOOGLE_TOKEN_PATH",
            str(Path.home() / ".config" / "prismind" / "token.json"),
        )
        
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
                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            
            # Refresh or get new credentials
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                elif os.path.exists(credentials_path):
                    flow = InstalledAppFlow.from_client_secrets_file(
                        credentials_path, SCOPES
                    )
                    creds = flow.run_local_server(port=0)
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
                spreadsheet_id=args["spreadsheet_id"],
                root_folder_id=args["root_folder_id"],
                description=args.get("description", ""),
                create_sheets=args.get("create_sheets", True),
                create_folders=args.get("create_folders", True),
                force=args.get("force", False),
            )
            return {
                "success": result.success,
                "project_id": result.project_id,
                "name": result.name,
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
            )
            return {
                "success": result.success,
                "project_id": result.project_id,
                "message": result.message,
            }
        
        # Document Operations
        elif name == "get_document":
            result = self._document_tools.get_document(
                query=args.get("query"),
                doc_id=args.get("doc_id"),
                doc_type=args.get("doc_type"),
                phase_task=args.get("phase_task"),
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
            result = self._document_tools.update_document(
                doc_id=args["doc_id"],
                content=args.get("content"),
                append=args.get("append", False),
            )
            return {
                "success": result.success,
                "doc_id": result.doc_id,
                "updated_fields": result.updated_fields,
                "message": result.message,
            }
        
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    server = PrismindServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
