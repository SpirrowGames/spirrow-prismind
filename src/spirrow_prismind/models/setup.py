"""Setup wizard models."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SettingStatus:
    """Status of a single setting."""

    name: str
    required: bool
    configured: bool
    current_value: Optional[str]  # Masked if sensitive
    default_value: str
    description: str
    benefit: Optional[str]  # None for required settings


@dataclass
class GetSetupStatusResult:
    """Result of get_setup_status tool."""

    success: bool
    ready: bool  # All required settings configured
    required_settings: list[SettingStatus] = field(default_factory=list)
    optional_settings: list[SettingStatus] = field(default_factory=list)
    config_file_path: str = ""
    config_file_exists: bool = False
    message: str = ""


@dataclass
class ConfigureResult:
    """Result of configure tool."""

    success: bool
    setting_name: str = ""
    old_value: Optional[str] = None
    new_value: str = ""
    validation_errors: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class ServiceConnectionInfo:
    """Connection info for a single service."""

    name: str
    url: str
    protocol: str = ""  # "rest", "mcp", etc.
    status: str = ""  # "connected", "disconnected", "unknown"
    latency_ms: Optional[float] = None
    version: str = ""
    collection: str = ""  # For RAG
    last_checked: str = ""


@dataclass
class GoogleConnectionInfo:
    """Connection info for Google services."""

    authenticated: bool
    user: str = ""
    scopes: list[str] = field(default_factory=list)


@dataclass
class GetConnectionInfoResult:
    """Result of get_connection_info tool."""

    success: bool
    memory_server: Optional[ServiceConnectionInfo] = None
    rag_server: Optional[ServiceConnectionInfo] = None
    google: Optional[GoogleConnectionInfo] = None
    message: str = ""


@dataclass
class ExportServerConfigResult:
    """Result of export_server_config tool."""

    success: bool
    config: str = ""  # TOML formatted config (without secrets)
    message: str = ""


@dataclass
class ImportServerConfigResult:
    """Result of import_server_config tool."""

    success: bool
    imported_settings: list[str] = field(default_factory=list)
    skipped_settings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    message: str = ""
