# Claude Code 移行用プロンプト

以下をClaude Codeの最初のメッセージとして使用してください：

---

## プロンプト開始

```
Spirrow-Prismind MCPサーバの開発を引き継ぎます。

## プロジェクト情報
- リポジトリ: C:\Users\owner\Documents\Unreal Projects\spirrow-prismind
- 言語: Python 3.11+
- 目的: 複数情報源を統合するコンテキスト対応知識管理MCPサーバ

## 引き継ぎドキュメント
まず docs/HANDOVER.md を読んで現在の実装状況を把握してください。

## 現在の状態
- データモデル: ✅ 完了
- 統合クライアント（Google/RAG/Memory）: ✅ 完了
- ツール層（5モジュール）: ✅ 完了
- MCPサーバ本体: ✅ 完了（11ツール）
- テスト: 🔲 未実装

## 次のタスク
1. pyproject.toml のエントリポイント確認・修正
2. テスト用モック作成（RAG/Memory）
3. ユニットテスト実装
4. MCPサーバの動作確認

まずプロジェクト構造を確認して、開発を進めてください。
```

---

## 補足情報

### ファイル構造
```
spirrow-prismind/
├── src/spirrow_prismind/
│   ├── __init__.py
│   ├── config.py
│   ├── server.py          # MCPサーバ本体
│   ├── integrations/      # 外部サービスクライアント
│   │   ├── google_docs.py
│   │   ├── google_drive.py
│   │   ├── google_sheets.py
│   │   ├── rag_client.py
│   │   └── memory_client.py
│   ├── models/            # データモデル
│   └── tools/             # MCPツール実装
│       ├── project_tools.py
│       ├── session_tools.py
│       ├── document_tools.py
│       ├── catalog_tools.py
│       └── knowledge_tools.py
├── tests/
├── docs/
│   ├── DESIGN.md          # 詳細設計
│   └── HANDOVER.md        # 引き継ぎドキュメント
├── config.toml.example
├── pyproject.toml
└── README.md
```

### Claude Codeでの作業開始コマンド
```bash
cd "C:\Users\owner\Documents\Unreal Projects\spirrow-prismind"
```

### 依存関係インストール
```bash
pip install -e ".[dev]"
```
