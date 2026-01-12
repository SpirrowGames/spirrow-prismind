"""Tests for summary templates and models."""

from datetime import datetime

import pytest

from spirrow_prismind.models.summary import (
    CheckServicesResult,
    INITIAL_PROGRESS_DATA,
    ServiceStatus,
    SUMMARY_SHEET_TEMPLATE,
    create_catalog_template,
    create_progress_template,
    create_summary_template,
)
from spirrow_prismind.models.progress import PROGRESS_SHEET_HEADERS
from spirrow_prismind.models.catalog import CATALOG_SHEET_HEADERS


class TestSummaryTemplate:
    """Tests for summary sheet template."""

    def test_create_summary_template_basic(self):
        """Test basic summary template creation."""
        result = create_summary_template(
            project_name="Test Project",
            description="A test project description",
            created_by="test_user",
        )

        assert len(result) == 11  # 11 rows in template
        assert result[1][0] == "プロジェクト名"
        assert result[1][1] == "Test Project"
        assert result[2][0] == "説明"
        assert result[2][1] == "A test project description"
        assert result[4][0] == "作成者"
        assert result[4][1] == "test_user"

    def test_create_summary_template_with_date(self):
        """Test summary template with specific date."""
        test_date = datetime(2025, 6, 15, 10, 30)
        result = create_summary_template(
            project_name="Project",
            description="Description",
            created_by="user",
            start_date=test_date,
        )

        assert result[3][0] == "開始日"
        assert result[3][1] == "2025-06-15"
        assert result[10][0] == "最終更新"
        assert result[10][1] == "2025-06-15 10:30"

    def test_create_summary_template_progress_section(self):
        """Test summary template has progress section."""
        result = create_summary_template(
            project_name="Project",
            description="Description",
            created_by="user",
        )

        assert result[6][0] == "進捗サマリ"
        assert result[7][0] == "現在のフェーズ"
        assert result[7][1] == "Phase 1"
        assert result[8][0] == "完了タスク"
        assert result[8][1] == "0"
        assert result[9][0] == "全タスク"
        assert result[9][1] == "1"


class TestProgressTemplate:
    """Tests for progress sheet template."""

    def test_create_progress_template_has_headers(self):
        """Test progress template includes headers."""
        result = create_progress_template()

        assert len(result) >= 2  # At least headers + 1 task
        assert result[0] == PROGRESS_SHEET_HEADERS

    def test_create_progress_template_has_initial_task(self):
        """Test progress template includes initial setup task."""
        result = create_progress_template()

        # Check initial task row
        initial_task = result[1]
        assert initial_task[0] == "Phase 1"
        assert initial_task[1] == "T01"
        assert "プロジェクト概要設定" in initial_task[2]
        assert initial_task[3] == "not_started"


class TestCatalogTemplate:
    """Tests for catalog sheet template."""

    def test_create_catalog_template_has_headers(self):
        """Test catalog template includes headers only."""
        result = create_catalog_template()

        assert len(result) == 1  # Headers only
        assert result[0] == CATALOG_SHEET_HEADERS


class TestServiceStatus:
    """Tests for ServiceStatus dataclass."""

    def test_service_status_available(self):
        """Test ServiceStatus for available service."""
        status = ServiceStatus(
            name="RAG Server",
            available=True,
            url="http://localhost:8000",
            message="接続成功",
        )

        assert status.name == "RAG Server"
        assert status.available is True
        assert status.url == "http://localhost:8000"
        assert status.message == "接続成功"

    def test_service_status_unavailable(self):
        """Test ServiceStatus for unavailable service."""
        status = ServiceStatus(
            name="Memory Server",
            available=False,
            url="http://localhost:8080",
            message="接続できませんでした",
        )

        assert status.available is False


class TestCheckServicesResult:
    """Tests for CheckServicesResult dataclass."""

    def test_check_services_result_all_available(self):
        """Test result when all services are available."""
        result = CheckServicesResult(
            success=True,
            services=[
                ServiceStatus(name="RAG", available=True, url="http://rag"),
                ServiceStatus(name="Memory", available=True, url="http://memory"),
            ],
            all_required_available=True,
            message="全てのサービスが利用可能です。",
        )

        assert result.success is True
        assert result.all_required_available is True
        assert len(result.services) == 2

    def test_check_services_result_partial(self):
        """Test result when some services are unavailable."""
        result = CheckServicesResult(
            success=True,
            services=[
                ServiceStatus(name="RAG", available=True, url="http://rag"),
                ServiceStatus(name="Memory", available=False, url="http://memory"),
            ],
            all_required_available=False,
            message="一部のサービスが利用不可です。",
        )

        assert result.success is True
        assert result.all_required_available is False


class TestInitialProgressData:
    """Tests for INITIAL_PROGRESS_DATA constant."""

    def test_initial_progress_data_structure(self):
        """Test INITIAL_PROGRESS_DATA has correct structure."""
        assert len(INITIAL_PROGRESS_DATA) >= 1
        first_task = INITIAL_PROGRESS_DATA[0]
        assert len(first_task) == 7  # Phase, ID, Name, Status, Blockers, CompletedAt, Notes
        assert first_task[0] == "Phase 1"
        assert first_task[1] == "T01"
