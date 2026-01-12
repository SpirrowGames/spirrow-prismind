# Spirrow-Prismind セッション再開用プロンプト

次回チャット開始時にこの内容をコピペしてください。

---

## 再開プロンプト

```
Spirrow-Prismindの開発を続けます。

## プロジェクト概要
- 名称: Spirrow-Prismind（スパイロウ・プリズマインド）
- 説明: 複数の情報源から知識を統合し、コンテキストに応じて必要な情報を分離・提供するMCPサーバ
- リポジトリ: C:\Users\owner\Documents\Unreal Projects\spirrow-prismind

## 完了した作業
1. 情報の分類基準と保存先ルール設計
2. 情報のライフサイクル定義
3. セッション管理（開始/終了/保存トリガー）設計
4. 知見蓄積の判断フロー設計
5. 目録スキーマ設計
6. 命名ルール（実装手順書）設計
7. AGENTS.md/CLAUDE.md整理方針決定
8. ツール設計完了（11ツール）

## 設計済みツール一覧
| カテゴリ | ツール |
|----------|--------|
| セッション管理 | start_session, end_session, save_session |
| ドキュメント操作 | get_document, create_document, update_document |
| 目録管理 | search_catalog, sync_catalog |
| 進捗管理 | get_progress, update_progress |
| 知見管理 | add_knowledge, search_knowledge |

## 成果物
- README.md
- docs/DESIGN.md（詳細設計書、ツール設計含む）

## 次のTODO
1. Google Sheets API連携実装
2. プロジェクト初期化（pyproject.toml等）
3. 目録管理機能実装
4. セッション管理機能実装

## 確認してほしいこと
まず docs/DESIGN.md を読んで設計内容を把握してください。
その後、次のステップとしてGoogle Sheets API連携から実装を始めたいです。
```

---

## 補足情報

### 主要な設計判断
- 保存先: Google Docs（設計書/手順書）、Google Sheets（進捗/目録マスター）、RAG（知見/目録キャッシュ）、MCP Memory Server（セッション状態）
- 目録: Sheetsがマスター、RAGはキャッシュ（Sheets→RAGの一方向同期）
- キーワード自動生成: 未指定時のみ自動生成
- セッション保存: end_session時 + 20メッセージごと + コンテキスト逼迫時

### 関連ファイルパス
- 設計書: C:\Users\owner\Documents\Unreal Projects\spirrow-prismind\docs\DESIGN.md
- README: C:\Users\owner\Documents\Unreal Projects\spirrow-prismind\README.md
