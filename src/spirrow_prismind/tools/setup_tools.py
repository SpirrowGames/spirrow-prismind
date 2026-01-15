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
    ExportServerConfigResult,
    GetConnectionInfoResult,
    GetSetupStatusResult,
    GoogleConnectionInfo,
    ImportServerConfigResult,
    ServiceConnectionInfo,
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
    "services.memory_server_type": {
        "required": False,
        "sensitive": False,
        "default": "rest",
        "description_ja": "Memory Serverプロトコル（rest: REST API / mcp: MCP over SSE）",
        "benefit_ja": "MCP対応サーバーを使用する場合は 'mcp' を指定",
        "validator": "choice",
        "allowed_values": ["rest", "mcp"],
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

        elif validator == "choice":
            allowed = setting_info.get("allowed_values", [])
            if value and value not in allowed:
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

    def check_services_status(
        self, timeout: float = 3.0, detailed: bool = False
    ) -> CheckServicesResult:
        """Check the status of RAG and Memory services.

        Args:
            timeout: Connection timeout in seconds
            detailed: If True, include protocol, latency_ms, version, last_checked

        Returns:
            CheckServicesResult
        """
        from datetime import datetime

        config_data = self._load_toml()
        now = datetime.now().isoformat() if detailed else ""

        services = []

        # Check RAG server
        rag_url = self._get_nested_value(config_data, "services.rag_server_url")
        if not rag_url:
            rag_url = SETTINGS_REGISTRY["services.rag_server_url"]["default"]

        rag_status = self._check_rag_service(rag_url, timeout, detailed, now)
        services.append(rag_status)

        # Check Memory server
        memory_url = self._get_nested_value(config_data, "services.memory_server_url")
        if not memory_url:
            memory_url = SETTINGS_REGISTRY["services.memory_server_url"]["default"]

        memory_type = self._get_nested_value(config_data, "services.memory_server_type")
        if not memory_type:
            memory_type = SETTINGS_REGISTRY["services.memory_server_type"]["default"]

        memory_status = self._check_memory_service(
            memory_url, memory_type, timeout, detailed, now
        )
        services.append(memory_status)

        # Determine overall status
        all_available = all(s.available for s in services)
        available_count = sum(1 for s in services if s.available)

        if all_available:
            message = "全てのサービスが利用可能です。"
        elif available_count == 0:
            message = (
                "全てのサービスが利用不可です。ローカルストレージモードで動作します。"
                "（RAG/Memoryサーバーはオプショナルです）"
            )
        else:
            available_names = [s.name for s in services if s.available]
            unavailable_names = [s.name for s in services if not s.available]
            message = (
                f"利用可能: {', '.join(available_names)}。"
                f"利用不可: {', '.join(unavailable_names)}（オプショナル - ローカルストレージで代替）"
            )

        return CheckServicesResult(
            success=True,
            services=services,
            all_required_available=all_available,
            message=message,
        )

    def _check_rag_service(
        self, url: str, timeout: float, detailed: bool, now: str
    ) -> ServiceStatus:
        """Check RAG server availability."""
        import time

        try:
            start = time.time()
            response = httpx.get(
                f"{url.rstrip('/')}/api/v1/heartbeat",
                timeout=timeout,
            )
            latency = (time.time() - start) * 1000 if detailed else None

            if response.status_code == 200:
                return ServiceStatus(
                    name="RAG Server",
                    available=True,
                    url=url,
                    message="接続成功。コレクションは自動作成されます。",
                    protocol="rest" if detailed else "",
                    latency_ms=round(latency, 2) if latency else None,
                    last_checked=now,
                )
            else:
                return ServiceStatus(
                    name="RAG Server",
                    available=False,
                    url=url,
                    message=f"サーバーがステータス {response.status_code} を返しました",
                    protocol="rest" if detailed else "",
                    last_checked=now,
                )
        except httpx.ConnectError:
            return ServiceStatus(
                name="RAG Server",
                available=False,
                url=url,
                message="接続できませんでした。サーバーが起動していない可能性があります。",
                protocol="rest" if detailed else "",
                last_checked=now,
            )
        except httpx.TimeoutException:
            return ServiceStatus(
                name="RAG Server",
                available=False,
                url=url,
                message="接続がタイムアウトしました。",
                protocol="rest" if detailed else "",
                last_checked=now,
            )
        except Exception as e:
            return ServiceStatus(
                name="RAG Server",
                available=False,
                url=url,
                message=f"エラー: {e}",
                protocol="rest" if detailed else "",
                last_checked=now,
            )

    def _check_memory_service(
        self, url: str, protocol: str, timeout: float, detailed: bool, now: str
    ) -> ServiceStatus:
        """Check Memory server availability.

        Args:
            url: Memory server URL
            protocol: Protocol type ("rest" or "mcp")
            timeout: Connection timeout
            detailed: Include detailed timing info
            now: Timestamp for last_checked
        """
        import time

        # Determine endpoint based on protocol
        if protocol == "mcp":
            check_url = f"{url.rstrip('/')}/sse"
            protocol_label = "MCP/SSE"
        else:
            check_url = f"{url.rstrip('/')}/health"
            protocol_label = "REST"

        try:
            start = time.time()
            if protocol == "mcp":
                # SSE is a streaming endpoint that never completes
                # Use stream() to check headers without waiting for body
                with httpx.stream("GET", check_url, timeout=timeout) as response:
                    latency = (time.time() - start) * 1000 if detailed else None
                    # Check if we get a valid SSE response
                    content_type = response.headers.get("content-type", "")
                    if response.status_code == 200 and "text/event-stream" in content_type:
                        return ServiceStatus(
                            name=f"Memory Server ({protocol_label})",
                            available=True,
                            url=url,
                            message="接続成功。MCP/SSEでセッション状態を永続化できます。",
                            protocol=protocol if detailed else "",
                            latency_ms=round(latency, 2) if latency else None,
                            last_checked=now,
                        )
                    elif response.status_code == 200:
                        # 200 but not SSE - still available
                        return ServiceStatus(
                            name=f"Memory Server ({protocol_label})",
                            available=True,
                            url=url,
                            message="接続成功。",
                            protocol=protocol if detailed else "",
                            latency_ms=round(latency, 2) if latency else None,
                            last_checked=now,
                        )
                    else:
                        return ServiceStatus(
                            name=f"Memory Server ({protocol_label})",
                            available=False,
                            url=url,
                            message=f"サーバーがステータス {response.status_code} を返しました",
                            protocol=protocol if detailed else "",
                            last_checked=now,
                        )
            else:
                # REST protocol - normal GET request
                response = httpx.get(check_url, timeout=timeout)
                latency = (time.time() - start) * 1000 if detailed else None
                if 200 <= response.status_code < 300:
                    return ServiceStatus(
                        name=f"Memory Server ({protocol_label})",
                        available=True,
                        url=url,
                        message="接続成功。セッション状態を永続化できます。",
                        protocol=protocol if detailed else "",
                        latency_ms=round(latency, 2) if latency else None,
                        last_checked=now,
                    )
                else:
                    return ServiceStatus(
                        name=f"Memory Server ({protocol_label})",
                        available=False,
                        url=url,
                        message=f"サーバーがステータス {response.status_code} を返しました",
                        protocol=protocol if detailed else "",
                        last_checked=now,
                    )
        except httpx.ConnectError:
            return ServiceStatus(
                name=f"Memory Server ({protocol_label})",
                available=False,
                url=url,
                message="接続できませんでした。サーバーが起動していない可能性があります。",
                protocol=protocol if detailed else "",
                last_checked=now,
            )
        except httpx.TimeoutException:
            return ServiceStatus(
                name=f"Memory Server ({protocol_label})",
                available=False,
                url=url,
                message="接続がタイムアウトしました。",
                protocol=protocol if detailed else "",
                last_checked=now,
            )
        except Exception as e:
            return ServiceStatus(
                name=f"Memory Server ({protocol_label})",
                available=False,
                url=url,
                message=f"エラー: {e}",
                protocol=protocol if detailed else "",
                last_checked=now,
            )

    def get_connection_info(self, timeout: float = 3.0) -> GetConnectionInfoResult:
        """Get detailed connection information for all services.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            GetConnectionInfoResult
        """
        from datetime import datetime

        config_data = self._load_toml()
        now = datetime.now().isoformat()

        # Memory Server info
        memory_url = self._get_nested_value(config_data, "services.memory_server_url")
        if not memory_url:
            memory_url = SETTINGS_REGISTRY["services.memory_server_url"]["default"]

        memory_type = self._get_nested_value(config_data, "services.memory_server_type")
        if not memory_type:
            memory_type = SETTINGS_REGISTRY["services.memory_server_type"]["default"]

        memory_info = self._get_memory_connection_info(memory_url, memory_type, timeout, now)

        # RAG Server info
        rag_url = self._get_nested_value(config_data, "services.rag_server_url")
        if not rag_url:
            rag_url = SETTINGS_REGISTRY["services.rag_server_url"]["default"]

        rag_collection = self._get_nested_value(config_data, "services.rag_collection")
        if not rag_collection:
            rag_collection = SETTINGS_REGISTRY["services.rag_collection"]["default"]

        rag_info = self._get_rag_connection_info(rag_url, rag_collection, timeout, now)

        # Google info (basic - we can't check auth state without credentials)
        google_info = GoogleConnectionInfo(
            authenticated=False,  # Would need to check token
            user="",
            scopes=[],
        )

        return GetConnectionInfoResult(
            success=True,
            memory_server=memory_info,
            rag_server=rag_info,
            google=google_info,
            message="接続情報を取得しました。",
        )

    def _get_memory_connection_info(
        self, url: str, protocol: str, timeout: float, now: str
    ) -> ServiceConnectionInfo:
        """Get connection info for Memory server."""
        import time

        if protocol == "mcp":
            check_url = f"{url.rstrip('/')}/sse"
        else:
            check_url = f"{url.rstrip('/')}/health"

        try:
            start = time.time()
            if protocol == "mcp":
                with httpx.stream("GET", check_url, timeout=timeout) as response:
                    latency = (time.time() - start) * 1000
                    content_type = response.headers.get("content-type", "")
                    if response.status_code == 200:
                        return ServiceConnectionInfo(
                            name="Memory Server",
                            url=url,
                            protocol=protocol,
                            status="connected",
                            latency_ms=round(latency, 2),
                            last_checked=now,
                        )
            else:
                response = httpx.get(check_url, timeout=timeout)
                latency = (time.time() - start) * 1000
                if 200 <= response.status_code < 300:
                    return ServiceConnectionInfo(
                        name="Memory Server",
                        url=url,
                        protocol=protocol,
                        status="connected",
                        latency_ms=round(latency, 2),
                        last_checked=now,
                    )

            return ServiceConnectionInfo(
                name="Memory Server",
                url=url,
                protocol=protocol,
                status="disconnected",
                last_checked=now,
            )
        except Exception:
            return ServiceConnectionInfo(
                name="Memory Server",
                url=url,
                protocol=protocol,
                status="disconnected",
                last_checked=now,
            )

    def _get_rag_connection_info(
        self, url: str, collection: str, timeout: float, now: str
    ) -> ServiceConnectionInfo:
        """Get connection info for RAG server."""
        import time

        try:
            start = time.time()
            response = httpx.get(
                f"{url.rstrip('/')}/api/v1/heartbeat",
                timeout=timeout,
            )
            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                return ServiceConnectionInfo(
                    name="RAG Server",
                    url=url,
                    protocol="rest",
                    status="connected",
                    latency_ms=round(latency, 2),
                    collection=collection,
                    last_checked=now,
                )

            return ServiceConnectionInfo(
                name="RAG Server",
                url=url,
                protocol="rest",
                status="disconnected",
                collection=collection,
                last_checked=now,
            )
        except Exception:
            return ServiceConnectionInfo(
                name="RAG Server",
                url=url,
                protocol="rest",
                status="disconnected",
                collection=collection,
                last_checked=now,
            )

    def export_server_config(self) -> ExportServerConfigResult:
        """Export server configuration for sharing with team members.

        Returns a sanitized config without sensitive information.

        Returns:
            ExportServerConfigResult
        """
        config_data = self._load_toml()

        # Create sanitized config
        export_data = {}

        # Services section (safe to share)
        services = config_data.get("services", {})
        if services:
            export_data["services"] = {
                "memory_server_url": services.get(
                    "memory_server_url",
                    SETTINGS_REGISTRY["services.memory_server_url"]["default"],
                ),
                "memory_server_type": services.get(
                    "memory_server_type",
                    SETTINGS_REGISTRY["services.memory_server_type"]["default"],
                ),
                "rag_server_url": services.get(
                    "rag_server_url",
                    SETTINGS_REGISTRY["services.rag_server_url"]["default"],
                ),
                "rag_collection": services.get(
                    "rag_collection",
                    SETTINGS_REGISTRY["services.rag_collection"]["default"],
                ),
            }

        # Log section (safe to share)
        log = config_data.get("log", {})
        if log:
            export_data["log"] = {
                "level": log.get("level", "INFO"),
                "format": log.get("format", "text"),
            }

        # Session section (only auto_save_interval)
        session = config_data.get("session", {})
        if session:
            export_data["session"] = {
                "auto_save_interval": session.get("auto_save_interval", 20),
            }

        # Note: google section is excluded (contains paths specific to each machine)
        # Note: user_name is excluded (each user has their own)

        try:
            import io
            buffer = io.BytesIO()
            tomli_w.dump(export_data, buffer)
            config_str = buffer.getvalue().decode("utf-8")

            return ExportServerConfigResult(
                success=True,
                config=config_str,
                message="サーバー設定をエクスポートしました。チームメンバーと共有できます。",
            )
        except Exception as e:
            return ExportServerConfigResult(
                success=False,
                message=f"設定のエクスポートに失敗しました: {e}",
            )

    def import_server_config(self, config: str) -> ImportServerConfigResult:
        """Import server configuration from a shared config string.

        Args:
            config: TOML formatted configuration string

        Returns:
            ImportServerConfigResult
        """
        try:
            import_data = tomllib.loads(config)
        except Exception as e:
            return ImportServerConfigResult(
                success=False,
                validation_errors=[f"TOML解析エラー: {e}"],
                message="設定ファイルの形式が正しくありません。",
            )

        imported = []
        skipped = []
        errors = []

        # Load current config
        current_config = self._load_toml()

        # Import services section
        if "services" in import_data:
            services = import_data["services"]
            for key in ["memory_server_url", "memory_server_type", "rag_server_url", "rag_collection"]:
                if key in services:
                    setting_key = f"services.{key}"
                    validation_errors = self._validate_value(setting_key, services[key])
                    if validation_errors:
                        errors.extend(validation_errors)
                        skipped.append(setting_key)
                    else:
                        self._set_nested_value(current_config, setting_key, services[key])
                        imported.append(setting_key)

        # Import log section
        if "log" in import_data:
            log = import_data["log"]
            for key in ["level", "format"]:
                if key in log:
                    setting_key = f"log.{key}"
                    validation_errors = self._validate_value(setting_key, log[key])
                    if validation_errors:
                        errors.extend(validation_errors)
                        skipped.append(setting_key)
                    else:
                        self._set_nested_value(current_config, setting_key, log[key])
                        imported.append(setting_key)

        # Import session section (only auto_save_interval)
        if "session" in import_data:
            session = import_data["session"]
            if "auto_save_interval" in session:
                setting_key = "session.auto_save_interval"
                validation_errors = self._validate_value(setting_key, session["auto_save_interval"])
                if validation_errors:
                    errors.extend(validation_errors)
                    skipped.append(setting_key)
                else:
                    self._set_nested_value(current_config, setting_key, session["auto_save_interval"])
                    imported.append(setting_key)

        # Save updated config
        if imported:
            try:
                self._save_toml(current_config)
            except Exception as e:
                return ImportServerConfigResult(
                    success=False,
                    validation_errors=[f"保存エラー: {e}"],
                    message="設定の保存に失敗しました。",
                )

        return ImportServerConfigResult(
            success=len(imported) > 0,
            imported_settings=imported,
            skipped_settings=skipped,
            validation_errors=errors,
            message=f"{len(imported)} 件の設定をインポートしました。"
            + (f" {len(skipped)} 件はスキップされました。" if skipped else ""),
        )
