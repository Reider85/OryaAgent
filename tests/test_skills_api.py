"""Test suite for the skills API endpoints."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.core.skills import get_skill_registry, Skill


class TestSkillsAPI:
    """Test cases for the skills API endpoints."""

    def setup_method(self):
        """Set up test environment."""
        self.client = TestClient(app)
        self.registry = get_skill_registry()

        # Clear existing skills for testing
        self.registry._skills.clear()

        # Mock the load_skills_from_directory method to prevent loading from YAML files
        self.original_load = self.registry.load_skills_from_directory
        self.registry.load_skills_from_directory = lambda: None

        # Add test skills
        self.test_skill1 = Skill(
            name="test-skill-1",
            config={
                "name": "test-skill-1",
                "description": "Test skill 1",
                "version": "1.0.0",
                "author": "Test Author",
                "category": "development",
                "tags": ["test", "development"],
                "tools": ["read", "write"],
                "hooks": [],
                "dependencies": [],
                "metadata": {},
            },
        )

        self.test_skill2 = Skill(
            name="test-skill-2",
            config={
                "name": "test-skill-2",
                "description": "Test skill 2",
                "version": "2.0.0",
                "author": "Test Author",
                "category": "testing",
                "tags": ["test", "qa"],
                "tools": ["grep", "bash"],
                "hooks": [],
                "dependencies": [],
                "metadata": {},
            },
        )

        self.registry.register_skill(self.test_skill1)
        self.registry.register_skill(self.test_skill2)

        # Set skills as inactive by default for testing
        self.test_skill1._is_active = False
        self.test_skill2._is_active = False

    def teardown_method(self):
        """Clean up test environment."""
        # Restore the original load_skills_from_directory method
        self.registry.load_skills_from_directory = self.original_load

    def test_list_skills(self):
        """Test listing all skills."""
        response = self.client.get("/skills/")
        assert response.status_code == 200

        skills = response.json()
        assert len(skills) == 2

        # Check first skill
        skill1 = skills[0]
        assert skill1["name"] == "test-skill-1"
        assert skill1["description"] == "Test skill 1"
        assert skill1["category"] == "development"
        assert "test" in skill1["tags"]
        assert "development" in skill1["tags"]
        assert "read" in skill1["tools"]
        assert "write" in skill1["tools"]

    def test_list_skills_by_category(self):
        """Test listing skills by category."""
        response = self.client.get("/skills/?category=development")
        assert response.status_code == 200

        skills = response.json()
        assert len(skills) == 1
        assert skills[0]["category"] == "development"

    def test_list_skills_by_tag(self):
        """Test listing skills by tag."""
        response = self.client.get("/skills/?tag=test")
        assert response.status_code == 200

        skills = response.json()
        assert len(skills) == 2  # Both skills have the "test" tag

    def test_list_active_skills_only(self):
        """Test listing only active skills."""
        # Activate one skill
        self.registry.activate_skill("test-skill-1")

        response = self.client.get("/skills/?active_only=true")
        assert response.status_code == 200

        skills = response.json()
        assert len(skills) == 1
        assert skills[0]["name"] == "test-skill-1"

    def test_get_skill_by_name(self):
        """Test getting a specific skill by name."""
        response = self.client.get("/skills/test-skill-1")
        assert response.status_code == 200

        skill = response.json()
        assert skill["name"] == "test-skill-1"
        assert skill["description"] == "Test skill 1"

    def test_get_nonexistent_skill(self):
        """Test getting a non-existent skill."""
        response = self.client.get("/skills/nonexistent-skill")
        assert response.status_code == 404

    def test_activate_skill(self):
        """Test activating a skill."""
        response = self.client.post(
            "/skills/activate", json={"skill_name": "test-skill-1", "activate": True}
        )
        assert response.status_code == 200

        result = response.json()
        assert result["message"] == "Skill 'test-skill-1' activated"
        assert result["skill_name"] == "test-skill-1"

        # Verify skill is active
        skill = self.registry.get_skill("test-skill-1")
        assert skill.is_active

    def test_deactivate_skill(self):
        """Test deactivating a skill."""
        # First activate the skill
        self.registry.activate_skill("test-skill-1")

        response = self.client.post(
            "/skills/activate", json={"skill_name": "test-skill-1", "activate": False}
        )
        assert response.status_code == 200

        result = response.json()
        assert result["message"] == "Skill 'test-skill-1' deactivated"
        assert result["skill_name"] == "test-skill-1"

        # Verify skill is inactive
        skill = self.registry.get_skill("test-skill-1")
        assert not skill.is_active

    def test_activate_nonexistent_skill(self):
        """Test activating a non-existent skill."""
        response = self.client.post(
            "/skills/activate",
            json={"skill_name": "nonexistent-skill", "activate": True},
        )
        assert response.status_code == 400

    def test_list_categories(self):
        """Test listing skill categories."""
        response = self.client.get("/skills/categories")
        assert response.status_code == 200

        categories = response.json()
        assert "development" in categories
        assert "testing" in categories

    def test_list_tags(self):
        """Test listing skill tags."""
        response = self.client.get("/skills/tags")
        assert response.status_code == 200

        tags = response.json()
        assert "test" in tags
        assert "development" in tags
        assert "qa" in tags

    def test_search_skills(self):
        """Test searching skills."""
        response = self.client.get("/skills/search?query=test")
        assert response.status_code == 200

        skills = response.json()
        assert len(skills) == 2  # Both skills have "test" in their data

        response = self.client.get("/skills/search?query=development")
        assert response.status_code == 200

        skills = response.json()
        assert len(skills) == 1  # Only skill1 has "development" in its data

    def test_validate_skill(self):
        """Test validating a skill."""
        response = self.client.get("/skills/validate/test-skill-1")
        assert response.status_code == 200

        result = response.json()
        assert result["skill_name"] == "test-skill-1"
        assert result["is_valid"] is True

    def test_validate_nonexistent_skill(self):
        """Test validating a non-existent skill."""
        response = self.client.get("/skills/validate/nonexistent-skill")
        assert response.status_code == 404

    def test_search_with_category_filter(self):
        """Test searching with category filter."""
        response = self.client.get("/skills/search?query=test&category=development")
        assert response.status_code == 200

        skills = response.json()
        assert len(skills) == 1  # Only skill1 matches both search and category

    def test_search_with_tag_filter(self):
        """Test searching with tag filter."""
        response = self.client.get("/skills/search?query=test&tag=development")
        assert response.status_code == 200

        skills = response.json()
        assert len(skills) == 1  # Only skill1 matches both search and tag
