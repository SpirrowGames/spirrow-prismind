# Spirrow-Prismind

**MCP Server for Context-Aware Knowledge Management**

複数の情報源（Google Drive, RAG, MCP Memory Server）を統合し、コンテキスト対応の知識管理を提供するMCPサーバです。

## Features

- **セッション管理**: 作業状態の保存・復元、推奨ドキュメントの自動提示
- **プロジェクト管理**: 複数プロジェクトの切り替え、類似プロジェクト検索
- **ドキュメント操作**: Google Docs連携、目録への自動登録
- **目録管理**: セマンティック検索、Google Sheets同期
- **知見管理**: RAGベースの知見蓄積・検索

## Installation

```bash
# Clone the repository
git clone https://github.com/SpirrowGames/spirrow-prismind.git
cd spirrow-prismind

# Install dependencies
pip install -e .
```

## Configuration

1. Copy the example config:
```bash
cp config.toml.example config.toml
```

2. Set up Google OAuth credentials:
   - Create a project in Google Cloud Console
   - Enable Google Docs, Drive, and Sheets APIs
   - Create OAuth 2.0 credentials
   - Download `credentials.json` and place it in the config directory

3. Configure external services:
   - RAG Server (ChromaDB compatible)
   - MCP Memory Server

## Usage

### As MCP Server

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "prismind": {
      "command": "spirrow-prismind",
      "env": {
        "PRISMIND_CONFIG": "/path/to/config.toml"
      }
    }
  }
}
```

### Available Tools

#### Session Management
- `start_session` - セッション開始、状態復元
- `end_session` - セッション終了、状態保存
- `save_session` - セッション中間保存

#### Project Management
- `setup_project` - 新規プロジェクトセットアップ
- `switch_project` - プロジェクト切り替え
- `list_projects` - プロジェクト一覧
- `update_project` - プロジェクト設定更新
- `delete_project` - プロジェクト削除

#### Document Operations
- `get_document` - ドキュメント検索・取得
- `create_document` - ドキュメント作成
- `update_document` - ドキュメント更新

#### Catalog Operations
- `search_catalog` - 目録検索
- `sync_catalog` - 目録同期（Sheets → RAG）

#### Knowledge Operations
- `add_knowledge` - 知見登録
- `search_knowledge` - 知見検索

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Server                            │
│  ┌─────────────────────────────────────────────────┐   │
│  │                    Tools                          │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐           │   │
│  │  │ Session │ │ Project │ │ Document│ ...       │   │
│  │  └────┬────┘ └────┬────┘ └────┬────┘           │   │
│  └───────┼──────────┼──────────┼──────────────────┘   │
│          │          │          │                       │
│  ┌───────┴──────────┴──────────┴──────────────────┐   │
│  │              Integrations                        │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │   │
│  │  │  RAG   │ │ Memory │ │ Docs   │ │ Drive  │   │   │
│  │  │ Client │ │ Client │ │ Client │ │ Client │   │   │
│  │  └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘   │   │
│  └───────┼──────────┼──────────┼──────────┼───────┘   │
└──────────┼──────────┼──────────┼──────────┼───────────┘
           │          │          │          │
           ▼          ▼          ▼          ▼
      ┌────────┐ ┌────────┐ ┌────────────────────┐
      │ChromaDB│ │ Memory │ │   Google APIs      │
      │  RAG   │ │ Server │ │ Docs/Drive/Sheets  │
      └────────┘ └────────┘ └────────────────────┘
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
ruff format .
ruff check --fix .
```

## License

MIT License - SpirrowGames

詳細は [LICENSE](LICENSE) ファイルを参照してください。
