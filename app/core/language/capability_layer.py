"""Per-language capability layer with agent_program and skill-bundles."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union, Callable
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path

from app.core.observability.spans import emit_span
from app.core.capability.registry import get_capability_registry, Capability, CapabilityType
from app.core.retrieval.orchestrator import get_retrieval_orchestrator

logger = logging.getLogger(__name__)


class Language(Enum):
    """Supported programming languages."""
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    RUST = "rust"
    GO = "go"
    JAVA = "java"
    LUA = "lua"
    CPP = "cpp"
    C = "c"
    CS = "csharp"
    PHP = "php"
    RUBY = "ruby"
    SWIFT = "swift"
    KOTLIN = "kotlin"
    SCALA = "scala"
    R = "r"
    JULIA = "julia"
    DART = "dart"
    ELIXIR = "elixir"
    HASKELL = "haskell"


class TaskType(Enum):
    """Types of tasks that can be performed."""
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    OPTIMIZATION = "optimization"
    MIGRATION = "migration"
    ANALYSIS = "analysis"
    INTEGRATION = "integration"


@dataclass
class SkillBundle:
    """Represents a bundle of skills for a specific language and task type."""
    id: str
    name: str
    language: Language
    task_type: TaskType
    skills: List[str]
    capabilities: List[str]
    config: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "language": self.language.value,
            "task_type": self.task_type.value,
            "skills": self.skills,
            "capabilities": self.capabilities,
            "config": self.config,
            "priority": self.priority,
            "enabled": self.enabled,
        }


@dataclass
class AgentProgram:
    """Represents an agent program for a specific language."""
    language: Language
    task_type: TaskType
    skill_bundles: List[SkillBundle]
    capabilities: List[str]
    config: Dict[str, Any] = field(default_factory=dict)
    max_iterations: int = 10
    timeout: int = 300
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "language": self.language.value,
            "task_type": self.task_type.value,
            "skill_bundles": [sb.to_dict() for sb in self.skill_bundles],
            "capabilities": self.capabilities,
            "config": self.config,
            "max_iterations": self.max_iterations,
            "timeout": self.timeout,
        }


class LanguageCapabilityLayer:
    """Per-language capability layer with agent_program and skill-bundles."""
    
    def __init__(self):
        self.agent_programs: Dict[str, AgentProgram] = {}
        self.skill_bundles: Dict[str, SkillBundle] = {}
        
        # Initialize capability registry
        self.capability_registry = get_capability_registry()
        
        # Initialize retrieval orchestrator
        self.retrieval_orchestrator = get_retrieval_orchestrator()
        
        # Load built-in skill bundles
        self._load_built_in_skill_bundles()
        
        # Load built-in agent programs
        self._load_built_in_agent_programs()
    
    def _load_built_in_skill_bundles(self) -> None:
        """Load built-in skill bundles."""
        # Python skill bundles
        self.register_skill_bundle(SkillBundle(
            id="python.code_generation",
            name="Python Code Generation",
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skills=["code_generation", "template_filling"],
            capabilities=["lsp.hover", "lsp.definition", "memory.semantic"],
            config={
                "max_code_length": 1000,
                "use_templates": True,
                "style_guide": "pep8",
            },
            priority=1,
        ))
        
        self.register_skill_bundle(SkillBundle(
            id="python.code_review",
            name="Python Code Review",
            language=Language.PYTHON,
            task_type=TaskType.CODE_REVIEW,
            skills=["code_analysis", "pattern_matching", "best_practice_check"],
            capabilities=["lsp.diagnostics", "memory.semantic", "memory.lexical"],
            config={
                "focus_areas": ["security", "performance", "readability"],
                "strictness": "medium",
            },
            priority=1,
        ))
        
        self.register_skill_bundle(SkillBundle(
            id="python.debugging",
            name="Python Debugging",
            language=Language.PYTHON,
            task_type=TaskType.DEBUGGING,
            skills=["error_analysis", "stack_trace_analysis", "variable_inspection"],
            capabilities=["lsp.diagnostics", "lsp.definition", "memory.semantic"],
            config={
                "max_stack_depth": 10,
                "show_locals": True,
            },
            priority=2,
        ))
        
        self.register_skill_bundle(SkillBundle(
            id="python.refactoring",
            name="Python Refactoring",
            language=Language.PYTHON,
            task_type=TaskType.REFACTORING,
            skills=["pattern_recognition", "code_smell_detection", "transformation"],
            capabilities=["lsp.codeAction", "lsp.definition", "memory.semantic"],
            config={
                "refactoring_types": ["extract_method", "rename", "inline"],
                "preserve_functionality": True,
            },
            priority=1,
        ))
        
        self.register_skill_bundle(SkillBundle(
            id="python.testing",
            name="Python Testing",
            language=Language.PYTHON,
            task_type=TaskType.TESTING,
            skills=["test_generation", "test_analysis", "coverage_analysis"],
            capabilities=["lsp.diagnostics", "memory.semantic", "workflow.test"],
            config={
                "test_framework": "pytest",
                "min_coverage": 80,
            },
            priority=1,
        ))
        
        # TypeScript skill bundles
        self.register_skill_bundle(SkillBundle(
            id="typescript.code_generation",
            name="TypeScript Code Generation",
            language=Language.TYPESCRIPT,
            task_type=TaskType.CODE_GENERATION,
            skills=["code_generation", "type_inference", "interface_generation"],
            capabilities=["lsp.hover", "lsp.definition", "memory.semantic"],
            config={
                "strict_mode": True,
                "use_interfaces": True,
            },
            priority=1,
        ))
        
        self.register_skill_bundle(SkillBundle(
            id="typescript.code_review",
            name="TypeScript Code Review",
            language=Language.TYPESCRIPT,
            task_type=TaskType.CODE_REVIEW,
            skills=["typescript_analysis", "type_safety_check", "react_best_practices"],
            capabilities=["lsp.diagnostics", "memory.semantic", "memory.lexical"],
            config={
                "focus_areas": ["typescript", "react", "performance"],
                "strictness": "high",
            },
            priority=1,
        ))
        
        # Rust skill bundles
        self.register_skill_bundle(SkillBundle(
            id="rust.code_generation",
            name="Rust Code Generation",
            language=Language.RUST,
            task_type=TaskType.CODE_GENERATION,
            skills=["rust_code_generation", "borrow_checker_aware", "lifetime_analysis"],
            capabilities=["lsp.hover", "lsp.definition", "memory.semantic"],
            config={
                "use_safe_code": True,
                "optimize_for_performance": True,
            },
            priority=1,
        ))
        
        self.register_skill_bundle(SkillBundle(
            id="rust.debugging",
            name="Rust Debugging",
            language=Language.RUST,
            task_type=TaskType.DEBUGGING,
            skills=["rust_error_analysis", "ownership_analysis", "borrow_checker_help"],
            capabilities=["lsp.diagnostics", "lsp.definition", "memory.semantic"],
            config={
                "show_borrow_errors": True,
                "explain_lifetimes": True,
            },
            priority=2,
        ))
    
    def _load_built_in_agent_programs(self) -> None:
        """Load built-in agent programs."""
        # Python agent programs
        self.register_agent_program(AgentProgram(
            language=Language.PYTHON,
            task_type=TaskType.CODE_GENERATION,
            skill_bundles=self.get_skill_bundles(
                language=Language.PYTHON,
                task_type=TaskType.CODE_GENERATION
            ),
            capabilities=["lsp.hover", "lsp.definition", "memory.semantic", "dfc.promote"],
            config={
                "use_templates": True,
                "style_guide": "pep8",
                "max_code_length": 1000,
            },
        ))
        
        self.register_agent_program(AgentProgram(
            language=Language.PYTHON,
            task_type=TaskType.CODE_REVIEW,
            skill_bundles=self.get_skill_bundles(
                language=Language.PYTHON,
                task_type=TaskType.CODE_REVIEW
            ),
            capabilities=["lsp.diagnostics", "memory.semantic", "memory.lexical"],
            config={
                "focus_areas": ["security", "performance", "readability"],
                "strictness": "medium",
            },
        ))
        
        self.register_agent_program(AgentProgram(
            language=Language.PYTHON,
            task_type=TaskType.DEBUGGING,
            skill_bundles=self.get_skill_bundles(
                language=Language.PYTHON,
                task_type=TaskType.DEBUGGING
            ),
            capabilities=["lsp.diagnostics", "lsp.definition", "memory.semantic"],
            config={
                "max_stack_depth": 10,
                "show_locals": True,
            },
        ))
        
        # TypeScript agent programs
        self.register_agent_program(AgentProgram(
            language=Language.TYPESCRIPT,
            task_type=TaskType.CODE_GENERATION,
            skill_bundles=self.get_skill_bundles(
                language=Language.TYPESCRIPT,
                task_type=TaskType.CODE_GENERATION
            ),
            capabilities=["lsp.hover", "lsp.definition", "memory.semantic"],
            config={
                "strict_mode": True,
                "use_interfaces": True,
            },
        ))
        
        self.register_agent_program(AgentProgram(
            language=Language.TYPESCRIPT,
            task_type=TaskType.CODE_REVIEW,
            skill_bundles=self.get_skill_bundles(
                language=Language.TYPESCRIPT,
                task_type=TaskType.CODE_REVIEW
            ),
            capabilities=["lsp.diagnostics", "memory.semantic", "memory.lexical"],
            config={
                "focus_areas": ["typescript", "react", "performance"],
                "strictness": "high",
            },
        ))
        
        # Rust agent programs
        self.register_agent_program(AgentProgram(
            language=Language.RUST,
            task_type=TaskType.CODE_GENERATION,
            skill_bundles=self.get_skill_bundles(
                language=Language.RUST,
                task_type=TaskType.CODE_GENERATION
            ),
            capabilities=["lsp.hover", "lsp.definition", "memory.semantic"],
            config={
                "use_safe_code": True,
                "optimize_for_performance": True,
            },
        ))
        
        self.register_agent_program(AgentProgram(
            language=Language.RUST,
            task_type=TaskType.DEBUGGING,
            skill_bundles=self.get_skill_bundles(
                language=Language.RUST,
                task_type=TaskType.DEBUGGING
            ),
            capabilities=["lsp.diagnostics", "lsp.definition", "memory.semantic"],
            config={
                "show_borrow_errors": True,
                "explain_lifetimes": True,
            },
        ))
    
    def register_skill_bundle(self, skill_bundle: SkillBundle) -> bool:
        """Register a skill bundle."""
        try:
            self.skill_bundles[skill_bundle.id] = skill_bundle
            logger.info(f"Registered skill bundle: {skill_bundle.id}")
            return True
        except Exception as e:
            logger.error(f"Failed to register skill bundle {skill_bundle.id}: {e}")
            return False
    
    def unregister_skill_bundle(self, skill_bundle_id: str) -> bool:
        """Unregister a skill bundle."""
        try:
            if skill_bundle_id not in self.skill_bundles:
                logger.warning(f"Skill bundle {skill_bundle_id} not found")
                return False
            
            del self.skill_bundles[skill_bundle_id]
            logger.info(f"Unregistered skill bundle: {skill_bundle_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to unregister skill bundle {skill_bundle_id}: {e}")
            return False
    
    def get_skill_bundle(self, skill_bundle_id: str) -> Optional[SkillBundle]:
        """Get a skill bundle by ID."""
        return self.skill_bundles.get(skill_bundle_id)
    
    def get_skill_bundles(
        self,
        language: Language,
        task_type: Optional[TaskType] = None,
    ) -> List[SkillBundle]:
        """Get skill bundles by language and task type."""
        results = []
        
        for skill_bundle in self.skill_bundles.values():
            if skill_bundle.language == language:
                if task_type is None or skill_bundle.task_type == task_type:
                    results.append(skill_bundle)
        
        # Sort by priority
        results.sort(key=lambda x: x.priority, reverse=True)
        
        return results
    
    def register_agent_program(self, agent_program: AgentProgram) -> bool:
        """Register an agent program."""
        try:
            key = f"{agent_program.language.value}_{agent_program.task_type.value}"
            self.agent_programs[key] = agent_program
            logger.info(f"Registered agent program: {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to register agent program {key}: {e}")
            return False
    
    def get_agent_program(
        self,
        language: Language,
        task_type: TaskType,
    ) -> Optional[AgentProgram]:
        """Get an agent program by language and task type."""
        key = f"{language.value}_{task_type.value}"
        return self.agent_programs.get(key)
    
    def get_available_languages(self) -> List[Language]:
        """Get list of available languages."""
        languages = set()
        
        for skill_bundle in self.skill_bundles.values():
            languages.add(skill_bundle.language)
        
        return list(languages)
    
    def get_available_task_types(self, language: Language) -> List[TaskType]:
        """Get list of available task types for a language."""
        task_types = set()
        
        for skill_bundle in self.skill_bundles.values():
            if skill_bundle.language == language:
                task_types.add(skill_bundle.task_type)
        
        return list(task_types)
    
    async def agent_program(
        self,
        language: Language,
        task: str,
        task_type: TaskType,
        context: Optional[Dict[str, Any]] = None,
        config_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an agent program for a specific language and task.
        
        Args:
            language: Programming language
            task: Task description
            task_type: Type of task
            context: Additional context for the task
            config_overrides: Configuration overrides
            
        Returns:
            Task execution result
        """
        with emit_span("agent_program", {
            "language": language.value,
            "task": task,
            "task_type": task_type.value,
        }) as span:
            
            # Get agent program
            agent_program = self.get_agent_program(language, task_type)
            if not agent_program:
                return {
                    "success": False,
                    "error": f"No agent program found for {language.value} {task_type.value}",
                }
            
            # Apply config overrides
            if config_overrides:
                agent_program.config.update(config_overrides)
            
            # Get relevant skill bundles
            skill_bundles = self.get_skill_bundles(language, task_type)
            
            # Execute task with skill bundles
            result = await self._execute_task(
                task,
                agent_program,
                skill_bundles,
                context or {},
            )
            
            span.set_attribute("success", result["success"])
            span.set_attribute("skill_bundles_used", len(skill_bundles))
            
            return result
    
    async def _execute_task(
        self,
        task: str,
        agent_program: AgentProgram,
        skill_bundles: List[SkillBundle],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a task using skill bundles."""
        try:
            # Initialize task context
            task_context = {
                "task": task,
                "language": agent_program.language.value,
                "task_type": agent_program.task_type.value,
                "context": context,
                "config": agent_program.config.copy(),
            }
            
            # Execute each skill bundle
            results = []
            for skill_bundle in skill_bundles:
                if not skill_bundle.enabled:
                    continue
                
                skill_result = await self._execute_skill_bundle(
                    skill_bundle,
                    task_context,
                )
                results.append(skill_result)
            
            # Combine results
            final_result = {
                "success": True,
                "task": task,
                "language": agent_program.language.value,
                "task_type": agent_program.task_type.value,
                "skill_bundle_results": results,
                "combined_output": self._combine_results(results),
            }
            
            return final_result
            
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "task": task,
                "language": agent_program.language.value,
                "task_type": agent_program.task_type.value,
            }
    
    async def _execute_skill_bundle(
        self,
        skill_bundle: SkillBundle,
        task_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a skill bundle."""
        try:
            # Prepare skill context
            skill_context = task_context.copy()
            skill_context["skills"] = skill_bundle.skills
            skill_context["capabilities"] = skill_bundle.capabilities
            skill_context["config"] = skill_bundle.config.copy()
            
            # Retrieve relevant information
            retrieval_results = await self.retrieval_orchestrator.retrieve(
                query=task_context["task"],
                capability=None,
                filters={"source": skill_bundle.language.value},
                top_k=5,
                strategies=["ukb", "semantic"],
            )
            
            skill_context["retrieved_info"] = retrieval_results
            
            # Execute skills (mock implementation)
            skill_results = []
            for skill in skill_bundle.skills:
                skill_result = await self._execute_skill(
                    skill,
                    skill_context,
                )
                skill_results.append(skill_result)
            
            return {
                "skill_bundle_id": skill_bundle.id,
                "skill_bundle_name": skill_bundle.name,
                "skills": skill_results,
                "retrieved_count": len(retrieval_results),
                "success": True,
            }
            
        except Exception as e:
            logger.error(f"Skill bundle execution failed: {e}")
            return {
                "skill_bundle_id": skill_bundle.id,
                "skill_bundle_name": skill_bundle.name,
                "error": str(e),
                "success": False,
            }
    
    async def _execute_skill(
        self,
        skill: str,
        skill_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a single skill."""
        # Mock skill execution
        skill_functions = {
            "code_generation": self._mock_code_generation,
            "code_analysis": self._mock_code_analysis,
            "error_analysis": self._mock_error_analysis,
            "pattern_recognition": self._mock_pattern_recognition,
            "test_generation": self._mock_test_generation,
            "type_inference": self._mock_type_inference,
            "interface_generation": self._mock_interface_generation,
            "typescript_analysis": self._mock_typescript_analysis,
            "type_safety_check": self._mock_type_safety_check,
            "react_best_practices": self._mock_react_best_practices,
            "rust_code_generation": self._mock_rust_code_generation,
            "borrow_checker_aware": self._mock_borrow_checker_aware,
            "lifetime_analysis": self._mock_lifetime_analysis,
            "rust_error_analysis": self._mock_rust_error_analysis,
            "ownership_analysis": self._mock_ownership_analysis,
            "borrow_checker_help": self._mock_borrow_checker_help,
        }
        
        skill_func = skill_functions.get(skill)
        if skill_func:
            return await skill_func(skill_context)
        else:
            return {
                "skill": skill,
                "result": f"Mock execution of {skill}",
                "success": True,
            }
    
    def _combine_results(self, results: List[Dict[str, Any]]) -> str:
        """Combine skill bundle results into a single output."""
        outputs = []
        for result in results:
            if result.get("success"):
                if "skills" in result:
                    for skill in result["skills"]:
                        if skill.get("success"):
                            outputs.append(skill.get("result", ""))
        
        return "\n\n".join(outputs)
    
    # Mock skill implementations
    async def _mock_code_generation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "code_generation",
            "result": f"Generated code for: {context['task']}",
            "success": True,
        }
    
    async def _mock_code_analysis(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "code_analysis",
            "result": f"Analyzed code for: {context['task']}",
            "success": True,
        }
    
    async def _mock_error_analysis(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "error_analysis",
            "result": f"Analyzed errors for: {context['task']}",
            "success": True,
        }
    
    async def _mock_pattern_recognition(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "pattern_recognition",
            "result": f"Recognized patterns in: {context['task']}",
            "success": True,
        }
    
    async def _mock_test_generation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "test_generation",
            "result": f"Generated tests for: {context['task']}",
            "success": True,
        }
    
    async def _mock_type_inference(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "type_inference",
            "result": f"Inferred types for: {context['task']}",
            "success": True,
        }
    
    async def _mock_interface_generation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "interface_generation",
            "result": f"Generated interfaces for: {context['task']}",
            "success": True,
        }
    
    async def _mock_typescript_analysis(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "typescript_analysis",
            "result": f"Analyzed TypeScript code for: {context['task']}",
            "success": True,
        }
    
    async def _mock_type_safety_check(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "type_safety_check",
            "result": f"Checked type safety for: {context['task']}",
            "success": True,
        }
    
    async def _mock_react_best_practices(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "react_best_practices",
            "result": f"Applied React best practices to: {context['task']}",
            "success": True,
        }
    
    async def _mock_rust_code_generation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "rust_code_generation",
            "result": f"Generated Rust code for: {context['task']}",
            "success": True,
        }
    
    async def _mock_borrow_checker_aware(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "borrow_checker_aware",
            "result": f"Made code borrow-checker aware for: {context['task']}",
            "success": True,
        }
    
    async def _mock_lifetime_analysis(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "lifetime_analysis",
            "result": f"Analyzed lifetimes for: {context['task']}",
            "success": True,
        }
    
    async def _mock_rust_error_analysis(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "rust_error_analysis",
            "result": f"Analyzed Rust errors for: {context['task']}",
            "success": True,
        }
    
    async def _mock_ownership_analysis(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "ownership_analysis",
            "result": f"Analyzed ownership for: {context['task']}",
            "success": True,
        }
    
    async def _mock_borrow_checker_help(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "skill": "borrow_checker_help",
            "result": f"Provided borrow checker help for: {context['task']}",
            "success": True,
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get layer statistics."""
        return {
            "total_agent_programs": len(self.agent_programs),
            "total_skill_bundles": len(self.skill_bundles),
            "languages": [lang.value for lang in self.get_available_languages()],
            "task_types": {
                lang.value: [tt.value for tt in self.get_available_task_types(lang)]
                for lang in self.get_available_languages()
            },
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        try:
            stats = self.get_statistics()
            
            # Check agent programs
            program_status = {}
            for key in self.agent_programs:
                program_status[key] = "healthy"
            
            # Check skill bundles
            bundle_status = {}
            for bundle_id in self.skill_bundles:
                bundle_status[bundle_id] = "healthy"
            
            return {
                "status": "healthy",
                "statistics": stats,
                "agent_programs": program_status,
                "skill_bundles": bundle_status,
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }


# Global language capability layer instance
_language_capability_layer: Optional[LanguageCapabilityLayer] = None


def get_language_capability_layer() -> LanguageCapabilityLayer:
    """Get global language capability layer instance."""
    global _language_capability_layer
    if _language_capability_layer is None:
        _language_capability_layer = LanguageCapabilityLayer()
    return _language_capability_layer


def initialize_language_capability_layer() -> LanguageCapabilityLayer:
    """Initialize global language capability layer."""
    global _language_capability_layer
    _language_capability_layer = LanguageCapabilityLayer()
    return _language_capability_layer