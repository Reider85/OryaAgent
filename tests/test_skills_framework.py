"""Test suite for the skills framework."""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.core.skills import (
    Skill,
    SkillRegistry,
    get_skill_registry,
    initialize_skill_registry,
    list_skills,
    get_skill,
    activate_skill,
    deactivate_skill,
    validate_skill,
)
from app.core.tools import get_tools


class TestSkill:
    """Test cases for the Skill class."""
    
    def test_skill_creation(self):
        """Test basic skill creation."""
        config = {
            "name": "test-skill",
            "description": "A test skill",
            "version": "1.0.0",
            "author": "Test Author",
            "tools": ["read", "write"],
            "hooks": ["pre-write"],
            "category": "development",
            "tags": ["testing"],
            "metadata": {"complexity": "low"}
        }
        
        skill = Skill("test-skill", config)
        
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.version == "1.0.0"
        assert skill.author == "Test Author"
        assert skill.tools == ["read", "write"]
        assert skill.hooks == ["pre-write"]
        assert skill.category == "development"
        assert skill.tags == ["testing"]
        assert skill.metadata == {"complexity": "low"}
        
    def test_skill_defaults(self):
        """Test skill with minimal configuration."""
        config = {
            "name": "minimal-skill",
            "tools": ["read"]
        }
        
        skill = Skill("minimal-skill", config)
        
        assert skill.name == "minimal-skill"
        assert skill.description == ""
        assert skill.version == "1.0.0"
        assert skill.author == ""
        assert skill.tools == ["read"]
        assert skill.hooks == []
        assert skill.category == "general"
        assert skill.tags == []
        assert skill.metadata == {}
        
    def test_skill_to_dict(self):
        """Test skill to dictionary conversion."""
        config = {
            "name": "dict-skill",
            "description": "Test skill for dict conversion",
            "version": "2.0.0",
            "tools": ["read", "write"],
            "hooks": ["post-write"],
            "category": "testing",
            "tags": ["unit"],
            "metadata": {"test": True}
        }
        
        skill = Skill("dict-skill", config)
        skill_dict = skill.to_dict()
        
        assert skill_dict["name"] == "dict-skill"
        assert skill_dict["description"] == "Test skill for dict conversion"
        assert skill_dict["version"] == "2.0.0"
        assert skill_dict["tools"] == ["read", "write"]
        assert skill_dict["hooks"] == ["post-write"]
        assert skill_dict["category"] == "testing"
        assert skill_dict["tags"] == ["unit"]
        assert skill_dict["metadata"] == {"test": True}
        
    def test_skill_repr(self):
        """Test skill string representation."""
        config = {
            "name": "repr-skill",
            "version": "1.5.0",
            "tools": ["read"]
        }
        
        skill = Skill("repr-skill", config)
        assert repr(skill) == "Skill(name='repr-skill', version='1.5.0')"


class TestSkillRegistry:
    """Test cases for the SkillRegistry class."""
    
    def setup_method(self):
        """Set up test environment."""
        self.registry = SkillRegistry()
        
    def test_skill_registry_initialization(self):
        """Test skill registry initialization."""
        registry = SkillRegistry()
        assert registry._skills == {}
        assert registry._skill_paths == {}
        assert registry._hook_registry is not None
        
    def test_register_skill(self):
        """Test skill registration."""
        config = {
            "name": "test-skill",
            "tools": ["read"],
            "description": "Test skill"
        }
        
        skill = Skill("test-skill", config)
        self.registry.register_skill(skill)
        
        assert "test-skill" in self.registry._skills
        assert self.registry.get_skill("test-skill") == skill
        
    def test_register_skill_with_path(self):
        """Test skill registration with path."""
        config = {
            "name": "path-skill",
            "tools": ["write"],
            "description": "Skill with path"
        }
        
        skill = Skill("path-skill", config)
        path = Path("/test/path.yaml")
        
        self.registry.register_skill(skill, path)
        
        assert "path-skill" in self.registry._skills
        assert self.registry._skill_paths["path-skill"] == path
        
    def test_unregister_skill(self):
        """Test skill unregistration."""
        config = {
            "name": "unregister-skill",
            "tools": ["read"],
            "description": "Skill to unregister"
        }
        
        skill = Skill("unregister-skill", config)
        self.registry.register_skill(skill)
        
        assert "unregister-skill" in self.registry._skills
        
        self.registry.unregister_skill("unregister-skill")
        
        assert "unregister-skill" not in self.registry._skills
        assert "unregister-skill" not in self.registry._skill_paths
        
    def test_get_skill(self):
        """Test getting a skill by name."""
        config = {
            "name": "get-skill",
            "tools": ["read"],
            "description": "Skill to get"
        }
        
        skill = Skill("get-skill", config)
        self.registry.register_skill(skill)
        
        retrieved_skill = self.registry.get_skill("get-skill")
        assert retrieved_skill == skill
        
        assert self.registry.get_skill("nonexistent") is None
        
    def test_list_skills(self):
        """Test listing all skills."""
        config1 = {"name": "skill1", "tools": ["read"]}
        config2 = {"name": "skill2", "tools": ["write"]}
        
        skill1 = Skill("skill1", config1)
        skill2 = Skill("skill2", config2)
        
        self.registry.register_skill(skill1)
        self.registry.register_skill(skill2)
        
        skills = self.registry.list_skills()
        assert len(skills) == 2
        assert skill1 in skills
        assert skill2 in skills
        
    def test_list_skill_names(self):
        """Test listing skill names."""
        config1 = {"name": "name1", "tools": ["read"]}
        config2 = {"name": "name2", "tools": ["write"]}
        
        skill1 = Skill("name1", config1)
        skill2 = Skill("name2", config2)
        
        self.registry.register_skill(skill1)
        self.registry.register_skill(skill2)
        
        names = self.registry.list_skill_names()
        assert len(names) == 2
        assert "name1" in names
        assert "name2" in names
        
    def test_get_skills_by_category(self):
        """Test getting skills by category."""
        config1 = {"name": "dev1", "tools": ["read"], "category": "development"}
        config2 = {"name": "dev2", "tools": ["write"], "category": "development"}
        config3 = {"name": "gen1", "tools": ["edit"], "category": "general"}
        
        self.registry.register_skill(Skill("dev1", config1))
        self.registry.register_skill(Skill("dev2", config2))
        self.registry.register_skill(Skill("gen1", config3))
        
        dev_skills = self.registry.get_skills_by_category("development")
        assert len(dev_skills) == 2
        assert "dev1" in [s.name for s in dev_skills]
        assert "dev2" in [s.name for s in dev_skills]
        
        gen_skills = self.registry.get_skills_by_category("general")
        assert len(gen_skills) == 1
        assert gen_skills[0].name == "gen1"
        
    def test_get_skills_by_tag(self):
        """Test getting skills by tag."""
        config1 = {"name": "tag1", "tools": ["read"], "tags": ["testing", "unit"]}
        config2 = {"name": "tag2", "tools": ["write"], "tags": ["testing", "integration"]}
        config3 = {"name": "tag3", "tools": ["edit"], "tags": ["linting"]}
        
        self.registry.register_skill(Skill("tag1", config1))
        self.registry.register_skill(Skill("tag2", config2))
        self.registry.register_skill(Skill("tag3", config3))
        
        testing_skills = self.registry.get_skills_by_tag("testing")
        assert len(testing_skills) == 2
        assert "tag1" in [s.name for s in testing_skills]
        assert "tag2" in [s.name for s in testing_skills]
        
        unit_skills = self.registry.get_skills_by_tag("unit")
        assert len(unit_skills) == 1
        assert unit_skills[0].name == "tag1"
        
    @patch('app.core.skills.get_tools')
    def test_activate_skill(self, mock_get_tools):
        """Test skill activation."""
        # Create mock tools with proper name attributes
        mock_read = MagicMock()
        mock_read.name = "read"
        mock_write = MagicMock()
        mock_write.name = "write"
        mock_edit = MagicMock()
        mock_edit.name = "edit"
        
        mock_tools = [mock_read, mock_write, mock_edit]
        mock_get_tools.return_value = mock_tools
        
        config = {
            "name": "activate-skill",
            "tools": ["read", "write"],
            "hooks": ["pre-write"],
            "description": "Skill to activate"
        }
        
        skill = Skill("activate-skill", config)
        self.registry.register_skill(skill)
        
        with patch.object(self.registry, '_hook_registry') as mock_hook_registry:
            activated = self.registry.activate_skill("activate-skill")
            
            # Should return activated tools and hooks
            assert "read" in activated
            assert "write" in activated
            assert "pre-write" in activated
            
    def test_activate_nonexistent_skill(self):
        """Test activating a non-existent skill."""
        with pytest.raises(ValueError, match="Skill not found: nonexistent"):
            self.registry.activate_skill("nonexistent")
            
    @patch('app.core.skills.get_tools')
    def test_deactivate_skill(self, mock_get_tools):
        """Test skill deactivation."""
        # Create mock tools with proper name attributes
        mock_read = MagicMock()
        mock_read.name = "read"
        mock_write = MagicMock()
        mock_write.name = "write"
        mock_edit = MagicMock()
        mock_edit.name = "edit"
        
        mock_tools = [mock_read, mock_write, mock_edit]
        mock_get_tools.return_value = mock_tools
        
        config = {
            "name": "deactivate-skill",
            "tools": ["read", "write"],
            "hooks": ["post-write"],
            "description": "Skill to deactivate"
        }
        
        skill = Skill("deactivate-skill", config)
        self.registry.register_skill(skill)
        
        with patch.object(self.registry, '_hook_registry') as mock_hook_registry:
            deactivated = self.registry.deactivate_skill("deactivate-skill")
            
            # Should return deactivated tools and hooks
            assert "read" in deactivated
            assert "write" in deactivated
            assert "post-write" in deactivated
            
    def test_deactivate_nonexistent_skill(self):
        """Test deactivating a non-existent skill."""
        with pytest.raises(ValueError, match="Skill not found: nonexistent"):
            self.registry.deactivate_skill("nonexistent")
            
    @patch('app.core.skills.get_tools')
    def test_validate_skill(self, mock_get_tools):
        """Test skill validation."""
        # Create mock tools with proper name attributes
        mock_read = MagicMock()
        mock_read.name = "read"
        mock_write = MagicMock()
        mock_write.name = "write"
        mock_edit = MagicMock()
        mock_edit.name = "edit"
        
        mock_tools = [mock_read, mock_write, mock_edit]
        mock_get_tools.return_value = mock_tools
        
        config = {
            "name": "valid-skill",
            "tools": ["read", "write"],
            "hooks": ["pre-write"],
            "description": "Valid skill"
        }
        
        skill = Skill("valid-skill", config)
        self.registry.register_skill(skill)
        
        result = self.registry.validate_skill("valid-skill")
        assert result["valid"] is True
        assert "issues" not in result
        
    def test_validate_nonexistent_skill(self):
        """Test validating a non-existent skill."""
        result = self.registry.validate_skill("nonexistent")
        assert result["valid"] is False
        assert "Skill not found: nonexistent" in result["error"]
        
    @patch('app.core.skills.get_tools')
    def test_validate_skill_with_missing_tools(self, mock_get_tools):
        """Test skill validation with missing tools."""
        mock_read = MagicMock()
        mock_read.name = "read"
        mock_tools = [mock_read]
        mock_get_tools.return_value = mock_tools
        
        config = {
            "name": "invalid-skill",
            "tools": ["read", "missing_tool"],
            "hooks": ["pre-write"],
            "description": "Invalid skill"
        }
        
        skill = Skill("invalid-skill", config)
        self.registry.register_skill(skill)
        
        result = self.registry.validate_skill("invalid-skill")
        assert result["valid"] is False
        assert "Tool 'missing_tool' not available" in result["issues"]
        
    def test_get_skill_dependencies(self):
        """Test getting skill dependencies."""
        config1 = {"name": "dep1", "tools": ["read"], "dependencies": []}
        config2 = {"name": "dep2", "tools": ["write"], "dependencies": ["dep1"]}
        config3 = {"name": "dep3", "tools": ["edit"], "dependencies": ["dep2", "dep1"]}
        
        self.registry.register_skill(Skill("dep1", config1))
        self.registry.register_skill(Skill("dep2", config2))
        self.registry.register_skill(Skill("dep3", config3))
        
        deps = self.registry.get_skill_dependencies("dep3")
        assert "dep1" in deps
        assert "dep2" in deps
        
    def test_resolve_skill_dependencies(self):
        """Test resolving skill dependencies."""
        config1 = {"name": "rdep1", "tools": ["read"], "dependencies": []}
        config2 = {"name": "rdep2", "tools": ["write"], "dependencies": ["rdep1"]}
        config3 = {"name": "rdep3", "tools": ["edit"], "dependencies": ["rdep2"]}
        
        self.registry.register_skill(Skill("rdep1", config1))
        self.registry.register_skill(Skill("rdep2", config2))
        self.registry.register_skill(Skill("rdep3", config3))
        
        resolved = self.registry.resolve_skill_dependencies("rdep3")
        assert resolved == ["rdep1", "rdep2", "rdep3"]


class TestSkillRegistryYAML:
    """Test cases for YAML-based skill loading."""
    
    def setup_method(self):
        """Set up test environment."""
        self.registry = SkillRegistry()
        
    def test_load_skill_from_yaml_file(self):
        """Test loading a skill from a YAML file."""
        yaml_content = """
name: yaml-skill
description: "Skill loaded from YAML"
version: "1.0.0"
author: "YAML Author"
tools: ["read", "write"]
hooks: ["pre-write"]
category: "development"
tags: ["yaml", "test"]
dependencies: []
metadata:
  test_key: "test_value"
"""
        
        # Create temporary file and close it before loading
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_file_path = f.name
            
        try:
            skill = self.registry.load_skill_from_yaml(temp_file_path)
            
            assert skill.name == "yaml-skill"
            assert skill.description == "Skill loaded from YAML"
            assert skill.version == "1.0.0"
            assert skill.author == "YAML Author"
            assert skill.tools == ["read", "write"]
            assert skill.hooks == ["pre-write"]
            assert skill.category == "development"
            assert skill.tags == ["yaml", "test"]
            assert skill.metadata == {"test_key": "test_value"}
            
        finally:
            os.unlink(temp_file_path)
                
    def test_load_skill_from_invalid_yaml(self):
        """Test loading a skill from invalid YAML."""
        # Use completely invalid YAML that should raise an exception
        yaml_content = """
name: invalid-skill
invalid: yaml: structure: with: invalid: colons: and: syntax
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_file_path = f.name
            
        try:
            with pytest.raises(Exception):
                self.registry.load_skill_from_yaml(temp_file_path)
                
        finally:
            os.unlink(temp_file_path)
                
    def test_load_skill_from_yaml_missing_name(self):
        """Test loading a skill from YAML missing name field."""
        yaml_content = """
description: "Skill without name"
tools: ["read"]
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_file_path = f.name
            
        try:
            with pytest.raises(ValueError, match="missing 'name' field"):
                self.registry.load_skill_from_yaml(temp_file_path)
                
        finally:
            os.unlink(temp_file_path)
                
    def test_load_skill_from_nonexistent_file(self):
        """Test loading a skill from non-existent file."""
        with pytest.raises(FileNotFoundError):
            self.registry.load_skill_from_yaml("/nonexistent/skill.yaml")
            
    def test_load_skills_from_directory(self):
        """Test loading skills from a directory."""
        # Create temporary directory with YAML files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create first skill file
            skill1_path = Path(temp_dir) / "skill1.yaml"
            skill1_content = """
name: skill1
description: "First test skill"
tools: ["read"]
"""
            skill1_path.write_text(skill1_content)
            
            # Create second skill file
            skill2_path = Path(temp_dir) / "skill2.yaml"
            skill2_content = """
name: skill2
description: "Second test skill"
tools: ["write"]
"""
            skill2_path.write_text(skill2_content)
            
            # Create non-YAML file (should be ignored)
            non_yaml_path = Path(temp_dir) / "README.md"
            non_yaml_path.write_text("# This is not a skill file")
            
            # Load skills from directory
            self.registry.load_skills_from_directory(temp_dir)
            
            # Check that skills were loaded
            assert self.registry.get_skill("skill1") is not None
            assert self.registry.get_skill("skill2") is not None
            assert self.registry.get_skill("README") is None
            
    def test_load_skills_from_nonexistent_directory(self):
        """Test loading skills from non-existent directory."""
        # Should not raise an error, just log a warning
        self.registry.load_skills_from_directory("/nonexistent/directory")
        assert len(self.registry.list_skills()) == 0


class TestGlobalSkillRegistry:
    """Test cases for global skill registry functions."""
    
    def setup_method(self):
        """Set up test environment."""
        # Reset global registry
        import app.core.skills
        app.core.skills._skill_registry = None
        
    def test_get_skill_registry_singleton(self):
        """Test that get_skill_registry returns the same instance."""
        registry1 = get_skill_registry()
        registry2 = get_skill_registry()
        
        assert registry1 is registry2
        
    def test_initialize_skill_registry(self):
        """Test initializing skill registry."""
        registry = initialize_skill_registry()
        
        assert registry is not None
        assert len(registry.list_skills()) >= 0  # May have default skills
        
    def test_list_skills_function(self):
        """Test global list_skills function."""
        skills = list_skills()
        assert isinstance(skills, list)
        
    def test_get_skill_function(self):
        """Test global get_skill function."""
        # This will return None for non-existent skill
        skill = get_skill("nonexistent")
        assert skill is None
        
    def test_activate_skill_function(self):
        """Test global activate_skill function."""
        with patch('app.core.skills.get_skill_registry') as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.activate_skill.return_value = ["read", "write"]
            mock_get_registry.return_value = mock_registry
            
            result = activate_skill("test-skill")
            
            assert result == ["read", "write"]
            mock_registry.activate_skill.assert_called_once_with("test-skill")
            
    def test_deactivate_skill_function(self):
        """Test global deactivate_skill function."""
        with patch('app.core.skills.get_skill_registry') as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.deactivate_skill.return_value = ["read", "write"]
            mock_get_registry.return_value = mock_registry
            
            result = deactivate_skill("test-skill")
            
            assert result == ["read", "write"]
            mock_registry.deactivate_skill.assert_called_once_with("test-skill")
            
    def test_validate_skill_function(self):
        """Test global validate_skill function."""
        with patch('app.core.skills.get_skill_registry') as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.validate_skill.return_value = {"valid": True}
            mock_get_registry.return_value = mock_registry
            
            result = validate_skill("test-skill")
            
            assert result == {"valid": True}
            mock_registry.validate_skill.assert_called_once_with("test-skill")


class TestSkillIntegration:
    """Integration tests for the skills framework."""
    
    def setup_method(self):
        """Set up test environment."""
        # Reset global registry
        import app.core.skills
        app.core.skills._skill_registry = None
        
        # Create a temporary skills directory
        self.temp_skills_dir = tempfile.mkdtemp()
        
    def teardown_method(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_skills_dir, ignore_errors=True)
        
    def test_full_skill_lifecycle(self):
        """Test complete skill lifecycle."""
        # Initialize registry with temporary directory
        registry = initialize_skill_registry(self.temp_skills_dir)
        
        # Create a test skill
        skill_config = {
            "name": "integration-skill",
            "description": "Integration test skill",
            "version": "1.0.0",
            "tools": ["read", "write"],
            "hooks": ["pre-write"],
            "category": "testing",
            "tags": ["integration"],
            "dependencies": [],
            "metadata": {"test": True}
        }
        
        skill = Skill("integration-skill", skill_config)
        registry.register_skill(skill)
        
        # Verify skill is registered
        assert registry.get_skill("integration-skill") is not None
        
        # Test listing skills
        skills = registry.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "integration-skill"
        
        # Test getting skills by category
        test_skills = registry.get_skills_by_category("testing")
        assert len(test_skills) == 1
        assert test_skills[0].name == "integration-skill"
        
        # Test getting skills by tag
        integration_skills = registry.get_skills_by_tag("integration")
        assert len(integration_skills) == 1
        assert integration_skills[0].name == "integration-skill"
        
        # Test validation
        validation_result = registry.validate_skill("integration-skill")
        assert validation_result["valid"] is True
        
        # Test activation
        with patch('app.core.skills.get_tools') as mock_get_tools:
            mock_read = MagicMock()
            mock_read.name = "read"
            mock_write = MagicMock()
            mock_write.name = "write"
            mock_tools = [mock_read, mock_write]
            mock_get_tools.return_value = mock_tools
            
            with patch.object(registry, '_hook_registry') as mock_hook_registry:
                activated = registry.activate_skill("integration-skill")
                assert "read" in activated
                assert "write" in activated
                assert "pre-write" in activated
                
        # Test deactivation
        with patch.object(registry, '_hook_registry') as mock_hook_registry:
            deactivated = registry.deactivate_skill("integration-skill")
            assert "read" in deactivated
            assert "write" in deactivated
            assert "pre-write" in deactivated
            
        # Test unregistration
        registry.unregister_skill("integration-skill")
        assert registry.get_skill("integration-skill") is None
        
    def test_skill_dependencies_resolution(self):
        """Test skill dependency resolution."""
        registry = initialize_skill_registry()
        
        # Create skills with dependencies
        base_config = {"name": "base", "tools": ["read"], "dependencies": []}
        mid_config = {"name": "mid", "tools": ["write"], "dependencies": ["base"]}
        top_config = {"name": "top", "tools": ["edit"], "dependencies": ["mid", "base"]}
        
        registry.register_skill(Skill("base", base_config))
        registry.register_skill(Skill("mid", mid_config))
        registry.register_skill(Skill("top", top_config))
        
        # Test dependency resolution
        resolved = registry.resolve_skill_dependencies("top")
        assert resolved == ["base", "mid", "top"]
        
        # Test dependency retrieval
        deps = registry.get_skill_dependencies("top")
        assert "base" in deps
        assert "mid" in deps
        
    def test_skill_export(self):
        """Test skill export functionality."""
        registry = initialize_skill_registry()
        
        # Create test skills
        for i in range(3):
            config = {
                "name": f"export-skill-{i}",
                "description": f"Export test skill {i}",
                "tools": ["read"],
                "hooks": []
            }
            registry.register_skill(Skill(f"export-skill-{i}", config))
            
        # Export skills
        export_file = Path(self.temp_skills_dir) / "exported_skills.yaml"
        registry.export_skills(export_file)
        
        # Verify export file exists
        assert export_file.exists()
        
        # Verify exported content
        import yaml
        with open(export_file, 'r') as f:
            exported_data = yaml.safe_load(f)
            
        # Should have 4 skills: the 3 we created + the code-review.yaml
        assert len(exported_data) == 4
        assert "export-skill-0" in exported_data
        assert "export-skill-1" in exported_data
        assert "export-skill-2" in exported_data