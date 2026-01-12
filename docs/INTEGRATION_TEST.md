# Spirrow-Prismind 統合テスト仕様書

## 概要

このドキュメントは、Spirrow-PrismindをClaude Desktopに統合してテストするための仕様書です。

## テスト環境準備

### 1. 前提条件

- [ ] Python 3.11+ インストール済み
- [ ] Claude Desktop インストール済み
- [ ] Google Cloud Consoleでプロジェクト作成済み
- [ ] Google OAuth 2.0 クライアントID作成済み

### 2. Google認証設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクト作成
2. 以下のAPIを有効化:
   - Google Sheets API
   - Google Docs API
   - Google Drive API
3. OAuth 2.0 クライアントIDを作成（デスクトップアプリ）
4. `credentials.json` をダウンロード
5. プロジェクトルートに配置

### 3. パッケージインストール

```bash
cd "C:\Users\owner\Documents\Unreal Projects\spirrow-prismind"
pip install -e .
```

### 4. 設定ファイル準備

`config.toml` を作成（config.toml.exampleからコピー）:

```toml
[google]
credentials_path = "credentials.json"
token_path = "token.json"

[services]
memory_server_url = "http://localhost:8080"
rag_server_url = "http://localhost:8000"
rag_collection = "prismind"

[log]
level = "DEBUG"

[session]
default_user = "default"
```

### 5. Claude Desktop設定

`%APPDATA%\Claude\claude_desktop_config.json` に追加:

```json
{
  "mcpServers": {
    "spirrow-prismind": {
      "command": "spirrow-prismind",
      "args": [],
      "env": {
        "PRISMIND_CONFIG": "C:\\Users\\owner\\Documents\\Unreal Projects\\spirrow-prismind\\config.toml"
      }
    }
  }
}
```

---

## テストケース

### Phase 1: 基本動作確認

#### TC-001: サーバー起動確認
**目的**: MCPサーバーが正常に起動するか確認

**手順**:
1. Claude Desktopを起動
2. MCPサーバー一覧でspirrow-prismindが表示されることを確認

**期待結果**:
- [ ] サーバーがConnected状態になる
- [ ] エラーログがない

---

### Phase 2: プロジェクト管理テスト

#### TC-010: プロジェクトセットアップ
**目的**: 新規プロジェクトを作成できるか確認

**手順**:
1. Claudeに依頼: 「setup_projectでテストプロジェクトを作成して」
2. パラメータ:
   - project: "test_proj"
   - name: "テストプロジェクト"
   - spreadsheet_id: (テスト用スプレッドシートID)
   - root_folder_id: (テスト用フォルダID)

**期待結果**:
- [ ] success: true
- [ ] プロジェクトIDが返る
- [ ] RAGに設定が保存される

#### TC-011: プロジェクト重複チェック
**目的**: 同じIDのプロジェクトを作成できないことを確認

**手順**:
1. TC-010と同じproject IDで再度setup_projectを実行

**期待結果**:
- [ ] success: false
- [ ] duplicate_id: true
- [ ] エラーメッセージが適切

#### TC-012: プロジェクト一覧取得
**目的**: list_projectsが正常に動作するか確認

**手順**:
1. Claudeに依頼: 「プロジェクト一覧を表示して」

**期待結果**:
- [ ] success: true
- [ ] TC-010で作成したプロジェクトが含まれる
- [ ] current_projectが設定されている

#### TC-013: プロジェクト切り替え
**目的**: switch_projectが正常に動作するか確認

**手順**:
1. 別のプロジェクトを作成
2. switch_projectで切り替え

**期待結果**:
- [ ] success: true
- [ ] current_projectが更新される

---

### Phase 3: セッション管理テスト

#### TC-020: セッション開始
**目的**: start_sessionが状態を正しく読み込むか確認

**手順**:
1. Claudeに依頼: 「セッションを開始して」

**期待結果**:
- [ ] プロジェクト名が返る
- [ ] 前回の状態があれば復元される
- [ ] recommended_docsが返る（あれば）

#### TC-021: セッション保存
**目的**: save_sessionが状態を保存するか確認

**手順**:
1. セッション開始後
2. Claudeに依頼: 「現在Phase 4のT01を作業中と保存して」

**期待結果**:
- [ ] success: true
- [ ] Memoryに状態が保存される

#### TC-022: セッション終了
**目的**: end_sessionが状態を保存して終了するか確認

**手順**:
1. Claudeに依頼: 「セッションを終了。サマリ：テスト完了」

**期待結果**:
- [ ] success: true
- [ ] session_durationが返る
- [ ] 状態がMemoryに保存される

#### TC-023: セッション状態復元
**目的**: 次回start_sessionで状態が復元されるか確認

**手順**:
1. TC-022終了後、再度start_session

**期待結果**:
- [ ] TC-021/022で保存した状態が復元される
- [ ] current_phase, current_taskが正しい

---

### Phase 4: 進捗管理テスト

#### TC-030: 進捗取得
**目的**: get_progressがSheetsからデータを取得するか確認

**前提**: テスト用スプレッドシートに進捗データを入力済み

**手順**:
1. Claudeに依頼: 「現在の進捗を確認して」

**期待結果**:
- [ ] success: true
- [ ] phasesにフェーズ一覧が含まれる
- [ ] 各フェーズにtasksが含まれる

#### TC-031: タスクステータス更新
**目的**: update_task_statusがSheetsを更新するか確認

**手順**:
1. Claudeに依頼: 「T01を作業中にして」

**期待結果**:
- [ ] success: true
- [ ] Sheetsのステータスが"in_progress"に更新
- [ ] Memoryのセッション状態も更新

#### TC-032: タスク完了
**目的**: タスク完了時に日付が記録されるか確認

**手順**:
1. Claudeに依頼: 「T01を完了にして」

**期待結果**:
- [ ] success: true
- [ ] Sheetsのステータスが"completed"
- [ ] 完了日が記録される

#### TC-033: タスク追加
**目的**: add_taskで新規タスクを追加できるか確認

**手順**:
1. Claudeに依頼: 「Phase 4にT99:新規テストタスクを追加して」

**期待結果**:
- [ ] success: true
- [ ] Sheetsに新しい行が追加される

---

### Phase 5: ドキュメント管理テスト

#### TC-040: ドキュメント検索
**目的**: get_documentが目録を検索するか確認

**前提**: 目録にドキュメントが登録済み

**手順**:
1. Claudeに依頼: 「設計書を検索して」

**期待結果**:
- [ ] 単一結果: ドキュメント内容が返る
- [ ] 複数結果: candidatesリストが返る

#### TC-041: ドキュメント作成
**目的**: create_documentがGoogle Docsにファイルを作成するか確認

**手順**:
1. Claudeに依頼: 「新しい設計書を作成して」
2. パラメータ指定

**期待結果**:
- [ ] success: true
- [ ] Google Docsにドキュメントが作成される
- [ ] 目録に登録される
- [ ] doc_urlが返る

---

### Phase 6: 目録・知見テスト

#### TC-050: 目録検索
**目的**: search_catalogが動作するか確認

**手順**:
1. Claudeに依頼: 「Phase 4の設計書を検索して」

**期待結果**:
- [ ] success: true
- [ ] フィルタ条件に合致する結果が返る

#### TC-051: 目録同期
**目的**: sync_catalogがSheetsからRAGに同期するか確認

**手順**:
1. Claudeに依頼: 「目録を同期して」

**期待結果**:
- [ ] success: true
- [ ] synced_countが返る

#### TC-060: 知見登録
**目的**: add_knowledgeが知見を登録するか確認

**手順**:
1. Claudeに依頼: 「この問題解決方法を知見として登録して：〇〇」

**期待結果**:
- [ ] success: true
- [ ] knowledge_idが返る
- [ ] tagsが自動生成される

#### TC-061: 知見検索
**目的**: search_knowledgeが知見を検索するか確認

**手順**:
1. Claudeに依頼: 「〇〇に関する知見を検索して」

**期待結果**:
- [ ] success: true
- [ ] 関連する知見が返る
- [ ] relevance_scoreが付与される

---

## テスト結果記録

| TC番号 | テスト名 | 結果 | 備考 |
|--------|----------|------|------|
| TC-001 | サーバー起動確認 | | |
| TC-010 | プロジェクトセットアップ | | |
| TC-011 | プロジェクト重複チェック | | |
| TC-012 | プロジェクト一覧取得 | | |
| TC-013 | プロジェクト切り替え | | |
| TC-020 | セッション開始 | | |
| TC-021 | セッション保存 | | |
| TC-022 | セッション終了 | | |
| TC-023 | セッション状態復元 | | |
| TC-030 | 進捗取得 | | |
| TC-031 | タスクステータス更新 | | |
| TC-032 | タスク完了 | | |
| TC-033 | タスク追加 | | |
| TC-040 | ドキュメント検索 | | |
| TC-041 | ドキュメント作成 | | |
| TC-050 | 目録検索 | | |
| TC-051 | 目録同期 | | |
| TC-060 | 知見登録 | | |
| TC-061 | 知見検索 | | |

---

## 注意事項

1. **Google認証**: 初回実行時はブラウザでOAuth認証が必要
2. **RAG/Memoryサーバー**: 本テストではモックではなく実サーバーが必要（または省略可能なテストのみ実施）
3. **テストデータ**: テスト用のGoogleスプレッドシートとフォルダを事前に準備

## トラブルシューティング

### サーバーが起動しない
- `config.toml`のパスを確認
- Pythonパスが正しいか確認
- `pip install -e .`を再実行

### Google認証エラー
- `credentials.json`の配置を確認
- Google Cloud Consoleで正しいAPIが有効か確認
- OAuth同意画面の設定を確認

### ツールが見つからない
- Claude Desktopを再起動
- MCPサーバーログを確認
