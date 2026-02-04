# Spirrow-Prismind

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

**コンテキスト対応のナレッジ管理MCPサーバー**

複数の情報源（Google Drive、RAG、MCP Memory Server）を統合し、AIアシスタント向けにコンテキスト対応のナレッジ管理を提供するMCP（Model Context Protocol）サーバーです。

> **Note**: English version is available in [README.md](README.md)

## 特徴

- **セッション管理**: 作業状態の保存・復元、関連ドキュメントの自動提示
- **プロジェクト管理**: 複数プロジェクトの切り替え、類似プロジェクトの検索
- **ドキュメント操作**: Google Docs連携、目録への自動登録
- **目録管理**: セマンティック検索、Google Sheetsとの同期
- **知見管理**: RAGベースの知見蓄積・検索

## 必要環境

- Python 3.11以上
- Google CloudプロジェクトとOAuth 2.0認証情報
- RAGサーバー（ChromaDB互換）
- MCP Memory Server（任意）

## インストール

```bash
# リポジトリをクローン
git clone https://github.com/SpirrowGames/spirrow-prismind.git
cd spirrow-prismind

# パッケージをインストール
pip install -e .
```

## 設定

1. **設定ファイルのコピー:**
   ```bash
   cp config.toml.example config.toml
   ```

2. **Google OAuth認証情報の設定:**
   - [Google Cloud Console](https://console.cloud.google.com/)でプロジェクトを作成
   - Google Docs、Drive、Sheets APIを有効化
   - OAuth 2.0認証情報を作成（デスクトップアプリケーション）
   - `credentials.json`をダウンロードして設定ディレクトリに配置

3. **外部サービスの設定（`config.toml`内）:**
   - RAGサーバーのエンドポイント（ChromaDB互換）
   - MCP Memory Serverの接続情報（任意）

## 使用方法

### Claude Desktopでの使用

Claude Desktopの設定ファイル（`claude_desktop_config.json`）に追加:

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

### Claude Codeでの使用

Claude Codeの設定に追加:

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

## 利用可能なツール

### セッション管理
| ツール | 説明 |
|--------|------|
| `start_session` | セッション開始、前回の状態を復元 |
| `end_session` | セッション終了、引き継ぎ用に状態を保存 |
| `save_session` | セッションの中間保存 |
| `list_sessions` | プロジェクトの全セッションを一覧表示 |
| `delete_session` | 特定のセッションを削除 |

### プロジェクト管理
| ツール | 説明 |
|--------|------|
| `setup_project` | 新規プロジェクトのセットアップ |
| `switch_project` | 別のプロジェクトに切り替え |
| `list_projects` | プロジェクト一覧 |
| `update_project` | プロジェクト設定の更新 |
| `delete_project` | プロジェクトの削除 |

### ドキュメント操作
| ツール | 説明 |
|--------|------|
| `get_document` | ドキュメントの検索・取得 |
| `create_document` | 新規ドキュメントの作成 |
| `update_document` | 既存ドキュメントの更新 |

### 目録操作
| ツール | 説明 |
|--------|------|
| `search_catalog` | 目録の検索 |
| `sync_catalog` | 目録の同期（Sheets → RAG） |

### 知見操作
| ツール | 説明 |
|--------|------|
| `add_knowledge` | 知見の追加 |
| `search_knowledge` | 知見の検索 |
| `update_knowledge` | 既存知見の更新 |
| `delete_knowledge` | 知見の削除 |

### 進捗管理
| ツール | 説明 |
|--------|------|
| `get_progress` | プロジェクト進捗（フェーズ・タスク）取得 |
| `add_task` | 新規タスク追加 |
| `get_task` | 単一タスク詳細取得 |
| `update_task` | タスク更新（名前・説明・ステータス・優先度・フェーズ移動） |
| `delete_task` | タスク削除（blocked_by参照の自動クリーンアップ） |
| `update_task_status` | タスクステータス更新 |
| `start_task` | タスクを進行中に設定 |
| `complete_task` | タスクを完了に設定 |
| `block_task` | タスクをブロック状態に設定 |

## アーキテクチャ

```
┌──────────────────────────────────────────────────────────────┐
│                       MCP Server                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                        Tools                           │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │  │
│  │  │ Session │ │ Project │ │Document │ │Knowledge│ ...  │  │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘      │  │
│  └───────┼──────────┼──────────┼──────────┼─────────────┘  │
│          │          │          │          │                 │
│  ┌───────┴──────────┴──────────┴──────────┴─────────────┐  │
│  │                    Integrations                       │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐         │  │
│  │  │  RAG   │ │ Memory │ │  Docs  │ │ Drive  │         │  │
│  │  │ Client │ │ Client │ │ Client │ │ Client │         │  │
│  │  └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘         │  │
│  └───────┼──────────┼──────────┼──────────┼─────────────┘  │
└──────────┼──────────┼──────────┼──────────┼────────────────┘
           │          │          │          │
           ▼          ▼          ▼          ▼
      ┌────────┐ ┌────────┐ ┌────────────────────┐
      │ChromaDB│ │ Memory │ │    Google APIs     │
      │  RAG   │ │ Server │ │ Docs/Drive/Sheets  │
      └────────┘ └────────┘ └────────────────────┘
```

## 開発

### セットアップ

```bash
# 開発用依存関係を含めてインストール
pip install -e ".[dev]"
```

### テスト

```bash
pytest
```

### コード品質

```bash
# コードフォーマット
ruff format .

# Lint & 自動修正
ruff check --fix .
```

## コントリビューション

プルリクエストを歓迎します！

1. リポジトリをフォーク
2. フィーチャーブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'Add some amazing feature'`)
4. ブランチにプッシュ (`git push origin feature/amazing-feature`)
5. プルリクエストを作成

## ライセンス

MIT License - 詳細は [LICENSE](LICENSE) ファイルを参照してください。

## 関連プロジェクト

- [Model Context Protocol](https://modelcontextprotocol.io) - プロトコル仕様
- [MCP Servers](https://github.com/modelcontextprotocol/servers) - MCP公式サーバー実装
