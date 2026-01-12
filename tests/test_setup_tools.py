"""Tests for SetupTools."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spirrow_prismind.tools.setup_tools import SetupTools, SETTINGS_REGISTRY


class TestGetSetupStatus:
    """Tests for get_setup_status method."""

    def test_get_setup_status_no_config(self, tmp_path):
        """Test status when config file doesn't exist."""
        config_path = tmp_path / "nonexistent.toml"
        tools = SetupTools(str(config_path))

        result = tools.get_setup_status()

        assert result.success is True
        assert result.ready is False  # Not ready without required settings
        assert result.config_file_exists is False
        assert len(result.required_settings) > 0

    def test_get_setup_status_partial_config(self, tmp_path):
        """Test status with partially configured file."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("""
[google]
credentials_path = "credentials.json"

[session]
user_name = ""
""")
        tools = SetupTools(str(config_path))

        result = tools.get_setup_status()

        assert result.success is True
        assert result.ready is False  # Missing required settings
        assert result.config_file_exists is True

        # Check that some are configured, some not
        configured_names = [s.name for s in result.required_settings if s.configured]
        unconfigured_names = [s.name for s in result.required_settings if not s.configured]
        assert "google.credentials_path" in configured_names
        assert "session.user_name" in unconfigured_names

    def test_get_setup_status_complete_config(self, tmp_path):
        """Test status when all required settings are configured."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("""
[google]
credentials_path = "credentials.json"
projects_folder_id = "folder123"

[session]
user_name = "test_user"
""")
        tools = SetupTools(str(config_path))

        result = tools.get_setup_status()

        assert result.success is True
        assert result.ready is True
        assert "準備ができています" in result.message


class TestConfigure:
    """Tests for configure method."""

    def test_configure_valid_setting(self, tmp_path):
        """Test configuring a valid setting."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("")
        tools = SetupTools(str(config_path))

        result = tools.configure("session.user_name", "new_user")

        assert result.success is True
        assert result.setting_name == "session.user_name"
        assert result.new_value == "new_user"
        assert "設定しました" in result.message

        # Verify file was updated
        content = config_path.read_text()
        assert "new_user" in content

    def test_configure_invalid_setting(self, tmp_path):
        """Test configuring an invalid setting name."""
        config_path = tmp_path / "config.toml"
        tools = SetupTools(str(config_path))

        result = tools.configure("invalid.setting", "value")

        assert result.success is False
        assert "不明な設定" in result.message

    def test_configure_invalid_url(self, tmp_path):
        """Test configuring URL with invalid value."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("")
        tools = SetupTools(str(config_path))

        result = tools.configure("services.rag_server_url", "not-a-url")

        assert result.success is False
        assert len(result.validation_errors) > 0
        assert "http://" in result.validation_errors[0] or "https://" in result.validation_errors[0]

    def test_configure_log_level_uppercase(self, tmp_path):
        """Test log level is converted to uppercase."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("")
        tools = SetupTools(str(config_path))

        result = tools.configure("log.level", "debug")

        assert result.success is True
        assert result.new_value == "DEBUG"

    def test_configure_positive_int(self, tmp_path):
        """Test positive integer validation."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("")
        tools = SetupTools(str(config_path))

        # Valid positive int
        result = tools.configure("session.auto_save_interval", "30")
        assert result.success is True
        assert result.new_value == "30"

        # Invalid (negative)
        result = tools.configure("session.auto_save_interval", "-5")
        assert result.success is False

        # Invalid (not a number)
        result = tools.configure("session.auto_save_interval", "abc")
        assert result.success is False


class TestCheckServicesStatus:
    """Tests for check_services_status method."""

    @patch("spirrow_prismind.tools.setup_tools.httpx.get")
    def test_check_services_all_available(self, mock_get, tmp_path):
        """Test when all services are available."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("""
[services]
rag_server_url = "http://localhost:8000"
memory_server_url = "http://localhost:8080"
""")
        tools = SetupTools(str(config_path))

        # Mock successful responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = tools.check_services_status()

        assert result.success is True
        assert result.all_required_available is True
        assert len(result.services) == 2
        assert all(s.available for s in result.services)
        assert "利用可能" in result.message

    @patch("spirrow_prismind.tools.setup_tools.httpx.get")
    def test_check_services_none_available(self, mock_get, tmp_path):
        """Test when no services are available."""
        import httpx

        config_path = tmp_path / "config.toml"
        config_path.write_text("")
        tools = SetupTools(str(config_path))

        # Mock connection errors
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        result = tools.check_services_status()

        assert result.success is True
        assert result.all_required_available is False
        assert all(not s.available for s in result.services)
        assert "インメモリモード" in result.message

    @patch("spirrow_prismind.tools.setup_tools.httpx.get")
    def test_check_services_partial_availability(self, mock_get, tmp_path):
        """Test when some services are available."""
        import httpx

        config_path = tmp_path / "config.toml"
        config_path.write_text("")
        tools = SetupTools(str(config_path))

        # Mock: RAG available, Memory not
        def mock_response(url, **kwargs):
            if "8000" in url or "heartbeat" in url:
                response = MagicMock()
                response.status_code = 200
                return response
            raise httpx.ConnectError("Connection refused")

        mock_get.side_effect = mock_response

        result = tools.check_services_status()

        assert result.success is True
        assert result.all_required_available is False
        available_count = sum(1 for s in result.services if s.available)
        assert available_count == 1

    @patch("spirrow_prismind.tools.setup_tools.httpx.get")
    def test_check_services_timeout(self, mock_get, tmp_path):
        """Test when service times out."""
        import httpx

        config_path = tmp_path / "config.toml"
        config_path.write_text("")
        tools = SetupTools(str(config_path))

        mock_get.side_effect = httpx.TimeoutException("Timeout")

        result = tools.check_services_status()

        assert result.success is True
        assert all(not s.available for s in result.services)
        assert any("タイムアウト" in s.message for s in result.services)


class TestGetAvailableSettings:
    """Tests for get_available_settings method."""

    def test_get_available_settings(self, tmp_path):
        """Test getting list of available settings."""
        config_path = tmp_path / "config.toml"
        tools = SetupTools(str(config_path))

        settings = tools.get_available_settings()

        assert len(settings) > 0
        assert "google.credentials_path" in settings
        assert "session.user_name" in settings
        assert "services.rag_server_url" in settings


class TestSettingsRegistry:
    """Tests for SETTINGS_REGISTRY constant."""

    def test_required_settings_exist(self):
        """Test that required settings are defined."""
        required = [k for k, v in SETTINGS_REGISTRY.items() if v["required"]]
        assert "google.credentials_path" in required
        assert "google.projects_folder_id" in required
        assert "session.user_name" in required

    def test_optional_settings_have_benefits(self):
        """Test that optional settings have benefit descriptions."""
        optional = [k for k, v in SETTINGS_REGISTRY.items() if not v["required"]]
        for key in optional:
            setting = SETTINGS_REGISTRY[key]
            assert setting.get("benefit_ja") is not None, f"{key} should have benefit_ja"

    def test_all_settings_have_description(self):
        """Test that all settings have descriptions."""
        for key, setting in SETTINGS_REGISTRY.items():
            assert setting.get("description_ja"), f"{key} should have description_ja"
