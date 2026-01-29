# Spirrow-Prismind 設計書

> 複数の情報源から知識を統合し、コンテキストに応じて必要な情報を分離・提供するMCPサーバ

---

## 概要

### プロジェクト名
**Spirrow-Prismind**（スパイロウ・プリズマインド）

### コンセプト
- 複数の情報源（Google Drive, RAG, MCP Memory Server）を統合管理
- 「どこに保存するか」を意識せずに知識を蓄積・取得
- セッション開始/終了で自動的にコンテキストを引き継ぎ
- **ユーザーが思考に集中できる環境を提供**

### 解決する課題
1. 情報の分散（複数ストレージに散らばる）
2. コンテキストウィンドウの圧迫
3. 環境間のバージョン差異
4. 知見の保存先判断の迷い
5. セッション切り替え時の情報引き継ぎ
6. プロジェクト切り替え時の設定書き換えの手間

---

## システム構成

### 利用するGoogle API

| API | 用途 |
|-----|------|
| Sheets API | 目録・進捗・サマリの管理 |
| Drive API | フォルダ操作、ファイル移動、メタデータ |
| Docs API | ドキュメント作成・編集（実装手順書等の自動生成） |

### 外部サービス

| サービス | 用途 |
|----------|------|
| MCP Memory Server | セッション状態、現在のプロジェクト |
| RAG Server | 知見検索、目録キャッシュ、プロジェクト設定 |

---

## 設定管理

### 設計方針

- **グローバル設定**: ローカルファイル（環境依存の認証情報等）
- **プロジェクト設定**: RAGに保存（共有可能、ファイル書き換え不要）
- **現在のプロジェクト**: MCP Memory Server（セッション状態の一部）

### グローバル設定（config.toml）

環境依存の設定のみローカルに保持：

```toml
[google]
credentials_path = "credentials.json"
token_path = "token.json"

[services]
memory_server_url = "http://localhost:8080"
rag_server_url = "http://localhost:8000"

[log]
level = "INFO"           # DEBUG / INFO / WARNING / ERROR
file = ""                # 空 = stdout
format = "text"          # text / json

[session]
auto_save_interval = 20  # メッセージ数
default_user = "default"
```

| 設定項目 | 説明 | デフォルト |
|----------|------|------------|
| `google.credentials_path` | OAuth認証用JSON | `credentials.json` |
| `google.token_path` | トークン保存先 | `token.json` |
| `services.memory_server_url` | MCP Memory Server URL | `http://localhost:8080` |
| `services.rag_server_url` | RAG Server URL | `http://localhost:8000` |
| `log.level` | ログレベル | `INFO` |
| `log.file` | ログファイルパス | `""`（stdout） |
| `log.format` | フォーマット | `text` |
| `session.auto_save_interval` | 自動保存間隔（メッセージ数） | `20` |
| `session.default_user` | デフォルトユーザー | `default` |

### プロジェクト設定（RAG保存）

`setup_project` で設定し、RAGに保存される：

```python
# RAGドキュメント形式
{
    "id": "project:trapxtrap",
    "content": "TrapxTrapCpp - 1v1トラップアクションゲーム",
    "metadata": {
        "type": "project_config",
        "project_id": "trapxtrap",
        "name": "TrapxTrapCpp",
        "description": "1v1トラップアクションゲーム",
        "spreadsheet_id": "1abc...",
        "root_folder_id": "1xyz...",
        "sheets": {
            "summary": "サマリ",
            "progress": "進捗",
            "catalog": "目録"
        },
        "drive": {
            "design_folder": "設計書",
            "procedure_folder": "実装手順書"
        },
        "docs": {
            "template_folder_id": "",
            "default_template": ""
        },
        "options": {
            "auto_sync_catalog": true,
            "auto_create_folders": true
        },
        "created_at": "2025-01-12T...",
        "updated_at": "2025-01-12T..."
    }
}
```

| 設定項目 | 説明 | 必須 |
|----------|------|:----:|
| `project_id` | プロジェクト識別子（英数字） | ✅ |
| `name` | 表示名 | ✅ |
| `description` | 説明 | |
| `spreadsheet_id` | Google SheetsのID | ✅ |
| `root_folder_id` | DriveルートフォルダID | ✅ |
| `sheets.summary` | サマリシート名 | `サマリ` |
| `sheets.progress` | 進捗シート名 | `進捗` |
| `sheets.catalog` | 目録シート名 | `目録` |
| `drive.design_folder` | 設計書フォルダ名 | `設計書` |
| `drive.procedure_folder` | 実装手順書フォルダ名 | `実装手順書` |
| `docs.template_folder_id` | テンプレートフォルダID | |
| `docs.default_template` | デフォルトテンプレート名 | |
| `options.auto_sync_catalog` | 目録自動同期 | `true` |
| `options.auto_create_folders` | フォルダ自動作成 | `true` |

### 現在のプロジェクト（MCP Memory Server）

```python
{
    "key": "prismind:current_project:{user}",
    "value": {
        "project_id": "trapxtrap",
        "switched_at": "2025-01-12T..."
    }
}
```

---

## 情報の分類と保存先

### 保存先ルール

| 情報 | 保存先 | 理由 |
|------|--------|------|
| 設計ドキュメント | Google Docs | バージョン管理、長文、NotebookLM連携 |
| 実装手順書 | Google Docs | 同上 |
| 進捗状態（Phase、タスク） | Google Sheets | 構造化データ、一覧性 |
| 技術知見（解決パターン） | RAG | セマンティック検索 |
| プロジェクト設定 | RAG | 複数プロジェクト対応、共有可能 |
| セッション状態 | MCP Memory Server | 軽量、頻繁更新、開発者ごと |
| 目録（マスター） | Google Sheets | 人間も確認できる |
| 目録（キャッシュ） | RAG | 高速検索用 |

### Google Sheets構成（プロジェクトごと）

1つのスプレッドシートに複数シートを配置：

```
[プロジェクト名]_Prismind.gsheet
├── サマリ    # プロジェクト概要、現在の状態
├── 進捗      # フェーズ・タスク一覧
└── 目録      # ドキュメント目録
```

**サマリシートの内容：**
- プロジェクト名
- 現在のフェーズ/タスク
- 最終更新日時
- ブロッカー一覧
- 次のアクション
- 関連リンク

### Google Driveフォルダ構成

```
Google Drive
└── Prismind/
    └── Projects/
        └── [プロジェクト名]/
            ├── 設計書/
            └── 実装手順書/
```

---

## 情報のライフサイクル

### 設計ドキュメント（Google Docs）

| ライフサイクル | タイミング |
|----------------|------------|
| 作成 | プロジェクト開始時、新機能設計時 |
| 更新 | 設計変更時 |
| 参照 | 実装時、仕様確認時 |
| 削除 | 基本的にしない（履歴として残す） |

### 実装手順書（Google Docs）

| ライフサイクル | タイミング |
|----------------|------------|
| 作成 | 新しい実装タスク開始時、複雑な手順を整理したい時 |
| 更新 | 実装実施前の変更のみ |
| 参照 | 実装作業中、過去の実装経緯を確認したい時 |
| 削除 | 基本的にしない |

**補足ルール：**
- 実装実施後に変更が必要な場合は修正用の新規手順書を作成
- 修正が発生したら新しいタスクとして進捗Sheetsに登録

### 進捗状態（Google Sheets）

| ライフサイクル | タイミング |
|----------------|------------|
| 作成 | プロジェクト開始時 |
| 更新 | タスク完了時、Phase移行時、新タスク追加時 |
| 参照 | セッション開始時、作業計画時 |
| 削除 | 基本的にしない（完了タスクも履歴として残す） |

### 技術知見（RAG）

| ライフサイクル | タイミング |
|----------------|------------|
| 作成 | 問題解決時、新しいパターン発見時 |
| 更新 | 知見に誤りがあった時、より良い方法が見つかった時 |
| 参照 | 類似問題に直面した時、実装方針検討時 |
| 削除 | 誤った知見、古くなって有害な情報のみ |

### セッション状態（MCP Memory Server）

| ライフサイクル | タイミング |
|----------------|------------|
| 作成 | プロジェクトで初回作業開始時 |
| 更新 | セッション終了時（毎回） |
| 参照 | セッション開始時（毎回） |
| 削除 | プロジェクト完了時 |

---

## セッション管理

### セッション開始時の手順

| 順序 | 実行者 | 内容 |
|------|--------|------|
| 1 | ユーザー | `start_session` を実行（プロジェクト指定） |
| 2 | Prismind | RAGからプロジェクト設定を取得 |
| 3 | Prismind | セッション状態をMCP Memory Serverから取得 |
| 4 | Prismind | セッション状態を返す |
| 5 | Claude | セッション状態を読み、作業内容を把握 |
| 6 | Claude | 必要そうな追加情報があれば質問する |

### 保存トリガー

| トリガー | 動作 | 通知 |
|----------|------|------|
| `end_session` 実行時 | セッション状態を保存 | 「セッション状態を保存しました。」 |
| 20メッセージごと（設定可） | セッション状態を上書き保存 | 同上 |
| コンテキスト逼迫検知時 | 警告 + 強制保存 | 「コンテキストが逼迫しています。セッション状態を保存しました。」 |

---

## 知見蓄積の判断フロー

### フロー

```
新しい知見が出た
    ↓
Claudeが保存価値を判断
    ↓
保存価値あり → Claudeが提案
  「この知見はRAGに登録しておくと良さそうですが、どうしますか？」
    ↓
ユーザーが承認 → 登録実行
ユーザーが却下 → 登録しない
```

### 保存先判断基準

| 情報の種類 | 保存先 |
|------------|--------|
| 問題解決パターン、技術Tips | RAG |
| 設計判断、アーキテクチャ | Google Docs（設計ドキュメント） |
| 手順、やり方 | Google Docs（実装手順書） |

---

## 目録管理

### 概要

目録はドキュメントへの高速アクセスを実現するためのインデックス。

- **マスター**: Google Sheets（人間も確認できる）
- **キャッシュ**: RAG（高速検索用）

### ドキュメント取得フロー

```
ユーザー: 「WeaponSystem刷新の実装手順書取得して」
    ↓
Claude: get_document("WeaponSystem刷新の実装手順書") を呼ぶ
    ↓
Prismind内部:
  1. RAGで目録を検索（高速）
  2. 該当ドキュメントのID・保存先を特定
  3. Google Docs APIで取得
  4. 内容を返す
```

### 同期機能

| 機能 | 説明 |
|------|------|
| ドキュメント作成時 | Sheets + RAG 両方に登録 |
| `sync_catalog` | Sheetsから RAGに全件再読み込み（リカバリ用） |

### 目録スキーマ

**基本情報：**

| 項目 | 必須 | 説明 |
|------|------|------|
| ドキュメント名 | ✅ | 識別名 |
| 保存先 | ✅ | Google Docs / RAG |
| ID | ✅ | 取得用識別子 |
| 種別 | ✅ | 設計書 / 実装手順書 / 仕様書 / 規約 / 設定 / その他 |

**プロジェクト情報：**

| 項目 | 必須 | 説明 |
|------|------|------|
| プロジェクト | ✅ | 所属プロジェクト |
| フェーズタスク | ✅ | P4-T01 / 共通 / 事前設計 / 技術選定 / 環境構築 / 運用 等 |
| フィーチャー | | 機能名 |

**利用コンテキスト：**

| 項目 | 必須 | 説明 |
|------|------|------|
| 参照タイミング | | 設計時 / 実装時 / レビュー時 / セッション開始時 / トラブル時 / 随時 |
| 関連ドキュメント | | 併せて読むと良い資料のID |

**検索用：**

| 項目 | 必須 | 説明 |
|------|------|------|
| キーワード | ✅ | 検索用タグ |

**運用情報：**

| 項目 | 必須 | 説明 |
|------|------|------|
| 更新日 | ✅ | 最終更新日 |
| 作成者 | | 誰が作ったか |
| ステータス | ✅ | active / archived |

---

## 命名ルール

### 実装手順書

**ファイル名：**

```
P[Phase]_T[Task]_[フィーチャー]_[対象アセット種別]_[連番]

例：
P4_T01_BTノード生成_Blueprint_001
P4_T02_BTノード生成_Blueprint_001（T01の修正 → 新タスク）
P3_T05_WeaponSystem_C++_001
P3_T06_TrapUI_Widget_001
```

**対象アセット種別の例：**
- Blueprint
- C++
- Widget
- Material
- DataAsset
- etc...

**運用ルール：**
- 修正が発生したら新しいタスクとして進捗Sheetsに登録
- タスク番号が変わるので、命名で自然に区別できる

---

## AGENTS.md / CLAUDE.md の方針

Prismindに情報を寄せた結果、ローカルファイルは最小限に：

```
AGENTS.md / CLAUDE.md（超軽量化）
├── プロジェクト名
├── Prismindの使い方（start_session）
└── 「詳細はPrismindから取得せよ」
```

---

## 環境間同期

| 情報 | 同期状態 |
|------|----------|
| Google Drive系 | ✅ 自動同期 |
| RAG | ✅ 共有サーバで解決 |
| MCP Memory Server | ✅ 共有サーバで解決 |
| ローカルファイル（config.toml等） | ⚠️ 最小限に抑えることで影響を軽減 |

---

## ツール設計

### ツール一覧

| カテゴリ | ツール | 概要 |
|----------|--------|------|
| **プロジェクト管理** | `setup_project` | 新規プロジェクトセットアップ |
| | `switch_project` | プロジェクト切り替え |
| | `list_projects` | プロジェクト一覧取得 |
| | `update_project` | プロジェクト設定更新 |
| | `delete_project` | プロジェクト削除（設定のみ） |
| **セッション管理** | `start_session` | セッション開始、状態読み込み |
| | `end_session` | セッション終了、状態保存 |
| | `save_session` | 手動での状態保存 |
| **ドキュメント操作** | `get_document` | 目録から検索してドキュメント取得 |
| | `create_document` | 新規ドキュメント作成 + 目録登録 |
| | `update_document` | ドキュメント更新 + 目録更新 |
| **目録管理** | `search_catalog` | 目録検索 |
| | `sync_catalog` | Sheets→RAG同期 |
| **進捗管理** | `get_progress` | 進捗状態取得 |
| | `update_progress` | タスク完了、Phase移行等 |
| **知見管理** | `add_knowledge` | RAGに知見追加 |
| | `search_knowledge` | RAGから知見検索 |

---

### プロジェクト管理

#### setup_project

新規プロジェクトをセットアップする。

**インターフェース：**

```python
def setup_project(
    project: str,                       # 必須: プロジェクト識別子（英数字）
    name: str,                          # 必須: 表示名
    spreadsheet_id: str,                # 必須: Google SheetsのID
    root_folder_id: str,                # 必須: Google DriveのルートフォルダID
    description: str = "",              # 任意: 説明
    create_sheets: bool = True,         # 任意: シート自動作成
    create_folders: bool = True,        # 任意: フォルダ自動作成
    force: bool = False,                # 任意: 確認をスキップして強制作成
    similarity_threshold: float = 0.7,  # 任意: 類似度閾値（0.0-1.0）
) -> SetupProjectResult
```

**出力：**

```python
@dataclass
class SimilarProject:
    project_id: str
    name: str
    description: str
    similarity: float               # 0.0 - 1.0

@dataclass
class SetupProjectResult:
    success: bool
    project_id: str = ""
    name: str = ""
    sheets_created: list[str]       # 作成されたシート名
    folders_created: list[str]      # 作成されたフォルダ名
    message: str = ""
    
    # 重複/類似チェック結果
    requires_confirmation: bool = False    # 確認が必要か
    duplicate_id: bool = False             # ID重複（エラー）
    duplicate_name: str = ""               # 名前重複したプロジェクトID（警告）
    similar_projects: list[SimilarProject] = []  # 類似プロジェクト一覧
```

**内部処理フロー：**

1. **ID重複チェック**: RAGで `type=project_config & project_id={project}` を検索
   - 存在する場合 → `duplicate_id=True`, `success=False` でエラー終了
2. **名前重複チェック**: RAGで `type=project_config & name={name}` を検索
   - 存在する場合 → `duplicate_name` に該当プロジェクトIDをセット
3. **類似プロジェクト検索**: `name + description` でセマンティック検索
   - 類似度が `similarity_threshold` 以上 → `similar_projects` に追加
4. **確認要否の判定**:
   - `force=False` かつ (名前重複 or 類似プロジェクトあり) → `requires_confirmation=True` で一旦終了
   - `force=True` または 重複・類似なし → 作成処理へ
5. プロジェクト設定をRAGに保存
6. `create_sheets=True` の場合、Sheetsにサマリ/進捗/目録シートを作成
7. `create_folders=True` の場合、Driveに設計書/実装手順書フォルダを作成
8. Memoryに現在プロジェクトとして記録
9. 結果を返す

**使用例：**

```
# ケース1: 完全新規 → そのまま作成
ユーザー: 「NewGameをセットアップして」
Prismind: ID重複なし、類似なし → 作成成功

# ケース2: ID重複 → エラー
ユーザー: 「trapxtrapをセットアップして」
Prismind: 
  duplicate_id=True, success=False
  message="プロジェクト 'trapxtrap' は既に存在します。
           update_project で設定を更新するか、別のIDで作成してください。"

# ケース3: 類似プロジェクトあり → 確認
ユーザー: 「TrapGameをセットアップして。トラップ対戦ゲーム」
Prismind:
  requires_confirmation=True
  similar_projects=[SimilarProject("trapxtrap", "TrapxTrapCpp", "1v1トラップ...", 0.78)]
  message="類似のプロジェクトが見つかりました:
           - trapxtrap (類似度: 78%): TrapxTrapCpp
           新規プロジェクトとして作成しますか？"

Claude: ユーザーに確認

ユーザー: 「新規で作成して」

Claude: setup_project(..., force=True)  # 強制作成
```

---

#### switch_project

プロジェクトを切り替える。

**インターフェース：**

```python
def switch_project(
    project: str,                   # 必須: プロジェクト識別子
) -> SwitchProjectResult
```

**出力：**

```python
@dataclass
class SwitchProjectResult:
    success: bool
    project_id: str
    name: str
    message: str
```

**内部処理フロー：**

1. RAGからプロジェクト設定を取得
2. 存在しない場合はエラー
3. Memoryの現在プロジェクトを更新
4. 結果を返す

---

#### list_projects

登録されているプロジェクト一覧を取得する。

**インターフェース：**

```python
def list_projects() -> ListProjectsResult
```

**出力：**

```python
@dataclass
class ProjectSummary:
    project_id: str
    name: str
    description: str
    updated_at: datetime

@dataclass
class ListProjectsResult:
    success: bool
    projects: list[ProjectSummary]
    current_project: str            # 現在アクティブなプロジェクト
    message: str
```

**内部処理フロー：**

1. RAGから `type=project_config` のドキュメントを全件取得
2. Memoryから現在のプロジェクトを取得
3. 結果を返す

---

#### update_project

プロジェクト設定を更新する。

**インターフェース：**

```python
def update_project(
    project: str,                   # 必須: プロジェクト識別子
    name: str = None,               # 任意: 表示名
    description: str = None,        # 任意: 説明
    spreadsheet_id: str = None,     # 任意: SheetsのID
    root_folder_id: str = None,     # 任意: DriveフォルダID
    **options                       # 任意: その他のオプション
) -> UpdateProjectResult
```

**出力：**

```python
@dataclass
class UpdateProjectResult:
    success: bool
    project_id: str
    updated_fields: list[str]
    message: str
```

---

#### delete_project

プロジェクト設定を削除する（実データは残す）。

**インターフェース：**

```python
def delete_project(
    project: str,                   # 必須: プロジェクト識別子
    confirm: bool = False,          # 必須: 削除確認
) -> DeleteProjectResult
```

**出力：**

```python
@dataclass
class DeleteProjectResult:
    success: bool
    project_id: str
    message: str
```

---

### セッション管理

#### start_session

セッションを開始し、保存された状態を読み込む。

**インターフェース：**

```python
def start_session(
    project: str = None,            # 任意: プロジェクト名（未指定で現在のプロジェクト）
    user: str = None                # 任意: ユーザー識別（デフォルトは設定から）
) -> SessionContext
```

**出力：**

```python
@dataclass
class SessionContext:
    # 基本情報
    project: str
    project_name: str               # 表示名
    user: str
    started_at: datetime
    
    # 進捗状態（MCP Memory Serverから）
    current_phase: str              # 例: "Phase 4"
    current_task: str               # 例: "T01: BTノード生成"
    last_completed: str             # 例: "P3-T12: WeaponSystem統合"
    blockers: list[str]             # 例: ["UE5.7のFGraphNodeCreator問題"]
    
    # 推奨ドキュメント
    recommended_docs: list[DocReference]
    
    # メモ（前回セッション終了時のメモ）
    notes: str

@dataclass
class DocReference:
    name: str           # ドキュメント名
    doc_id: str         # 取得用ID
    reason: str         # 推奨理由（例: "現在タスクの実装手順書"）
```

**内部処理フロー：**

1. project未指定の場合、Memoryから現在のプロジェクトを取得
2. RAGからプロジェクト設定を取得
3. MCP Memory Serverからセッション状態取得（キー: `session:{project}:{user}`）
4. Google Sheetsから進捗状態取得（最新確認）
5. 状態の整合性チェック（差異があればSheetsを正とする）
6. 推奨ドキュメントを特定（目録から current_phase + current_task でフィルタ）
7. SessionContextを返す

---

#### end_session

セッションを終了し、状態を保存する。

**インターフェース：**

```python
def end_session(
    summary: str = None,            # 任意: 今回の作業サマリ
    next_action: str = None,        # 任意: 次回やるべきこと
    blockers: list[str] = None,     # 任意: ブロッカー更新
    notes: str = None               # 任意: 引き継ぎメモ
) -> EndSessionResult
```

**出力：**

```python
@dataclass
class EndSessionResult:
    success: bool
    session_duration: timedelta
    saved_to: list[str]             # 例: ["MCP Memory Server", "Google Sheets"]
    message: str                    # 例: "セッション状態を保存しました"
```

**内部処理フロー：**

1. 現在のセッション状態を収集
2. MCP Memory Serverに保存（キー: `session:{project}:{user}`）
3. Google Sheetsの進捗を更新（必要に応じて）
4. EndSessionResultを返す

**保存されるセッション状態：**

```python
@dataclass
class SessionState:
    project: str
    user: str
    current_phase: str
    current_task: str
    last_completed: str
    blockers: list[str]
    notes: str
    last_summary: str           # 直近の作業サマリ
    next_action: str            # 次回やるべきこと
    updated_at: datetime
```

---

#### save_session

セッションを終了せずに状態を保存する。

**インターフェース：**

```python
def save_session(
    summary: str = None,
    next_action: str = None,
    blockers: list[str] = None,
    notes: str = None
) -> SaveSessionResult
```

**出力：**

```python
@dataclass
class SaveSessionResult:
    success: bool
    saved_to: list[str]
    message: str                    # 例: "セッション状態を保存しました"
```

**end_session との違い：**

| 項目 | save_session | end_session |
|------|--------------|-------------|
| セッション継続 | する | しない |
| 用途 | 途中保存、自動保存 | 明示的な終了 |
| session_duration | 返さない | 返す |

---

### ドキュメント操作

#### get_document

目録から検索してドキュメントを取得する。

**インターフェース：**

```python
def get_document(
    query: str = None,              # 任意: 検索クエリ
    doc_id: str = None,             # 任意: 直接ID指定
    doc_type: str = None,           # 任意: 種別フィルタ
    phase_task: str = None          # 任意: フェーズタスクフィルタ（例: "P4-T01"）
) -> DocumentResult
```

**出力：**

```python
@dataclass
class DocumentResult:
    found: bool
    document: Document              # 見つかった場合
    candidates: list[DocReference]  # 複数候補がある場合
    message: str

@dataclass
class Document:
    doc_id: str
    name: str
    doc_type: str                   # 設計書/実装手順書/等
    content: str                    # ドキュメント本文
    source: str                     # Google Docs / RAG
    metadata: dict                  # 更新日、作成者等
```

**内部処理フロー：**

1. doc_id指定あり → Google Docs APIで直接取得
2. query指定あり → 目録(RAG)を検索
3. 候補が1件 → 取得して返す
4. 候補が複数 → candidatesとして返す（ユーザーに選択させる）
5. 候補なし → found=False

---

#### create_document

新規ドキュメントを作成し、目録に登録する。

**インターフェース：**

```python
def create_document(
    name: str,                      # 必須: ドキュメント名
    doc_type: str,                  # 必須: 種別
    content: str,                   # 必須: 本文
    phase_task: str,                # 必須: フェーズタスク
    feature: str = None,            # 任意: フィーチャー
    keywords: list[str] = None,     # 任意: 検索キーワード（未指定時は自動生成）
    reference_timing: str = None,   # 任意: 参照タイミング
    related_docs: list[str] = None  # 任意: 関連ドキュメントID
) -> CreateDocumentResult
```

**出力：**

```python
@dataclass
class CreateDocumentResult:
    success: bool
    doc_id: str                     # 生成されたID
    name: str
    doc_url: str                    # Google DocsのURL
    source: str                     # Google Docs
    catalog_registered: bool        # 目録登録成功
    message: str
```

**内部処理フロー：**

1. 現在のプロジェクト設定を取得
2. ドキュメント種別に応じたフォルダを特定（存在しない場合は作成）
3. Drive APIで正しいフォルダにドキュメントを作成
4. Docs APIでコンテンツを追加（見出し + 本文）
5. keywordsが未指定の場合、自動生成（ドキュメント名 + content から抽出）
6. 目録に登録（Google Sheets）
7. 目録キャッシュに登録（RAG）
8. 結果を返す

---

#### update_document

ドキュメントを更新し、目録も更新する。

**インターフェース：**

```python
def update_document(
    doc_id: str,                    # 必須: 更新対象ID
    content: str = None,            # 任意: 本文更新
    append: bool = False,           # 任意: Trueなら追記、Falseなら置換
    metadata: dict = None           # 任意: メタデータ更新
) -> UpdateDocumentResult
```

**出力：**

```python
@dataclass
class UpdateDocumentResult:
    success: bool
    doc_id: str
    updated_fields: list[str]       # 例: ["content", "keywords"]
    message: str
```

**内部処理フロー：**

1. Google Docs APIでドキュメントを更新
2. 目録を更新（Google Sheets）← 更新日を更新
3. 目録キャッシュを更新（RAG）
4. 結果を返す

---

### 目録管理

#### search_catalog

目録を検索する。

**インターフェース：**

```python
def search_catalog(
    query: str = None,              # 任意: フリーテキスト検索
    project: str = None,            # 任意: プロジェクトフィルタ
    doc_type: str = None,           # 任意: 種別フィルタ
    phase_task: str = None,         # 任意: フェーズタスクフィルタ
    feature: str = None,            # 任意: フィーチャーフィルタ
    reference_timing: str = None,   # 任意: 参照タイミングフィルタ
    status: str = "active",         # 任意: ステータス（active/archived/all）
    limit: int = 10                 # 任意: 最大件数
) -> SearchCatalogResult
```

**出力：**

```python
@dataclass
class SearchCatalogResult:
    success: bool
    total_count: int
    documents: list[CatalogEntry]
    message: str

@dataclass
class CatalogEntry:
    doc_id: str
    name: str
    doc_type: str
    project: str
    phase_task: str
    feature: str
    source: str                     # Google Docs / RAG
    updated_at: datetime
    keywords: list[str]
    reference_timing: str
```

**内部処理フロー：**

1. RAG（目録キャッシュ）で検索
2. フィルタ条件適用
3. 結果を整形して返す

---

#### sync_catalog

Google Sheets（目録マスター）からRAG（目録キャッシュ）へ同期する。

**インターフェース：**

```python
def sync_catalog(
    project: str = None             # 任意: 特定プロジェクトのみ同期（未指定で現在のプロジェクト）
) -> SyncCatalogResult
```

**出力：**

```python
@dataclass
class SyncCatalogResult:
    success: bool
    synced_count: int               # 同期した件数
    message: str
```

**内部処理フロー：**

1. Google Sheets（目録マスター）から全件取得
2. RAGの該当範囲をクリア
3. RAGに登録
4. 結果を返す

**用途：**
- 定期的な整合性維持
- 手動でSheetsを編集した後の反映
- 障害復旧時のキャッシュ再構築

---

### 進捗管理

#### get_progress

プロジェクトの進捗状態を取得する。

**インターフェース：**

```python
def get_progress(
    project: str = None,            # 任意: プロジェクト名（未指定で現在のプロジェクト）
    phase: str = None,              # 任意: 特定フェーズのみ
    include_completed: bool = False # 任意: 完了タスクも含める
) -> GetProgressResult
```

**出力：**

```python
@dataclass
class GetProgressResult:
    success: bool
    project: str
    current_phase: str
    phases: list[PhaseProgress]
    message: str

@dataclass
class PhaseProgress:
    phase: str                      # 例: "Phase 4"
    status: str                     # not_started / in_progress / completed
    tasks: list[TaskProgress]

@dataclass
class TaskProgress:
    task_id: str                    # 例: "T01"
    name: str                       # 例: "BTノード生成"
    status: str                     # not_started / in_progress / completed / blocked
    blockers: list[str]             # ブロッカーがあれば
    completed_at: datetime          # 完了日時（完了時のみ）
    notes: str                      # 備考
    # v2 拡張フィールド
    priority: str = "medium"        # high / medium / low
    category: str = ""              # bug / feature / refactor / design / test 等
    blocked_by: list[str] = []      # 依存タスクID（例: ["T01", "T02"]）
```

**スプレッドシートカラム構成：**

| カラム | 項目 | 備考 |
|--------|------|------|
| A | フェーズ | Phase 4 等 |
| B | タスクID | T01 等 |
| C | タスク名 | |
| D | ステータス | not_started/in_progress/completed/blocked |
| E | ブロッカー | カンマ区切り |
| F | 完了日 | ISO形式 |
| G | 備考 | |
| H | 優先度 | high/medium/low（v2） |
| I | カテゴリ | bug/feature/refactor/design/test（v2） |
| J | 依存タスク | カンマ区切りのタスクID（v2） |

※ H〜J列は後方互換性あり。古いシートでも動作。

**内部処理フロー：**

1. 現在のプロジェクト設定を取得
2. Google Sheets（進捗シート）から取得
3. フィルタ適用
4. 結果を返す

---

#### update_progress

タスクのステータスを更新または新規タスクを追加する。

**インターフェース：**

```python
def update_progress(
    task_id: str,                   # 必須: タスクID（例: "P4-T01"）
    status: str = None,             # 任意: ステータス変更
    blockers: list[str] = None,     # 任意: ブロッカー更新
    notes: str = None,              # 任意: 備考更新
    priority: str = None,           # 任意: 優先度（high/medium/low）（v2）
    category: str = None,           # 任意: カテゴリ（v2）
    blocked_by: list[str] = None,   # 任意: 依存タスクID（v2）
    new_task: TaskDefinition = None # 任意: 新規タスク追加
) -> UpdateProgressResult

@dataclass
class TaskDefinition:
    phase: str                      # 例: "Phase 4"
    task_id: str                    # 例: "T02"
    name: str                       # 例: "BTノード接続"
    description: str = None
    priority: str = "medium"        # 優先度（v2）
    category: str = ""              # カテゴリ（v2）
    blocked_by: list[str] = []      # 依存タスクID（v2）
```

**出力：**

```python
@dataclass
class UpdateProgressResult:
    success: bool
    project: str
    task_id: str
    updated_fields: list[str]
    message: str
```

**内部処理フロー：**

1. new_task 指定あり → 新規タスク追加
2. それ以外 → 既存タスク更新
3. Google Sheets（進捗シート）を更新
4. セッション状態も更新（MCP Memory Server）
5. 結果を返す

---

### 知見管理

#### add_knowledge

RAGに知見を追加する。

**インターフェース：**

```python
def add_knowledge(
    content: str,                   # 必須: 知見の内容
    category: str,                  # 必須: カテゴリ（問題解決/技術Tips/ベストプラクティス/落とし穴/等）
    project: str = None,            # 任意: 関連プロジェクト（汎用知見なら未指定）
    tags: list[str] = None,         # 任意: タグ（未指定時は自動生成）
    source: str = None              # 任意: 情報源（どこで得た知見か）
) -> AddKnowledgeResult
```

**出力：**

```python
@dataclass
class AddKnowledgeResult:
    success: bool
    knowledge_id: str               # 生成されたID
    tags: list[str]                 # 最終的なタグ（自動生成含む）
    message: str
```

**内部処理フロー：**

1. tags が未指定の場合、自動生成（content から重要語抽出）
2. RAGに登録（メタデータ: category, project, tags, source, created_at）
3. 結果を返す

---

#### search_knowledge

RAGから知見を検索する。

**インターフェース：**

```python
def search_knowledge(
    query: str,                     # 必須: 検索クエリ
    category: str = None,           # 任意: カテゴリフィルタ
    project: str = None,            # 任意: プロジェクトフィルタ（未指定で汎用含む全件）
    tags: list[str] = None,         # 任意: タグフィルタ（AND条件）
    limit: int = 5                  # 任意: 最大件数
) -> SearchKnowledgeResult
```

**出力：**

```python
@dataclass
class SearchKnowledgeResult:
    success: bool
    total_count: int
    knowledge: list[KnowledgeEntry]
    message: str

@dataclass
class KnowledgeEntry:
    knowledge_id: str
    content: str
    category: str
    project: str                    # None なら汎用知見
    tags: list[str]
    source: str
    created_at: datetime
    relevance_score: float          # 検索スコア
```

**内部処理フロー：**

1. RAGでセマンティック検索
2. フィルタ条件適用
3. スコア順にソート
4. 結果を返す

---

## 今後のTODO

- [x] Prismindのツール設計
- [x] 設定管理方式の設計
- [x] プロジェクト管理ツールの設計
- [ ] Google API連携実装（Sheets + Drive + Docs）
- [ ] RAG連携実装
- [ ] MCP Memory Server連携実装
- [ ] プロジェクト管理機能実装
- [ ] セッション管理機能実装
- [ ] ドキュメント操作機能実装
- [ ] 目録管理機能実装
- [ ] 進捗管理機能実装
- [ ] 知見管理機能実装
- [ ] 自動保存機能実装
- [ ] コンテキスト逼迫検知機能

---

## 更新履歴

| 日付 | 内容 |
|------|------|
| 2025-01-29 | TaskProgressにv2拡張フィールド追加（priority, category, blocked_by）|
| 2025-01-28 | create_documentの内部処理フローを「作成→移動」から「最初から正しいフォルダに作成」に変更 |
| 2025-01-12 | setup_projectに重複チェック・類似プロジェクト検索機能追加 |
| 2025-01-12 | プロジェクト管理ツール追加、設定管理方式変更、Google Docs API追加 |
| 2025-01-12 | ツール設計追加（11ツール） |
| 2025-01-12 | 初版作成 |
