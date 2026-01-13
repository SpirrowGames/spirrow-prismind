"""Setup wizard tools for Spirrow-Prismind."""

import logging
import os
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import tomli_w

import httpx

from ..models import (
    CheckServicesResult,
    ConfigureResult,
    GetSetupStatusResult,
    ServiceStatus,
    SettingStatus,
)

logger = logging.getLogger(__name__)


# Setting definitions with metadata
SETTINGS_REGISTRY: dict[str, dict[str, Any]] = {
    # Required settings
    "google.credentials_path": {
        "required": True,
        "sensitive": False,
        "default": "credentials.json",
        "description_ja": "Google OAuth認証ファイルのパス",
        "benefit_ja": None,
        "validator": "path_exists",
    },
    "google.projects_folder_id": {
        "required": True,
        "sensitive": False,
        "default": "",
        "description_ja": "プロジェクトの親フォルダID（Google Drive）",
        "benefit_ja": None,
        "validator": "non_empty",
    },
    "session.user_name": {
        "required": True,
        "sensitive": False,
        "default": "",
        "description_ja": "ユーザー名（複数PC間で共通、セッション状態の識別に使用）",
        "benefit_ja": None,
        "validator": "non_empty",
    },
    # Optional settings
    "google.token_path": {
        "required": False,
        "sensitive": False,
        "default": "token.json",
        "description_ja": "トークン保存先",
        "benefit_ja": "認証トークンの保存場所をカスタマイズ",
        "validator": None,
    },
    "services.memory_server_url": {
        "required": False,
        "sensitive": False,
        "default": "http://localhost:8080",
        "description_ja": "Memory Server URL",
        "benefit_ja": "セッション状態の永続化、再起動後も状態を維持",
        "validator": "url",
    },
    "services.rag_server_url": {
        "required": False,
        "sensitive": False,
        "default": "http://localhost:8000",
        "description_ja": "RAG Server URL",
        "benefit_ja": "知識検索、類似プロジェクト検索、目録検索機能",
        "validator": "url",
    },
    "services.rag_collection": {
        "required": False,
        "sensitive": False,
        "default": "prismind",
        "description_ja": "RAGコレクション名",
        "benefit_ja": "RAG検索のコレクションを指定",
        "validator": None,
    },
    "log.level": {
        "required": False,
        "sensitive": False,
        "default": "INFO",
        "description_ja": "ログレベル",
        "benefit_ja": "デバッグ時のログ詳細化（DEBUG, INFO, WARNING, ERROR）",
        "validator": "log_level",
        "allowed_values": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "session.auto_save_interval": {
        "required": False,
        "sensitive": False,
        "default": 20,
        "description_ja": "自動保存間隔（メッセージ数）",
        "benefit_ja": "セッションの自動保存頻度を調整",
        "validator": "positive_int",
    },
}


class SetupTools:
    """Tools for setup wizard."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize setup tools.

        Args:
            config_path: Path to config.toml file
        """
        self.config_path = self._resolve_config_path(config_path)

    def _resolve_config_path(self, config_path: Optional[str]) -> Path:
        """Resolve config file path."""
        if config_path:
            return Path(config_path)

        env_path = os.environ.get("PRISMIND_CONFIG")
        if env_path:
            return Path(env_path)

        # Default locations
        candidates = [
            Path("config.toml"),
            Path.home() / ".config" / "spirrow-prismind" / "config.toml",
        ]

        for p in candidates:
            if p.exists():
                return p

        # Return default (may not exist)
        return Path("config.toml")

    def _load_toml(self) -> dict:
        """Load current TOML config."""
        if not self.config_path.exists():
            return {}

        with open(self.config_path, "rb") as f:
            return tomllib.load(f)

    def _save_toml(self, data: dict) -> None:
        """Save TOML config."""
        # Ensure parent directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_path, "wb") as f:
            tomli_w.dump(data, f)

    def _get_nested_value(self, data: dict, key: str) -> Optional[Any]:
        """Get nested value from dict using dot notation."""
        parts = key.split(".")
        current = data
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def _set_nested_value(self, data: dict, key: str, value: Any) -> dict:
        """Set nested value in dict using dot notation."""
        parts = key.split(".")
        current = data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        return data

    def _mask_sensitive(self, value: str, setting_info: dict) -> str:
        """Mask sensitive values."""
        if setting_info.get("sensitive") and value:
            if len(value) > 4:
                return value[:2] + "*" * (len(value) - 4) + value[-2:]
            return "*" * len(value)
        return value

    def _validate_value(self, key: str, value: Any) -> list[str]:
        """Validate a setting value."""
        errors = []
        setting_info = SETTINGS_REGISTRY.get(key, {})
        validator = setting_info.get("validator")

        if validator == "non_empty":
            if not value or (isinstance(value, str) and not value.strip()):
                errors.append(f"'{key}' は空にできません")

        elif validator == "path_exists":
            # Only warn, don't block - file might be created later
            if value and not Path(value).exists():
                logger.warning(f"File not found (will be checked at runtime): {value}")

        elif validator == "url":
            if value and not (value.startswith("http://") or value.startswith("https://")):
                errors.append(f"URLは http:// または https:// で始まる必要があります: {value}")

        elif validator == "log_level":
            allowed = setting_info.get("allowed_values", [])
            if value and value.upper() not in allowed:
                errors.append(f"'{key}' は {allowed} のいずれかである必要があります")

        elif validator == "positive_int":
            try:
                int_val = int(value)
                if int_val < 1:
                    errors.append(f"'{key}' は1以上の整数である必要があります")
            except (ValueError, TypeError):
                errors.append(f"'{key}' は整数である必要があります")

        return errors

    def get_setup_status(self) -> GetSetupStatusResult:
        """Get current setup status."""
        config_data = self._load_toml()

        required_settings = []
        optional_settings = []
        all_required_configured = True

        for key, info in SETTINGS_REGISTRY.items():
            current_value = self._get_nested_value(config_data, key)
            default_value = info["default"]

            # Check if configured (has a non-empty value)
            configured = current_value is not None and current_value != ""

            # For required settings with non_empty validator, empty string = not configured
            if info["required"] and not configured:
                all_required_configured = False

            # Mask sensitive values
            display_value = None
            if current_value is not None:
                display_value = self._mask_sensitive(str(current_value), info)

            status = SettingStatus(
                name=key,
                required=info["required"],
                configured=configured,
                current_value=display_value,
                default_value=str(default_value),
                description=info["description_ja"],
                benefit=info.get("benefit_ja"),
            )

            if info["required"]:
                required_settings.append(status)
            else:
                optional_settings.append(status)

        # Build message
        if all_required_configured:
            message = "全ての必須設定が完了しています。Spirrow-Prismindを使用する準備ができています。"
        else:
            missing = [s.name for s in required_settings if not s.configured]
            message = f"以下の必須設定が必要です: {', '.join(missing)}"

        return GetSetupStatusResult(
            success=True,
            ready=all_required_configured,
            required_settings=required_settings,
            optional_settings=optional_settings,
            config_file_path=str(self.config_path.absolute()),
            config_file_exists=self.config_path.exists(),
            message=message,
        )

    def configure(
        self,
        setting: str,
        value: str,
    ) -> ConfigureResult:
        """Configure a setting.

        Args:
            setting: Setting name (e.g., "google.credentials_path")
            value: New value

        Returns:
            ConfigureResult
        """
        # Validate setting name
        if setting not in SETTINGS_REGISTRY:
            available = ", ".join(SETTINGS_REGISTRY.keys())
            return ConfigureResult(
                success=False,
                setting_name=setting,
                message=f"不明な設定: '{setting}'。利用可能な設定: {available}",
            )

        # Validate value
        setting_info = SETTINGS_REGISTRY[setting]
        validation_errors = self._validate_value(setting, value)

        if validation_errors:
            return ConfigureResult(
                success=False,
                setting_name=setting,
                new_value=value,
                validation_errors=validation_errors,
                message=f"設定値の検証に失敗しました: {'; '.join(validation_errors)}",
            )

        # Convert value type if needed
        converted_value: Any = value
        if setting_info.get("validator") == "positive_int":
            converted_value = int(value)
        elif setting_info.get("validator") == "log_level":
            converted_value = value.upper()

        # Load current config
        config_data = self._load_toml()
        old_value = self._get_nested_value(config_data, setting)

        # Update config
        self._set_nested_value(config_data, setting, converted_value)

        # Save config
        try:
            self._save_toml(config_data)
            logger.info(f"Configuration saved: {setting} = {converted_value}")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return ConfigureResult(
                success=False,
                setting_name=setting,
                message=f"設定ファイルの保存に失敗しました: {e}",
            )

        return ConfigureResult(
            success=True,
            setting_name=setting,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(converted_value),
            message=f"'{setting}' を '{converted_value}' に設定しました。",
        )

    def get_available_settings(self) -> list[str]:
        """Get list of available setting names."""
        return list(SETTINGS_REGISTRY.keys())

    def check_services_status(self, timeout: float = 3.0) -> CheckServicesResult:
        """Check the status of RAG and Memory services.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            CheckServicesResult
        """
        config_data = self._load_toml()

        services = []

        # Check RAG server
        rag_url = self._get_nested_value(config_data, "services.rag_server_url")
        if not rag_url:
            rag_url = SETTINGS_REGISTRY["services.rag_server_url"]["default"]

        rag_status = self._check_rag_service(rag_url, timeout)
        services.append(rag_status)

        # Check Memory server
        memory_url = self._get_nested_value(config_data, "services.memory_server_url")
        if not memory_url:
            memory_url = SETTINGS_REGISTRY["services.memory_server_url"]["default"]

        memory_status = self._check_memory_service(memory_url, timeout)
        services.append(memory_status)

        # Determine overall status
        all_available = all(s.available for s in services)
        available_count = sum(1 for s in services if s.available)

        if all_available:
            message = "全てのサービスが利用可能です。"
        elif available_count == 0:
            message = "全てのサービスが利用不可です。インメモリモードで動作します。"
        else:
            available_names = [s.name for s in services if s.available]
            unavailable_names = [s.name for s in services if not s.available]
            message = f"利用可能: {', '.join(available_names)}。利用不可: {', '.join(unavailable_names)}"

        return CheckServicesResult(
            success=True,
            services=services,
            all_required_available=all_available,
            message=message,
        )

    def _check_rag_service(self, url: str, timeout: float) -> ServiceStatus:
        """Check RAG server availability."""
        try:
            response = httpx.get(
                f"{url.rstrip('/')}/api/v1/heartbeat",
                timeout=timeout,
            )
            if response.status_code == 200:
                return ServiceStatus(
                    name="RAG Server",
                    available=True,
                    url=url,
                    message="接続成功。コレクションは自動作成されます。",
                )
            else:
                return ServiceStatus(
                    name="RAG Server",
                    available=False,
                    url=url,
                    message=f"サーバーがステータス {response.status_code} を返しました",
                )
        except httpx.ConnectError:
            return ServiceStatus(
                name="RAG Server",
                available=False,
                url=url,
                message="接続できませんでした。サーバーが起動していない可能性があります。",
            )
        except httpx.TimeoutException:
            return ServiceStatus(
                name="RAG Server",
                available=False,
                url=url,
                message="接続がタイムアウトしました。",
            )
        except Exception as e:
            return ServiceStatus(
                name="RAG Server",
                available=False,
                url=url,
                message=f"エラー: {e}",
            )

    def _check_memory_service(self, url: str, timeout: float) -> ServiceStatus:
        """Check Memory server availability."""
        try:
            response = httpx.get(
                f"{url.rstrip('/')}/health",
                timeout=timeout,
            )
            # Accept any 2xx response
            if 200 <= response.status_code < 300:
                return ServiceStatus(
                    name="Memory Server",
                    available=True,
                    url=url,
                    message="接続成功。セッション状態を永続化できます。",
                )
            else:
                return ServiceStatus(
                    name="Memory Server",
                    available=False,
                    url=url,
                    message=f"サーバーがステータス {response.status_code} を返しました",
                )
        except httpx.ConnectError:
            return ServiceStatus(
                name="Memory Server",
                available=False,
                url=url,
                message="接続できませんでした。サーバーが起動していない可能性があります。",
            )
        except httpx.TimeoutException:
            return ServiceStatus(
                name="Memory Server",
                available=False,
                url=url,
                message="接続がタイムアウトしました。",
            )
        except Exception as e:
            return ServiceStatus(
                name="Memory Server",
                available=False,
                url=url,
                message=f"エラー: {e}",
            )
