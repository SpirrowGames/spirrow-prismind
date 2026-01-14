# トラブルシューティング

このドキュメントでは、Spirrow-Prismindの初回接続時やよくある問題の解決方法を説明します。

## 目次

- [初回セットアップ](#初回セットアップ)
- [credentials.json について](#credentialsjson-について)
- [token.json の取得](#tokenjson-の取得)
- [config.toml のパス設定](#configtoml-のパス設定)
- [RAG/Memory サーバーについて](#ragmemory-サーバーについて)
- [よくあるエラーと対処法](#よくあるエラーと対処法)

---

## 初回セットアップ

### 必要なもの

1. **credentials.json** - プロジェクトオーナーから配布
2. **config.toml** - 設定ファイル（`config.toml.example` をコピーして作成）
3. **Python 3.11+** - 実行環境

### セットアップ手順

```bash
# 1. リポジトリをクローン
git clone https://github.com/SpirrowGames/spirrow-prismind.git
cd spirrow-prismind

# 2. 依存関係をインストール
pip install -e .

# 3. 設定ファイルを作成
cp config.toml.example config.toml

# 4. config.toml を編集（パスを設定）

# 5. Google認証を実行
python scripts/init_google_auth.py
```

---

## credentials.json について

`credentials.json` はGoogle Cloud Projectの認証情報ファイルです。

### 入手方法

- **プロジェクトオーナーから配布してもらう必要があります**
- 自分で作成することはできません

### プロジェクトメンバーの登録

credentials.jsonを使用するには、Google Cloud Projectにメールアドレスが登録されている必要があります：

1. プロジェクトオーナーに自分のGoogleアカウントのメールアドレスを伝える
2. プロジェクトオーナーがGoogle Cloud Consoleでメンバーとして追加
3. 追加後、認証が可能になる

---

## token.json の取得

### MCP経由での問題

MCPサーバーとして起動すると、stdioが吸い込まれるため、OAuth認証フローが正常に動作しない場合があります。

### 解決方法

**方法1: 初期化スクリプトを使用（推奨）**

```bash
python scripts/init_google_auth.py
```

**方法2: Pythonコマンドを直接実行**

```bash
python -c "from spirrow_prismind.server import PrismindServer; import asyncio; asyncio.run(PrismindServer()._do_initialization())"
```

### 認証フローの流れ

1. スクリプトを実行
2. ブラウザが自動的に開く
3. Googleアカウントでログイン
4. アクセス許可を承認
5. token.jsonが自動的に保存される

---

## config.toml のパス設定

### 絶対パスの推奨

`credentials.json` と `token.json` のパスは**絶対パス**を使用することを推奨します。

```toml
[google]
credentials_path = "C:/Users/username/path/to/credentials.json"
token_path = "C:/Users/username/path/to/token.json"
```

### 相対パスを使用する場合

相対パスは `config.toml` のあるディレクトリからの相対パスとして解釈されます：

```toml
[google]
credentials_path = "credentials.json"  # config.toml と同じディレクトリ
token_path = "token.json"
```

---

## RAG/Memory サーバーについて

### オプショナルなサービス

RAGサーバーとMemoryサーバーは**オプショナル**です。これらが利用できない場合でも、基本的な機能は動作します。

### サービスが利用できない場合

- **プロジェクトデータ**: ローカルの `.prismind_projects.json` に保存
- **セッション状態**: ローカルファイルで管理
- **制限される機能**: 類似プロジェクト検索、ナレッジ検索

### ログメッセージ

正常な動作：
```
INFO - RAG server is not available (optional). Project data will be stored locally.
INFO - Memory server is not available (optional). Session state will use local file storage.
```

これらはエラーではなく、情報メッセージです。

---

## よくあるエラーと対処法

### 1. "プロジェクト設定の保存に失敗しました"

**原因**: 以前のバージョンではRAGサーバーエラー時に失敗していました。

**対処法**: 最新バージョンでは自動的にローカルストレージにフォールバックします。
アップデートしてください。

**正常な動作時のメッセージ例**:
```
プロジェクト 'example' をセットアップしました。
⚠️ RAGサーバーへの保存に失敗しましたが、ローカルストレージに保存しました
```

### 2. list_projects / setup_project が失敗する

**確認事項**:

1. **Google認証**: token.jsonが存在し、有効か確認
   ```bash
   python scripts/init_google_auth.py
   ```

2. **サービス状態**: check_services_status ツールで確認
   ```
   check_services_status
   ```

3. **ログ確認**: 詳細なエラーメッセージをログで確認

### 3. OAuth認証が完了しない

**症状**: ブラウザは開くが、認証後に進まない

**対処法**:
1. MCP経由ではなく、直接スクリプトを実行
2. ファイアウォールがlocalhostへの接続をブロックしていないか確認
3. 別のブラウザで試す

### 4. "credentials.json が見つかりません"

**対処法**:
1. プロジェクトオーナーから credentials.json を受け取る
2. config.toml で正しいパスを設定
3. 絶対パスを使用することを推奨

### 5. HTTP 500 エラー (RAGサーバー)

**原因**: RAGサーバー（ChromaDB等）の内部エラー

**対処法**:
- このエラーは無視できます（オプショナルサービス）
- データはローカルストレージに自動的に保存されます
- RAGサーバーが必要な場合は、サーバー管理者に連絡

---

## サポート

問題が解決しない場合は、以下の情報と共にIssueを作成してください：

1. エラーメッセージの全文
2. 実行したコマンド
3. config.toml の内容（機密情報を除く）
4. 環境情報（OS、Pythonバージョン）

Issue: https://github.com/SpirrowGames/spirrow-prismind/issues
