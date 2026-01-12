"""Tests for KnowledgeTools."""

import pytest


class TestAddKnowledge:
    """Tests for add_knowledge method."""

    def test_add_knowledge_invalid_category(self, knowledge_tools):
        """Test add_knowledge fails with invalid category."""
        result = knowledge_tools.add_knowledge(
            content="Some knowledge",
            category="InvalidCategory",
        )

        assert result.success is False
        assert "無効なカテゴリ" in result.message

    def test_add_knowledge_success(self, knowledge_tools, mock_rag_client, project_tools):
        """Test successful knowledge addition."""
        project_tools.setup_project(
            project="know_proj",
            name="Knowledge Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = knowledge_tools.add_knowledge(
            content="When using async/await, always handle exceptions properly.",
            category="技術Tips",
            tags=["async", "error-handling"],
            source="Code review",
        )

        assert result.success is True
        assert result.knowledge_id != ""
        assert "async" in result.tags
        assert "登録しました" in result.message

    def test_add_knowledge_auto_tags(self, knowledge_tools, project_tools):
        """Test add_knowledge auto-generates tags."""
        project_tools.setup_project(
            project="autotag_proj",
            name="AutoTag Project",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        result = knowledge_tools.add_knowledge(
            content="Use UE_LOG macro for logging in Unreal Engine C++ code",
            category="技術Tips",
            # No tags provided - should auto-generate
        )

        assert result.success is True
        # Should have auto-generated some tags

    def test_add_knowledge_general(self, knowledge_tools):
        """Test add_knowledge for general knowledge (no project)."""
        result = knowledge_tools.add_knowledge(
            content="Always validate user input at system boundaries.",
            category="ベストプラクティス",
            project="",  # Explicitly general
            tags=["security", "validation"],
        )

        assert result.success is True


class TestSearchKnowledge:
    """Tests for search_knowledge method."""

    def test_search_knowledge_empty(self, knowledge_tools):
        """Test search on empty knowledge base."""
        result = knowledge_tools.search_knowledge(query="anything")

        assert result.success is True
        assert result.total_count == 0

    def test_search_knowledge_by_query(self, knowledge_tools, mock_rag_client, project_tools):
        """Test search knowledge by query."""
        project_tools.setup_project(
            project="search_know",
            name="Search Knowledge",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add knowledge entries
        knowledge_tools.add_knowledge(
            content="Use dependency injection for better testability",
            category="ベストプラクティス",
            tags=["testing", "DI"],
        )
        knowledge_tools.add_knowledge(
            content="Avoid circular dependencies in module design",
            category="落とし穴",
            tags=["architecture", "dependencies"],
        )

        result = knowledge_tools.search_knowledge(query="dependency")

        assert result.success is True
        assert result.total_count >= 1

    def test_search_knowledge_by_category(self, knowledge_tools, mock_rag_client, project_tools):
        """Test search knowledge filtered by category."""
        project_tools.setup_project(
            project="cat_know",
            name="Category Knowledge",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        knowledge_tools.add_knowledge(
            content="Database connection timeout issue resolution",
            category="問題解決",
            tags=["database"],
        )
        knowledge_tools.add_knowledge(
            content="Use prepared statements for SQL queries",
            category="技術Tips",
            tags=["database", "security"],
        )

        result = knowledge_tools.search_knowledge(
            query="database",
            category="問題解決",
        )

        assert result.success is True
        for k in result.knowledge:
            assert k.category == "問題解決"

    def test_search_knowledge_by_tags(self, knowledge_tools, mock_rag_client, project_tools):
        """Test search knowledge filtered by tags."""
        project_tools.setup_project(
            project="tag_know",
            name="Tag Knowledge",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        knowledge_tools.add_knowledge(
            content="API rate limiting best practices",
            category="ベストプラクティス",
            tags=["API", "performance"],
        )
        knowledge_tools.add_knowledge(
            content="API authentication methods comparison",
            category="技術Tips",
            tags=["API", "security"],
        )

        result = knowledge_tools.search_knowledge(
            query="API",
            tags=["security"],
        )

        assert result.success is True
        # All results should have "security" tag
        for k in result.knowledge:
            assert "security" in k.tags

    def test_search_knowledge_include_general(self, knowledge_tools, mock_rag_client, project_tools):
        """Test search includes general knowledge."""
        project_tools.setup_project(
            project="gen_know",
            name="General Knowledge",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add general knowledge
        mock_rag_client.add_knowledge(
            content="General best practice for logging",
            category="ベストプラクティス",
            tags=["logging"],
            project="",  # General
        )

        # Add project-specific knowledge
        mock_rag_client.add_knowledge(
            content="Project-specific logging setup",
            category="技術Tips",
            tags=["logging"],
            project="gen_know",
        )

        result = knowledge_tools.search_knowledge(
            query="logging",
            project="gen_know",
            include_general=True,
        )

        assert result.success is True


class TestGetCategories:
    """Tests for get_categories method."""

    def test_get_categories(self, knowledge_tools):
        """Test getting available categories."""
        categories = knowledge_tools.get_categories()

        assert "問題解決" in categories
        assert "技術Tips" in categories
        assert "ベストプラクティス" in categories
        assert "落とし穴" in categories
        assert "設計パターン" in categories
        assert "その他" in categories

    def test_get_categories_returns_copy(self, knowledge_tools):
        """Test get_categories returns a copy."""
        categories1 = knowledge_tools.get_categories()
        categories2 = knowledge_tools.get_categories()

        # Should be equal but not the same object
        assert categories1 == categories2
        assert categories1 is not categories2


class TestDeleteKnowledge:
    """Tests for delete_knowledge method."""

    def test_delete_knowledge_success(self, knowledge_tools, mock_rag_client, project_tools):
        """Test successful knowledge deletion."""
        project_tools.setup_project(
            project="del_know",
            name="Delete Knowledge",
            spreadsheet_id="sheet1",
            root_folder_id="folder1",
            create_sheets=False,
            create_folders=False,
        )

        # Add knowledge
        add_result = knowledge_tools.add_knowledge(
            content="Knowledge to delete",
            category="その他",
        )

        assert add_result.success is True
        knowledge_id = add_result.knowledge_id

        # Delete it
        success = knowledge_tools.delete_knowledge(knowledge_id)

        assert success is True

    def test_delete_knowledge_not_found(self, knowledge_tools):
        """Test delete knowledge that doesn't exist."""
        success = knowledge_tools.delete_knowledge("nonexistent_id")

        # Should return False for non-existent
        assert success is False


class TestGenerateTags:
    """Tests for _generate_tags method."""

    def test_generate_tags_technical_terms(self, knowledge_tools):
        """Test tag generation identifies technical terms."""
        tags = knowledge_tools._generate_tags(
            "Use UE_LOG for logging in Unreal Engine. Apply OAuth2 for authentication."
        )

        # Should identify technical terms
        assert any("UE" in t for t in tags) or any("Unreal" in t for t in tags)

    def test_generate_tags_camelcase(self, knowledge_tools):
        """Test tag generation identifies CamelCase."""
        tags = knowledge_tools._generate_tags(
            "The PlayerController handles input events."
        )

        assert "PlayerController" in tags

    def test_generate_tags_skips_common_words(self, knowledge_tools):
        """Test tag generation skips common words."""
        tags = knowledge_tools._generate_tags(
            "This is a simple test with common words."
        )

        # Common words should not be in tags
        assert "This" not in tags
        assert "is" not in tags
        assert "the" not in tags
        assert "and" not in tags

    def test_generate_tags_limit(self, knowledge_tools):
        """Test tag generation limits number of tags."""
        # Long content with many potential tags
        content = " ".join([f"TechnicalTerm{i}" for i in range(100)])
        tags = knowledge_tools._generate_tags(content)

        assert len(tags) <= 10
