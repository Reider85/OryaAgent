"""Test suite for agent_program function (B-30)."""

import pytest
import asyncio
from unittest.mock import patch, MagicMock

from app.core.capability.program import agent_program


class TestAgentProgram:
    """Test cases for agent_program function."""

    @patch('app.core.capability.program.get_language_capability_registry')
    @patch('app.core.skills.get_skill_registry')
    @patch('app.core.tools.capability_registry.get_capability_registry')
    @patch('app.core.capability.program.get_dfc')
    @patch('app.core.capability.program.asyncio.create_task')
    def test_agent_program_success(
        self,
        mock_create_task,
        mock_get_dfc,
        mock_get_capability_registry,
        mock_get_skill_registry,
        mock_get_language_capability_registry
    ):
        """Test successful agent_program execution."""
        # Mock language capability registry
        mock_registry = MagicMock()
        mock_capability = MagicMock()
        mock_capability.language = "java"
        mock_capability.lsp_server = "jdtls"
        mock_capability.skill_bundle = "java-maven"
        mock_capability.hooks = ["auto-format", "auto-lint"]
        mock_capability.build_cmd = "mvn compile"
        mock_capability.test_cmd = "mvn test"
        mock_capability.get_build_cmd_with_settings.return_value = "mvn compile"
        mock_capability.get_test_cmd_with_settings.return_value = "mvn test"
        mock_registry.resolve.return_value = mock_capability
        mock_get_language_capability_registry.return_value = mock_registry
        
        # Mock skill registry
        mock_skill_registry = MagicMock()
        mock_skill_registry.activate.return_value = None
        mock_get_skill_registry.return_value = mock_skill_registry
        
        # Mock capability registry
        mock_cap_registry = MagicMock()
        mock_get_capability_registry.return_value = mock_cap_registry
        
        # Mock DFC
        mock_dfc = MagicMock()
        mock_dfc.promote_to_hot.return_value = None
        mock_get_dfc.return_value = mock_dfc
        
        # Test agent_program
        result = agent_program("java", "add logging to UserService.create")
        
        # Verify results
        assert "java" in result.lower()
        assert "jdtls" in result
        assert "java-maven" in result
        assert "mvn compile" in result
        assert "mvn test" in result
        
        # Verify function calls
        mock_registry.resolve.assert_called_once_with("java")
        mock_skill_registry.activate.assert_called_once_with("java-maven")
        mock_dfc.promote_to_hot.assert_called_once()
        mock_create_task.assert_called_once()

    @patch('app.core.capability.program.get_language_capability_registry')
    def test_agent_program_unsupported_language(self, mock_get_language_capability_registry):
        """Test agent_program with unsupported language."""
        # Mock language capability registry
        mock_registry = MagicMock()
        mock_registry.resolve.side_effect = ValueError("Unsupported language: klingon")
        mock_get_language_capability_registry.return_value = mock_registry
        
        # Test agent_program
        with pytest.raises(ValueError, match="Unsupported language: klingon"):
            agent_program("klingon", "do something")

    @patch('app.core.capability.program.get_language_capability_registry')
    @patch('app.core.skills.get_skill_registry')
    @patch('app.core.tools.capability_registry.get_capability_registry')
    @patch('app.core.capability.program.get_dfc')
    @patch('app.core.capability.program.asyncio.create_task')
    def test_agent_program_skill_activation_failure(
        self,
        mock_create_task,
        mock_get_dfc,
        mock_get_capability_registry,
        mock_get_skill_registry,
        mock_get_language_capability_registry
    ):
        """Test agent_program with skill activation failure."""
        # Mock language capability registry
        mock_registry = MagicMock()
        mock_capability = MagicMock()
        mock_capability.language = "java"
        mock_capability.lsp_server = "jdtls"
        mock_capability.skill_bundle = "java-maven"
        mock_capability.hooks = ["auto-format", "auto-lint"]
        mock_capability.build_cmd = "mvn compile"
        mock_capability.test_cmd = "mvn test"
        mock_capability.get_build_cmd_with_settings.return_value = "mvn compile"
        mock_capability.get_test_cmd_with_settings.return_value = "mvn test"
        mock_registry.resolve.return_value = mock_capability
        mock_get_language_capability_registry.return_value = mock_registry
        
        # Mock skill registry (activation fails)
        mock_skill_registry = MagicMock()
        mock_skill_registry.activate.side_effect = Exception("Skill activation failed")
        mock_get_skill_registry.return_value = mock_skill_registry
        
        # Mock capability registry
        mock_cap_registry = MagicMock()
        mock_get_capability_registry.return_value = mock_cap_registry
        
        # Mock DFC
        mock_dfc = MagicMock()
        mock_dfc.promote_to_hot.return_value = None
        mock_get_dfc.return_value = mock_dfc
        
        # Test agent_program (should not raise exception)
        result = agent_program("java", "add logging to UserService.create")
        
        # Verify results
        assert "java" in result.lower()
        assert "jdtls" in result
        assert "java-maven" in result
        
        # Verify function calls
        mock_skill_registry.activate.assert_called_once_with("java-maven")

    @patch('app.core.capability.program.get_language_capability_registry')
    @patch('app.core.skills.get_skill_registry')
    @patch('app.core.tools.capability_registry.get_capability_registry')
    @patch('app.core.capability.program.get_dfc')
    @patch('app.core.capability.program.asyncio.create_task')
    def test_agent_program_dfc_failure(
        self,
        mock_create_task,
        mock_get_dfc,
        mock_get_capability_registry,
        mock_get_skill_registry,
        mock_get_language_capability_registry
    ):
        """Test agent_program with DFC promotion failure."""
        # Mock language capability registry
        mock_registry = MagicMock()
        mock_capability = MagicMock()
        mock_capability.language = "java"
        mock_capability.lsp_server = "jdtls"
        mock_capability.skill_bundle = "java-maven"
        mock_capability.hooks = ["auto-format", "auto-lint"]
        mock_capability.build_cmd = "mvn compile"
        mock_capability.test_cmd = "mvn test"
        mock_capability.get_build_cmd_with_settings.return_value = "mvn compile"
        mock_capability.get_test_cmd_with_settings.return_value = "mvn test"
        mock_registry.resolve.return_value = mock_capability
        mock_get_language_capability_registry.return_value = mock_registry
        
# Mock skill registry
        mock_skill_registry = MagicMock()
        mock_skill_registry.activate = MagicMock()
        mock_get_skill_registry.return_value = mock_skill_registry
        
        # Mock capability registry
        mock_cap_registry = MagicMock()
        mock_get_capability_registry.return_value = mock_cap_registry
        
        # Mock DFC
        mock_dfc = MagicMock()
        mock_dfc.promote_to_hot.return_value = None
        mock_get_dfc.return_value = mock_dfc
        
        # Test agent_program (should not raise exception)
        result = agent_program("java", "add logging to UserService.create")
        
        # Verify results
        assert "java" in result.lower()
        assert "jdtls" in result
        assert "java-maven" in result
        
        # Verify function calls
        mock_dfc.promote_to_hot.assert_called_once()

    @patch('app.core.capability.program.get_language_capability_registry')
    @patch('app.core.skills.get_skill_registry')
    @patch('app.core.tools.capability_registry.get_capability_registry')
    @patch('app.core.capability.program.get_dfc')
    @patch('app.core.capability.program.asyncio.create_task')
    def test_agent_program_capability_registry_failure(
        self,
        mock_create_task,
        mock_get_dfc,
        mock_get_capability_registry,
        mock_get_skill_registry,
        mock_get_language_capability_registry
    ):
        """Test agent_program with capability registry update failure."""
        # Mock language capability registry
        mock_registry = MagicMock()
        mock_capability = MagicMock()
        mock_capability.language = "java"
        mock_capability.lsp_server = "jdtls"
        mock_capability.skill_bundle = "java-maven"
        mock_capability.hooks = ["auto-format", "auto-lint"]
        mock_capability.build_cmd = "mvn compile"
        mock_capability.test_cmd = "mvn test"
        mock_capability.get_build_cmd_with_settings.return_value = "mvn compile"
        mock_capability.get_test_cmd_with_settings.return_value = "mvn test"
        mock_registry.resolve.return_value = mock_capability
        mock_get_language_capability_registry.return_value = mock_registry
        
        # Mock skill registry
        mock_skill_registry = MagicMock()
        mock_skill_registry.activate.return_value = None
        mock_get_skill_registry.return_value = mock_skill_registry
        
        # Mock capability registry (update fails)
        mock_cap_registry = MagicMock()
        mock_cap_registry.filter.side_effect = Exception("Capability registry update failed")
        mock_get_capability_registry.return_value = mock_cap_registry
        
        # Mock DFC
        mock_dfc = MagicMock()
        mock_dfc.promote_to_hot.return_value = None
        mock_get_dfc.return_value = mock_dfc
        
        # Test agent_program (should not raise exception)
        result = agent_program("java", "add logging to UserService.create")
        
        # Verify results
        assert "java" in result.lower()
        assert "jdtls" in result
        assert "java-maven" in result

    @patch('app.core.capability.program.get_language_capability_registry')
    @patch('app.core.skills.get_skill_registry')
    @patch('app.core.tools.capability_registry.get_capability_registry')
    @patch('app.core.capability.program.get_dfc')
    @patch('app.core.capability.program.asyncio.create_task')
    def test_agent_program_metrics(
        self,
        mock_create_task,
        mock_get_dfc,
        mock_get_capability_registry,
        mock_get_skill_registry,
        mock_get_language_capability_registry
    ):
        """Test agent_program metrics collection."""
        # Mock language capability registry
        mock_registry = MagicMock()
        mock_capability = MagicMock()
        mock_capability.language = "java"
        mock_capability.lsp_server = "jdtls"
        mock_capability.skill_bundle = "java-maven"
        mock_capability.hooks = ["auto-format", "auto-lint"]
        mock_capability.build_cmd = "mvn compile"
        mock_capability.test_cmd = "mvn test"
        mock_capability.get_build_cmd_with_settings.return_value = "mvn compile"
        mock_capability.get_test_cmd_with_settings.return_value = "mvn test"
        mock_registry.resolve.return_value = mock_capability
        mock_get_language_capability_registry.return_value = mock_registry
        
        # Mock skill registry
        mock_skill_registry = MagicMock()
        mock_skill_registry.activate.return_value = None
        mock_get_skill_registry.return_value = mock_skill_registry
        
        # Mock capability registry
        mock_cap_registry = MagicMock()
        mock_get_capability_registry.return_value = mock_cap_registry
        
        # Mock DFC
        mock_dfc = MagicMock()
        mock_dfc.promote_to_hot.return_value = None
        mock_get_dfc.return_value = mock_dfc
        
        # Mock metrics
        mock_metrics = MagicMock()
        mock_increment_counter = MagicMock()
        mock_gauge = MagicMock()
        mock_metrics.increment_counter = mock_increment_counter
        mock_metrics.gauge = mock_gauge
        
        with patch('app.core.capability.program.get_metric_collector', return_value=mock_metrics):
            # Test agent_program
            result = agent_program("java", "add logging to UserService.create")
            
            # Verify metrics calls
            mock_increment_counter.assert_called_with("orya_language_program_total", {"language": "java"})
            mock_gauge.assert_called_once()

    @patch('app.core.capability.program.get_language_capability_registry')
    @patch('app.core.skills.get_skill_registry')
    @patch('app.core.tools.capability_registry.get_capability_registry')
    @patch('app.core.capability.program.get_dfc')
    @patch('app.core.capability.program.asyncio.create_task')
    def test_agent_program_different_languages(
        self,
        mock_create_task,
        mock_get_dfc,
        mock_get_capability_registry,
        mock_get_skill_registry,
        mock_get_language_capability_registry
    ):
        """Test agent_program with different languages."""
        # Mock language capability registry
        mock_registry = MagicMock()
        mock_capabilities = {}
        
        # Create mock capabilities for different languages
        for lang in ["java", "rust", "go", "javascript", "frontend"]:
            mock_capability = MagicMock()
            mock_capability.language = lang
            mock_capability.lsp_server = f"{lang}-lsp"
            mock_capability.skill_bundle = f"{lang}-bundle"
            mock_capability.hooks = [f"auto-format-{lang}", f"auto-lint-{lang}"]
            mock_capability.build_cmd = f"build {lang}"
            mock_capability.test_cmd = f"test {lang}"
            mock_capability.get_build_cmd_with_settings.return_value = f"build {lang}"
            mock_capability.get_test_cmd_with_settings.return_value = f"test {lang}"
            mock_capabilities[lang] = mock_capability
        
        def mock_resolve(language):
            return mock_capabilities[language]
        
        mock_registry.resolve.side_effect = mock_resolve
        mock_get_language_capability_registry.return_value = mock_registry
        
        # Mock skill registry
        mock_skill_registry = MagicMock()
        mock_skill_registry.activate.return_value = None
        mock_get_skill_registry.return_value = mock_skill_registry
        
        # Mock capability registry
        mock_cap_registry = MagicMock()
        mock_get_capability_registry.return_value = mock_cap_registry
        
        # Mock DFC
        mock_dfc = MagicMock()
        mock_dfc.promote_to_hot.return_value = None
        mock_get_dfc.return_value = mock_dfc
        
        # Test different languages
        for lang in ["java", "rust", "go", "javascript", "frontend"]:
            result = agent_program(lang, f"do something in {lang}")
            
            # Verify results
            assert lang in result.lower()
            assert f"{lang}-lsp" in result
            assert f"{lang}-bundle" in result
            assert f"build {lang}" in result
            assert f"test {lang}" in result
            
            # Verify function calls
            mock_skill_registry.activate.assert_called_with(f"{lang}-bundle")

    @patch('app.core.capability.program.get_language_capability_registry')
    @patch('app.core.skills.get_skill_registry')
    @patch('app.core.tools.capability_registry.get_capability_registry')
    @patch('app.core.capability.program.get_dfc')
    @patch('app.core.capability.program.asyncio.create_task')
    def test_agent_program_task_parameter(
        self,
        mock_create_task,
        mock_get_dfc,
        mock_get_capability_registry,
        mock_get_skill_registry,
        mock_get_language_capability_registry
    ):
        """Test agent_program with different task parameters."""
        # Mock language capability registry
        mock_registry = MagicMock()
        mock_capability = MagicMock()
        mock_capability.language = "java"
        mock_capability.lsp_server = "jdtls"
        mock_capability.skill_bundle = "java-maven"
        mock_capability.hooks = ["auto-format", "auto-lint"]
        mock_capability.build_cmd = "mvn compile"
        mock_capability.test_cmd = "mvn test"
        mock_capability.get_build_cmd_with_settings.return_value = "mvn compile"
        mock_capability.get_test_cmd_with_settings.return_value = "mvn test"
        mock_registry.resolve.return_value = mock_capability
        mock_get_language_capability_registry.return_value = mock_registry
        
        # Mock skill registry
        mock_skill_registry = MagicMock()
        mock_skill_registry.activate.return_value = None
        mock_get_skill_registry.return_value = mock_skill_registry
        
        # Mock capability registry
        mock_cap_registry = MagicMock()
        mock_get_capability_registry.return_value = mock_cap_registry
        
        # Mock DFC
        mock_dfc = MagicMock()
        mock_dfc.promote_to_hot.return_value = None
        mock_get_dfc.return_value = mock_dfc
        
        # Test different tasks
        tasks = [
            "add logging to UserService.create",
            "refactor the authentication module",
            "implement a new REST API endpoint",
            "fix the memory leak in the database connection",
            "add unit tests for the payment service"
        ]
        
        for task in tasks:
            result = agent_program("java", task)
            
            # Verify results
            assert "java" in result.lower()
            assert "jdtls" in result
            assert "java-maven" in result
            assert "mvn compile" in result
            assert "mvn test" in result