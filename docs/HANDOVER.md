# Spirrow-Prismind 開発引き継ぎドキュメント

## プロジェクト概要

**Spirrow-Prismind** は、複数情報源（Google Drive, RAG, MCP Memory Server）を統合し、コンテキスト対応の知識管理を提供するMCPサーバです。

- **リポジトリ**: `C:\Users\owner\Documents\Unreal Projects\spirrow-prismind`
- **言語**: Python 3.11+
- **フレームワーク**: MCP (Model Context Protocol)

## 現在の実装状況

### ✅ 完了

#### データモデル（`src/spirrow_prismind/models/`）
- `session.py` - SessionContext, SessionState, EndSessionResult, SaveSessionResult
- `document.py` - Document, DocReference, DocumentResult, CreateDocumentResult, UpdateDocumentResult
- `catalog.py` - CatalogEntry, SearchCatalogResult, SyncCatalogResult
- `knowledge.py` - KnowledgeEntry, AddKnowledgeResult, SearchKnowledgeResult
- `progress.py` - PhaseProgress, TaskProgress, TaskDefinition, GetProgressResult, UpdateProgressResult
- `project.py` - ProjectConfig, SheetsConfig, DriveConfig, DocsConfig, ProjectOptions, ProjectSummary, SimilarProject, SetupProjectResult, SwitchProjectResult, ListProjectsResult, UpdateProjectResult, DeleteProjectResult

#### 統合クライアント（`src/spirrow_prismind/integrations/`）
- `google_sheets.py` - Google Sheets API連携（OAuth2, CRUD）
- `google_docs.py` - Google Docs API連携（作成, 編集, テキスト抽出）
- `google_drive.py` - Google Drive API連携（フォルダ, ファイル操作）
- `rag_client.py` - RAGサーバクライアント（ChromaDB互換REST API想定）
- `memory_client.py` - MCP Memory Serverクライアント（key-value REST API想定）

#### ツール（`src/spirrow_prismind/tools/`）
- `project_tools.py` - setup_project, switch_project, list_projects, update_project, delete_project, get_project_config
- `session_tools.py` - start_session, end_session, save_session, update_progress
- `document_tools.py` - get_document, create_document, update_document
- `catalog_tools.py` - search_catalog, sync_catalog
- `knowledge_tools.py` - add_knowledge, search_knowledge
- `progress_tools.py` - get_progress, update_task_status, add_task, complete_task, start_task, block_task

#### サーバ
- `server.py` - MCPサーバ本体（14ツール登録済み）
- `config.py` - 設定管理（TOML読み込み）

#### テスト（`tests/`）
- `conftest.py` - Pytest フィクスチャ（モッククライアント初期化）
- `test_google_sheets.py` - Google Sheets統合テスト（5テスト）
- `test_project_tools.py` - ProjectToolsユニットテスト（17テスト）
- `test_session_tools.py` - SessionToolsユニットテスト（16テスト）
- `test_document_tools.py` - DocumentToolsユニットテスト（12テスト）
- `test_catalog_tools.py` - CatalogToolsユニットテスト（12テスト）
- `test_knowledge_tools.py` - KnowledgeToolsユニットテスト（17テスト）
- `test_progress_tools.py` - ProgressToolsユニットテスト（16テスト）
- `mocks/mock_rag.py` - RAGクライアントのインメモリモック
- `mocks/mock_memory.py` - Memoryクライアントのインメモリモック

**テスト合計: 95テスト（すべてパス）**

### 🔲 未実装・要検討

1. **Claude Desktop統合テスト** - 実環境での動作確認

## アーキテクチャ

```
MCP Server (server.py)
    │
    ├── Tools Layer
    │   ├── ProjectTools     - プロジェクト管理
    │   ├── SessionTools     - セッション管理
    │   ├── DocumentTools    - ドキュメント操作
    │   ├── CatalogTools     - 目録管理
    │   └── KnowledgeTools   - 知見管理
    │
    └── Integration Layer
        ├── GoogleSheetsClient  → Google Sheets API
        ├── GoogleDocsClient    → Google Docs API
        ├── GoogleDriveClient   → Google Drive API
        ├── RAGClient           → ChromaDB互換サーバ
        └── MemoryClient        → MCP Memory Server
```

## 設定ファイル

### config.toml
```toml
[google]
credentials_path = "credentials.json"
token_path = "token.json"

[services]
memory_server_url = "http://localhost:8080"
rag_server_url = "http://localhost:8000"
rag_collection = "prismind"

[log]
level = "INFO"

[session]
default_user = "default"
```

## MCPツール一覧（17個）

| ツール名 | 説明 |
|----------|------|
| `start_session` | セッション開始、状態復元 |
| `end_session` | セッション終了、状態保存 |
| `save_session` | セッション中間保存 |
| `setup_project` | 新規プロジェクトセットアップ（重複チェック付き） |
| `switch_project` | プロジェクト切り替え |
| `list_projects` | プロジェクト一覧 |
| `update_project` | プロジェクト設定更新 |
| `delete_project` | プロジェクト削除 |
| `get_document` | ドキュメント検索・取得 |
| `create_document` | ドキュメント作成 |
| `update_document` | ドキュメント更新 |
| `search_catalog` | 目録検索 |
| `sync_catalog` | 目録同期 |
| `add_knowledge` | 知見登録 |
| `search_knowledge` | 知見検索 |
| `get_progress` | 進捗取得（Sheets連携） |
| `update_task_status` | タスクステータス更新 |
| `add_task` | タスク追加 |

## データ構造

### RAGデータ
- プロジェクト設定: `doc_id="project:{project_id}"`, `metadata.type="project_config"`
- 知見: `doc_id="knowledge:{timestamp}"`, `metadata.type="knowledge"`
- 目録: `doc_id="catalog:{project}:{doc_id}"`, `metadata.type="catalog"`

### Memoryキー
- セッション状態: `"prismind:session:{project}:{user}"`（デフォルト/レガシー）
  - コンテキスト author 分割時: `"prismind:session:{project}:{user}:{author}"`
  - `author` 空は従来キー形式を維持（後方互換）。保存済み author は `list_context_authors` で取得可能
- 現在プロジェクト: `"prismind:current_project:{user}"`

### Google Sheets構成（プロジェクトごと）
- サマリシート: プロジェクト概要
- 進捗シート: フェーズ・タスク一覧
- 目録シート: ドキュメント目録

## 次のタスク候補

### 1. テスト実行
```bash
cd "C:\Users\owner\Documents\Unreal Projects\spirrow-prismind"
pip install -e ".[dev]"
pytest tests/ -v  # 95テストすべてパス
```

### 2. Claude Desktop統合テスト
`claude_desktop_config.json`に追加してテスト：
```json
{
  "mcpServers": {
    "spirrow-prismind": {
      "command": "spirrow-prismind",
      "args": []
    }
  }
}
```

## 関連ドキュメント

- 詳細設計: `docs/DESIGN.md`
- セッション再開ガイド: `docs/SESSION_RESUME.md`

## 開発者メモ

- Python 3.11+必須（tomllib使用）
- Google OAuth認証は初回実行時にブラウザ認証が必要
- RAGサーバはChromaDB REST API互換を想定
- MemoryサーバはシンプルなKey-Value REST APIを想定
