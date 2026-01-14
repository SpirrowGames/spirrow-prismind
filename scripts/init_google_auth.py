#!/usr/bin/env python3
"""
Google OAuth認証の初期化スクリプト

MCP経由ではstdioが吸い込まれるため、token.jsonを事前に取得するには
このスクリプトを直接実行してください。

使用方法:
    python scripts/init_google_auth.py

    または、config.tomlの場所を指定する場合:
    PRISMIND_CONFIG=/path/to/config.toml python scripts/init_google_auth.py
"""

import os
import sys
from pathlib import Path


def main():
    """Run Google OAuth initialization."""
    print("=" * 60)
    print("Spirrow-Prismind Google OAuth 初期化")
    print("=" * 60)
    print()

    # Determine config path
    config_path = os.environ.get("PRISMIND_CONFIG", "config.toml")
    config_dir = Path(config_path).parent

    print(f"設定ファイル: {config_path}")

    # Try to load config
    credentials_path = None
    token_path = None

    try:
        import tomllib
        if Path(config_path).exists():
            with open(config_path, "rb") as f:
                config = tomllib.load(f)

            google_config = config.get("google", {})
            cred_path = google_config.get("credentials_path", "credentials.json")
            tok_path = google_config.get("token_path", "token.json")

            # Resolve relative paths
            cred_path = Path(cred_path)
            if not cred_path.is_absolute():
                cred_path = config_dir / cred_path
            credentials_path = str(cred_path)

            tok_path = Path(tok_path)
            if not tok_path.is_absolute():
                tok_path = config_dir / tok_path
            token_path = str(tok_path)
        else:
            print(f"警告: 設定ファイルが見つかりません: {config_path}")
            print("デフォルトパスを使用します。")
    except Exception as e:
        print(f"警告: 設定ファイルの読み込みに失敗: {e}")
        print("デフォルトパスを使用します。")

    # Default paths if not set
    if not credentials_path:
        credentials_path = str(config_dir / "credentials.json")
    if not token_path:
        token_path = str(config_dir / "token.json")

    print(f"credentials.json: {credentials_path}")
    print(f"token.json: {token_path}")
    print()

    # Check if credentials.json exists
    if not Path(credentials_path).exists():
        print("エラー: credentials.json が見つかりません。")
        print()
        print("credentials.json はプロジェクトオーナーから配布されます。")
        print("ファイルを受け取り、以下の場所に配置してください:")
        print(f"  {credentials_path}")
        print()
        print("また、プロジェクトメンバーとしてメールアドレスの登録も必要です。")
        sys.exit(1)

    # Check if token.json already exists
    if Path(token_path).exists():
        print("token.json は既に存在します。")
        response = input("再認証しますか？ (y/N): ").strip().lower()
        if response != "y":
            print("既存のトークンを使用します。")
            sys.exit(0)
        print()

    # Run OAuth flow
    print("OAuth認証フローを開始します...")
    print("ブラウザが開きます。Googleアカウントでログインしてください。")
    print()

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow

        SCOPES = [
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets",
        ]

        flow = InstalledAppFlow.from_client_secrets_file(
            credentials_path, SCOPES
        )
        creds = flow.run_local_server(port=0, timeout_seconds=120)

        # Save the token
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as token:
            token.write(creds.to_json())

        print()
        print("=" * 60)
        print("認証成功!")
        print("=" * 60)
        print()
        print(f"トークンが保存されました: {token_path}")
        print()
        print("これでMCPサーバーを起動できます。")

    except Exception as e:
        print()
        print("=" * 60)
        print("認証失敗")
        print("=" * 60)
        print()
        print(f"エラー: {e}")
        print()
        print("トラブルシューティング:")
        print("1. credentials.json が正しいか確認してください")
        print("2. プロジェクトメンバーとしてメールアドレスが登録されているか確認してください")
        print("3. ブラウザでGoogleアカウントにログインできるか確認してください")
        sys.exit(1)


if __name__ == "__main__":
    main()
