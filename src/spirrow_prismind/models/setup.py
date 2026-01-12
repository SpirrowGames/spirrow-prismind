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
