"""Tests for LanguageCapabilityLayer components."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

from app.core.language.capability_layer import (
    get_language_capability_layer,
    initialize_language_capability_layer,
    LanguageCapabilityLayer,
    SkillBundle,
    AgentProgram,
    Language,
    TaskType,
)


class TestSkillBundle:
    """Test SkillBundle functionality."""
    
    def test_skill_bundle_creation(self):
        """Test skill bundle creation."""
        bundle = SkillBundle(
            id="python.code_gen",
            name="Python Code Generation",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["code_generation", "template_filling"],
            capabilities=["lsp.hover", "lsp.definition"],
            config={"max_length": 1000},
            priority=1,
            enabled=True,
        )
        
        assert bundle.id == "python.code_gen"
        assert bundle.name == "Python Code Generation"
        assert bundle.language == Language.PYTHON
        assert bundle.task_type == TaskType.CODE_GENERATION
        assert bundle.skills == ["code_generation", "template_filling"]
        assert bundle.capabilities == ["lsp.hover", "lsp.definition"]
        assert bundle.config == {"max_length": 1000}
        assert bundle.priority == 1
        assert bundle.enabled is True
    
    def test_skill_bundle_to_dict(self):
        """Test skill bundle to dictionary conversion."""
        bundle = SkillBundle(
            id="python.code_gen",
            name="Python Code Generation",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["code_generation"],
            capabilities=["lsp.hover"],
            config={"max_length": 1000},
            priority=1,
            enabled=True,
        )
        
        result = bundle.to_dict()
        
        assert result["id"] == "python.code_gen"
        assert result["name"] == "Python Code Generation"
        assert result["language"] == "python"
        assert result["task_type"] == "code_generation"
        assert result["skills"] == ["code_generation"]
        assert result["capabilities"] == ["lsp.hover"]
        assert result["config"] == {"max_length": 1000}
        assert result["priority"] == 1
        assert result["enabled"] is True


class TestAgentProgram:
    """Test AgentProgram functionality."""
    
    def test_agent_program_creation(self):
        """Test agent program creation."""
        skill_bundle = SkillBundle(
            id="python.code_gen",
            name="Python Code Generation",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["code_generation"],
            capabilities=["lsp.hover"],
        )
        
        program = AgentProgram(
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skill_bundles=[skill_bundle],
            capabilities=["lsp.hover", "lsp.definition"],
            config={"max_iterations": 5},
            max_iterations=5,
            timeout=300,
        )
        
        assert program.language == Language.PYTHON
        assert program.task_type == TaskType.CODE_GENERATION
        assert len(program.skill_bundles) == 1
        assert program.skill_bundles[0].id == "python.code_gen"
        assert program.capabilities == ["lsp.hover", "lsp.definition"]
        assert program.config == {"max_iterations": 5}
        assert program.max_iterations == 5
        assert program.timeout == 300
    
    def test_agent_program_to_dict(self):
        """Test agent program to dictionary conversion."""
        skill_bundle = SkillBundle(
            id="python.code_gen",
            name="Python Code Generation",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["code_generation"],
            capabilities=["lsp.hover"],
        )
        
        program = AgentProgram(
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skill_bundles=[skill_bundle],
            capabilities=["lsp.hover"],
        )
        
        result = program.to_dict()
        
        assert result["language"] == "python"
        assert result["task_type"] == "code_generation"
        assert len(result["skill_bundles"]) == 1
        assert result["skill_bundles"][0]["id"] == "python.code_gen"
        assert result["capabilities"] == ["lsp.hover"]
        assert result["max_iterations"] == 10
        assert result["timeout"] == 300


class TestLanguageCapabilityLayer:
    """Test LanguageCapabilityLayer functionality."""
    
    def test_layer_creation(self):
        """Test layer creation."""
        layer = LanguageCapabilityLayer()
        
        assert len(layer.agent_programs) > 0
        assert len(layer.skill_bundles) > 0
        assert layer.capability_registry is not None
        assert layer.retrieval_orchestrator is not None
        
        # Check that built-in skill bundles are loaded
        assert "python.code_generation" in layer.skill_bundles
        assert "python.code_review" in layer.skill_bundles
        assert "python.debugging" in layer.skill_bundles
        assert "python.refactoring" in layer.skill_bundles
        assert "python.testing" in layer.skill_bundles
        assert "typescript.code_generation" in layer.skill_bundles
        assert "typescript.code_review" in layer.skill_bundles
        assert "rust.code_generation" in layer.skill_bundles
        assert "rust.debugging" in layer.skill_bundles
        
        # Check that built-in agent programs are loaded
        assert "python_code_generation" in layer.agent_programs
        assert "python_code_review" in layer.agent_programs
        assert "python_debugging" in layer.agent_programs
        assert "typescript_code_generation" in layer.agent_programs
        assert "typescript_code_review" in layer.agent_programs
        assert "rust_code_generation" in layer.agent_programs
        assert "rust_debugging" in layer.agent_programs
    
    def test_register_skill_bundle(self):
        """Test skill bundle registration."""
        layer = LanguageCapabilityLayer()
        
        bundle = SkillBundle(
            id="new.bundle",
            name="New Bundle",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["new_skill"],
            capabilities=["lsp.hover"],
        )
        
        result = layer.register_skill_bundle(bundle)
        
        assert result is True
        assert "new.bundle" in layer.skill_bundles
        assert layer.skill_bundles["new.bundle"] == bundle
    
    def test_register_duplicate_skill_bundle(self):
        """Test registering duplicate skill bundle."""
        layer = LanguageCapabilityLayer()
        
        bundle = SkillBundle(
            id="python.code_generation",  # Already exists
            name="New Code Generation",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["new_skill"],
            capabilities=["lsp.hover"],
        )
        
        result = layer.register_skill_bundle(bundle)
        
        assert result is True
        # Should update existing bundle
        updated_bundle = layer.get_skill_bundle("python.code_generation")
        assert updated_bundle.name == "New Code Generation"
    
    def test_register_invalid_skill_bundle(self):
        """Test registering invalid skill bundle."""
        layer = LanguageCapabilityLayer()
        
        bundle = None
        
        result = layer.register_skill_bundle(bundle)
        
        assert result is False
    
    def test_unregister_skill_bundle(self):
        """Test skill bundle unregistration."""
        layer = LanguageCapabilityLayer()
        
        result = layer.unregister_skill_bundle("python.code_generation")
        
        assert result is True
        assert "python.code_generation" not in layer.skill_bundles
    
    def test_unregister_nonexistent_skill_bundle(self):
        """Test unregistering non-existent skill bundle."""
        layer = LanguageCapabilityLayer()
        
        result = layer.unregister_skill_bundle("nonexistent.bundle")
        
        assert result is False
    
    def test_get_skill_bundle(self):
        """Test getting skill bundle by ID."""
        layer = LanguageCapabilityLayer()
        
        bundle = layer.get_skill_bundle("python.code_generation")
        
        assert bundle is not None
        assert bundle.id == "python.code_generation"
        assert bundle.name == "Python Code Generation"
    
    def test_get_nonexistent_skill_bundle(self):
        """Test getting non-existent skill bundle."""
        layer = LanguageCapabilityLayer()
        
        bundle = layer.get_skill_bundle("nonexistent.bundle")
        
        assert bundle is None
    
    def test_get_skill_bundles_by_language(self):
        """Test getting skill bundles by language."""
        layer = LanguageCapabilityLayer()
        
        python_bundles = layer.get_skill_bundles(Language.PYTHON)
        
        assert len(python_bundles) > 0
        assert all(bundle.language == Language.PYTHON for bundle in python_bundles)
        
        # Check specific Python bundles
        bundle_ids = [bundle.id for bundle in python_bundles]
        assert "python.code_generation" in bundle_ids
        assert "python.code_review" in bundle_ids
        assert "python.debugging" in bundle_ids
        assert "python.refactoring" in bundle_ids
        assert "python.testing" in bundle_ids
    
    def test_get_skill_bundles_by_language_and_task_type(self):
        """Test getting skill bundles by language and task type."""
        layer = LanguageCapabilityLayer()
        
        python_gen_bundles = layer.get_skill_bundles(
            Language.PYTHON,
            TaskType.CODE_GENERATION
        )
        
        assert len(python_gen_bundles) > 0
        assert all(bundle.language == Language.PYTHON for bundle in python_gen_bundles)
        assert all(bundle.task_type == TaskType.CODE_GENERATION for bundle in python_gen_bundles)
        
        # Check specific Python code generation bundles
        bundle_ids = [bundle.id for bundle in python_gen_bundles]
        assert "python.code_generation" in bundle_ids
    
    def test_register_agent_program(self):
        """Test agent program registration."""
        layer = LanguageCapabilityLayer()
        
        skill_bundle = SkillBundle(
            id="new.bundle",
            name="New Bundle",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["new_skill"],
            capabilities=["lsp.hover"],
        )
        
        program = AgentProgram(
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skill_bundles=[skill_bundle],
            capabilities=["lsp.hover"],
        )
        
        result = layer.register_agent_program(program)
        
        assert result is True
        assert "python_code_generation" in layer.agent_programs
        assert layer.agent_programs["python_code_generation"] == program
    
    def test_get_agent_program(self):
        """Test getting agent program by language and task type."""
        layer = LanguageCapabilityLayer()
        
        program = layer.get_agent_program(Language.PYTHON, TaskType.CODE_GENERATION)
        
        assert program is not None
        assert program.language == Language.PYTHON
        assert program.task_type == TaskType.CODE_GENERATION
    
    def test_get_nonexistent_agent_program(self):
        """Test getting non-existent agent program."""
        layer = LanguageCapabilityLayer()
        
        program = layer.get_agent_program(Language.PYTHON, TaskType.ANALYSIS)
        
        assert program is None
    
    def test_get_available_languages(self):
        """Test getting available languages."""
        layer = LanguageCapabilityLayer()
        
        languages = layer.get_available_languages()
        
        assert len(languages) > 0
        assert Language.PYTHON in languages
        assert Language.TYPESCRIPT in languages
        assert Language.RUST in languages
    
    def test_get_available_task_types(self):
        """Test getting available task types for language."""
        layer = LanguageCapabilityLayer()
        
        python_tasks = layer.get_available_task_types(Language.PYTHON)
        
        assert len(python_tasks) > 0
        assert TaskType.CODE_GENERATION in python_tasks
        assert TaskType.CODE_REVIEW in python_tasks
        assert TaskType.DEBUGGING in python_tasks
        assert TaskType.REFACTORING in python_tasks
        assert TaskType.TESTING in python_tasks
    
    @pytest.mark.asyncio
    async def test_agent_program_success(self):
        """Test successful agent program execution."""
        layer = LanguageCapabilityLayer()
        
        result = await layer.agent_program(
            language=Language.PYTHON,
            task="Generate a Python function to calculate factorial",
            task_type=TaskType.CODE_GENERATION,
            context={"file_type": "py"},
        )
        
        assert result["success"] is True
        assert result["language"] == "python"
        assert result["task_type"] == "code_generation"
        assert "skill_bundle_results" in result
        assert "combined_output" in result
        assert len(result["skill_bundle_results"]) > 0
    
    @pytest.mark.asyncio
    async def test_agent_program_with_config_overrides(self):
        """Test agent program execution with config overrides."""
        layer = LanguageCapabilityLayer()
        
        result = await layer.agent_program(
            language=Language.PYTHON,
            task="Generate a Python function",
            task_type=TaskType.CODE_GENERATION,
            config_overrides={"max_iterations": 3},
        )
        
        assert result["success"] is True
        # Config should be applied (though we can't directly check in mock)
    
    @pytest.mark.asyncio
    async def test_agent_program_no_program_found(self):
        """Test agent program when no program is found."""
        layer = LanguageCapabilityLayer()
        
        result = await layer.agent_program(
            language=Language.PYTHON,
            task="Some task",
            task_type=TaskType.ANALYSIS,  # No program for this task type
        )
        
        assert result["success"] is False
        assert "No agent program found" in result["error"]
    
    @pytest.mark.asyncio
    async def test_agent_program_task_execution_error(self):
        """Test agent program when task execution fails."""
        layer = LanguageCapabilityLayer()
        
        # Mock skill bundle execution to raise error
        with patch.object(layer, '_execute_skill_bundle') as mock_execute:
            mock_execute.side_effect = Exception("Test error")
            
            result = await layer.agent_program(
                language=Language.PYTHON,
                task="Some task",
                task_type=TaskType.CODE_GENERATION,
            )
            
            assert result["success"] is False
            assert "Test error" in result["error"]
    
    @pytest.mark.asyncio
    async def test_execute_task(self):
        """Test task execution."""
        layer = LanguageCapabilityLayer()
        
        skill_bundle = SkillBundle(
            id="test.bundle",
            name="Test Bundle",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["code_generation"],
            capabilities=["lsp.hover"],
        )
        
        agent_program = AgentProgram(
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skill_bundles=[skill_bundle],
            capabilities=["lsp.hover"],
        )
        
        result = await layer._execute_task(
            task="Generate a Python function",
            agent_program=agent_program,
            skill_bundles=[skill_bundle],
            context={"file_type": "py"},
        )
        
        assert result["success"] is True
        assert result["task"] == "Generate a Python function"
        assert result["language"] == "python"
        assert result["task_type"] == "code_generation"
        assert "skill_bundle_results" in result
        assert "combined_output" in result
    
    @pytest.mark.asyncio
    async def test_execute_skill_bundle(self):
        """Test skill bundle execution."""
        layer = LanguageCapabilityLayer()
        
        skill_bundle = SkillBundle(
            id="test.bundle",
            name="Test Bundle",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["code_generation"],
            capabilities=["lsp.hover"],
        )
        
        task_context = {
            "task": "Generate a Python function",
            "language": "python",
            "task_type": "code_generation",
            "context": {"file_type": "py"},
        }
        
        result = await layer._execute_skill_bundle(skill_bundle, task_context)
        
        assert result["success"] is True
        assert result["skill_bundle_id"] == "test.bundle"
        assert result["skill_bundle_name"] == "Test Bundle"
        assert "skills" in result
        assert "retrieved_count" in result
        assert len(result["skills"]) > 0
    
    @pytest.mark.asyncio
    async def test_execute_skill_bundle_disabled(self):
        """Test skill bundle execution when disabled."""
        layer = LanguageCapabilityLayer()
        
        skill_bundle = SkillBundle(
            id="test.bundle",
            name="Test Bundle",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["code_generation"],
            capabilities=["lsp.hover"],
            enabled=False,  # Disabled
        )
        
        task_context = {
            "task": "Generate a Python function",
            "language": "python",
            "task_type": "code_generation",
            "context": {"file_type": "py"},
        }
        
        result = await layer._execute_skill_bundle(skill_bundle, task_context)
        
        # Should not execute disabled bundle
        assert result["skill_bundle_id"] == "test.bundle"
        assert len(result["skills"]) == 0
    
    @pytest.mark.asyncio
    async def test_execute_skill(self):
        """Test skill execution."""
        layer = LanguageCapabilityLayer()
        
        skill_context = {
            "task": "Generate a Python function",
            "language": "python",
            "task_type": "code_generation",
            "context": {"file_type": "py"},
        }
        
        result = await layer._execute_skill("code_generation", skill_context)
        
        assert result["success"] is True
        assert result["skill"] == "code_generation"
        assert "result" in result
        assert "Mock execution of code_generation" in result["result"]
    
    @pytest.mark.asyncio
    async def test_execute_unknown_skill(self):
        """Test execution of unknown skill."""
        layer = LanguageCapabilityLayer()
        
        skill_context = {
            "task": "Some task",
            "language": "python",
            "task_type": "code_generation",
        }
        
        result = await layer._execute_skill("unknown_skill", skill_context)
        
        assert result["success"] is True
        assert result["skill"] == "unknown_skill"
        assert "Mock execution of unknown_skill" in result["result"]
    
    def test_combine_results(self):
        """Test result combination."""
        layer = LanguageCapabilityLayer()
        
        results = [
            {
                "success": True,
                "skills": [
                    {"success": True, "result": "result1"},
                    {"success": True, "result": "result2"},
                ]
            },
            {
                "success": True,
                "skills": [
                    {"success": True, "result": "result3"},
                ]
            },
            {
                "success": False,
                "error": "error",
            }
        ]
        
        combined = layer._combine_results(results)
        
        assert "result1" in combined
        assert "result2" in combined
        assert "result3" in combined
        assert "result1\n\nresult2\n\nresult3" == combined.strip()
    
    def test_get_statistics(self):
        """Test getting layer statistics."""
        layer = LanguageCapabilityLayer()
        
        stats = layer.get_statistics()
        
        assert "total_agent_programs" in stats
        assert "total_skill_bundles" in stats
        assert "languages" in stats
        assert "task_types" in stats
        
        assert stats["total_agent_programs"] > 0
        assert stats["total_skill_bundles"] > 0
        assert len(stats["languages"]) > 0
        assert len(stats["task_types"]) > 0
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test layer health check."""
        layer = LanguageCapabilityLayer()
        
        health = await layer.health_check()
        
        assert health["status"] == "healthy"
        assert "statistics" in health
        assert "agent_programs" in health
        assert "skill_bundles" in health
        assert health["total_agent_programs"] > 0
        assert health["total_skill_bundles"] > 0


class TestGlobalLanguageCapabilityLayer:
    """Test global language capability layer functions."""
    
    def test_get_language_capability_layer(self):
        """Test getting language capability layer instance."""
        layer1 = get_language_capability_layer()
        layer2 = get_language_capability_layer()
        
        assert layer1 is layer2
        assert isinstance(layer1, LanguageCapabilityLayer)
    
    def test_initialize_language_capability_layer(self):
        """Test initializing language capability layer."""
        layer = initialize_language_capability_layer()
        
        assert isinstance(layer, LanguageCapabilityLayer)
        assert len(layer.agent_programs) > 0
        assert len(layer.skill_bundles) > 0
        assert layer.capability_registry is not None
        assert layer.retrieval_orchestrator is not None