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
        description="Spirrow-Prismindの設定状況を確認します。必須設定とオプション設定の一覧、設定済み/未設定の状態を表示します。",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="configure",
        description="Spirrow-Prismindの設定を変更します。config.tomlに設定を書き込みます。",
        inputSchema={
            "type": "object",
            "properties": {
                "setting": {
                    "type": "string",
                    "description": "設定名（例: google.credentials_path, services.memory_server_url, session.user_name）",
                },
                "value": {
                    "type": "string",
                    "description": "設定値",
                },
            },
            "required": ["setting", "value"],
        },
    ),
    Tool(
        name="check_services_status",
        description="RAGサーバーとMemoryサーバーの接続状態を確認します。サーバーが利用可能かどうか、コレクション/スキーマの自動作成状態も確認できます。detailed=trueでプロトコル、レイテンシ等の詳細情報を取得できます。",
        inputSchema={
            "type": "object",
            "properties": {
                "detailed": {
                    "type": "boolean",
                    "description": "詳細情報を取得するか（protocol, latency_ms, last_checked）",
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="get_connection_info",
        description="現在の接続情報を取得します。Memory Server、RAG Server、Googleサービスの接続状態、レイテンシ、バージョン情報を表示します。",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="export_server_config",
        description="チームで共有可能なサーバー設定をエクスポートします。機密情報（パス）を除いたTOML形式で出力します。",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="import_server_config",
        description="共有されたサーバー設定をインポートします。設定の検証を行い、エラーがあれば報告します。",
        inputSchema={
            "type": "object",
            "properties": {
                "config": {
                    "type": "string",
                    "description": "TOML形式の設定内容",
                },
            },
            "required": ["config"],
        },
    ),
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
        description="新しいプロジェクトをセットアップします。spreadsheet_idとroot_folder_idを省略すると、config.tomlのprojects_folder_id配下に自動作成します。",
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
                    "description": "Google Sheets ID（省略時は自動作成）",
                },
                "root_folder_id": {
                    "type": "string",
                    "description": "Google Drive ルートフォルダID（省略時は自動作成）",
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
            "required": ["project", "name"],
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
    Tool(
        name="sync_projects_from_drive",
        description="Google Driveのprojects_folder_id配下のフォルダ一覧をRAGと同期します。Driveをマスタとして、追加・削除を行います。",
        inputSchema={
            "type": "object",
            "properties": {
                "dry_run": {
                    "type": "boolean",
                    "description": "trueの場合、実際の変更は行わず差分のみ報告",
                    "default": False,
                },
            },
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
    # Document Type Management
    Tool(
        name="list_document_types",
        description="利用可能なドキュメントタイプ一覧を取得します。ビルトインタイプ（設計書、実装手順書）とプロジェクト固有のカスタムタイプを返します。",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="register_document_type",
        description="新しいドキュメントタイプを登録します。プロジェクト固有のカスタムドキュメントタイプを追加できます。",
        inputSchema={
            "type": "object",
            "properties": {
                "type_id": {
                    "type": "string",
                    "description": "タイプID（英数字とアンダースコア、例: meeting_notes）",
                },
                "name": {
                    "type": "string",
                    "description": "表示名（例: 議事録）",
                },
                "folder_name": {
                    "type": "string",
                    "description": "Google Drive内のフォルダ名",
                },
                "template_doc_id": {
                    "type": "string",
                    "description": "テンプレートのGoogle Docs ID（省略可）",
                },
                "description": {
                    "type": "string",
                    "description": "ドキュメントタイプの説明",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "カスタムメタデータフィールド",
                },
                "create_folder": {
                    "type": "boolean",
                    "description": "フォルダを自動作成するか",
                    "default": True,
                },
            },
            "required": ["type_id", "name", "folder_name"],
        },
    ),
    Tool(
        name="delete_document_type",
        description="カスタムドキュメントタイプを削除します。ビルトインタイプは削除できません。",
        inputSchema={
            "type": "object",
            "properties": {
                "type_id": {
                    "type": "string",
                    "description": "削除するタイプID",
                },
            },
            "required": ["type_id"],
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
    # Progress Management
    Tool(
        name="get_progress",
        description="プロジェクトの進捗状況をGoogle Sheetsから取得します。",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "プロジェクトID（省略時は現在のプロジェクト）",
                },
                "phase": {
                    "type": "string",
                    "description": "フェーズフィルタ（省略時は全フェーズ）",
                },
            },
        },
    ),
    Tool(
        name="update_task_status",
        description="タスクのステータスをGoogle Sheetsで更新します。",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "タスクID（例: T01）",
                },
                "status": {
                    "type": "string",
                    "description": "新しいステータス（not_started/in_progress/completed/blocked）",
                },
                "phase": {
                    "type": "string",
                    "description": "フェーズ名（タスクIDが曖昧な場合に指定）",
                },
                "blockers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "ブロッカーリスト",
                },
                "notes": {
                    "type": "string",
                    "description": "備考",
                },
                "project": {
                    "type": "string",
                    "description": "プロジェクトID",
                },
            },
            "required": ["task_id", "status"],
        },
    ),
    Tool(
        name="add_task",
        description="進捗シートに新しいタスクを追加します。",
        inputSchema={
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "description": "フェーズ名（例: Phase 4）",
                },
                "task_id": {
                    "type": "string",
                    "description": "タスクID（例: T01）",
                },
                "name": {
                    "type": "string",
                    "description": "タスク名",
                },
                "description": {
                    "type": "string",
                    "description": "タスクの説明",
                },
                "project": {
                    "type": "string",
                    "description": "プロジェクトID",
                },
            },
            "required": ["phase", "task_id", "name"],
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
            "start_session", "end_session", "save_session",
            "setup_project", "switch_project", "list_projects",
            "update_project", "delete_project", "sync_projects_from_drive",
            "get_document", "create_document", "update_document",
            "list_document_types", "register_document_type", "delete_document_type",
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
                        "is_builtin": dt.is_builtin,
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
            )
            return {
                "success": result.success,
                "type_id": result.type_id,
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
