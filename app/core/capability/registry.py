"""CapabilityRegistry - Manages capabilities across different languages and contexts."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union, Callable
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path

from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


class CapabilityType(Enum):
    """Types of capabilities."""

    LANGUAGE = "language"
    TOOL = "tool"
    SKILL = "skill"
    HOOK = "hook"
    MEMORY = "memory"
    LSP = "lsp"
    RETRIEVAL = "retrieval"
    DFC = "dfc"
    WORKFLOW = "workflow"


class CapabilityStatus(Enum):
    """Status of capabilities."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"


@dataclass
class Capability:
    """Represents a capability."""

    id: str
    name: str
    type: CapabilityType
    description: str
    language: Optional[str] = None
    status: CapabilityStatus = CapabilityStatus.ACTIVE
    version: str = "1.0.0"
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "language": self.language,
            "status": self.status.value,
            "version": self.version,
            "dependencies": self.dependencies,
            "tags": self.tags,
            "config": self.config,
            "metadata": self.metadata,
        }


@dataclass
class LanguageCapability:
    """Represents language-specific capabilities."""

    language: str
    capabilities: List[Capability]
    default_capabilities: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "language": self.language,
            "capabilities": [cap.to_dict() for cap in self.capabilities],
            "default_capabilities": self.default_capabilities,
            "required_capabilities": self.required_capabilities,
        }


class CapabilityRegistry:
    """Registry for managing capabilities across different languages and contexts."""

    def __init__(self):
        # Global capabilities
        self.capabilities: Dict[str, Capability] = {}

        # Language-specific capabilities
        self.language_capabilities: Dict[str, LanguageCapability] = {}

        # Capability type indexes
        self.type_index: Dict[CapabilityType, List[str]] = {}

        # Language index
        self.language_index: Dict[str, List[str]] = {}

        # Tag index
        self.tag_index: Dict[str, List[str]] = {}

        # Status index
        self.status_index: Dict[CapabilityStatus, List[str]] = {}

        # Load built-in capabilities
        self._load_built_in_capabilities()

    def _load_built_in_capabilities(self) -> None:
        """Load built-in capabilities."""
        # LSP capabilities
        self.register_capability(
            Capability(
                id="lsp.hover",
                name="LSP Hover",
                type=CapabilityType.LSP,
                description="Get hover information for a position in a file",
                language=None,
                tags=["lsp", "code", "documentation"],
                config={
                    "timeout": 10,
                    "cache": True,
                },
            )
        )

        self.register_capability(
            Capability(
                id="lsp.definition",
                name="LSP Definition",
                type=CapabilityType.LSP,
                description="Get definition location for a symbol",
                language=None,
                tags=["lsp", "code", "navigation"],
                config={
                    "timeout": 10,
                    "cache": True,
                },
            )
        )

        self.register_capability(
            Capability(
                id="lsp.references",
                name="LSP References",
                type=CapabilityType.LSP,
                description="Get all references to a symbol",
                language=None,
                tags=["lsp", "code", "navigation"],
                config={
                    "timeout": 20,
                    "cache": True,
                },
            )
        )

        self.register_capability(
            Capability(
                id="lsp.symbol_search",
                name="LSP Symbol Search",
                type=CapabilityType.LSP,
                description="Search for symbols in the workspace",
                language=None,
                tags=["lsp", "code", "navigation"],
                config={
                    "timeout": 50,
                    "cache": True,
                },
            )
        )

        # Memory capabilities
        self.register_capability(
            Capability(
                id="memory.semantic",
                name="Semantic Memory Search",
                type=CapabilityType.MEMORY,
                description="Search semantic memory using embeddings",
                language=None,
                tags=["memory", "semantic", "ai"],
                config={
                    "top_k": 5,
                    "threshold": 0.7,
                },
            )
        )

        self.register_capability(
            Capability(
                id="memory.lexical",
                name="Lexical Memory Search",
                type=CapabilityType.MEMORY,
                description="Search lexical memory using keyword matching",
                language=None,
                tags=["memory", "lexical", "search"],
                config={
                    "top_k": 10,
                    "fuzzy": True,
                },
            )
        )

        # DFC capabilities
        self.register_capability(
            Capability(
                id="dfc.promote",
                name="DFC Promotion",
                type=CapabilityType.DFC,
                description="Promote content to DFC layers",
                language=None,
                tags=["dfc", "cache", "optimization"],
                config={
                    "layer": "HOT",
                    "threshold": 0.8,
                },
            )
        )

        # Workflow capabilities
        self.register_capability(
            Capability(
                id="workflow.plan",
                name="Plan Workflow",
                type=CapabilityType.WORKFLOW,
                description="Execute planning workflow",
                language=None,
                tags=["workflow", "planning", "tri-model"],
                config={
                    "max_iterations": 3,
                    "timeout": 30,
                },
            )
        )

        self.register_capability(
            Capability(
                id="workflow.execute",
                name="Execute Workflow",
                type=CapabilityType.WORKFLOW,
                description="Execute execution workflow",
                language=None,
                tags=["workflow", "execution", "tri-model"],
                config={
                    "max_duration": 300,
                    "timeout": 60,
                },
            )
        )

        self.register_capability(
            Capability(
                id="workflow.test",
                name="Test Workflow",
                type=CapabilityType.WORKFLOW,
                description="Execute testing workflow",
                language=None,
                tags=["workflow", "testing", "tri-model"],
                config={
                    "max_tests": 10,
                    "timeout": 120,
                },
            )
        )

        # Register language-specific capabilities
        self._register_language_capabilities()

    def _register_language_capabilities(self) -> None:
        """Register language-specific capabilities."""
        # Python capabilities
        python_caps = [
            Capability(
                id="python.linter",
                name="Python Linter",
                type=CapabilityType.TOOL,
                description="Run Python linter",
                language="python",
                tags=["python", "linter", "quality"],
            ),
            Capability(
                id="python.formatter",
                name="Python Formatter",
                type=CapabilityType.TOOL,
                description="Format Python code",
                language="python",
                tags=["python", "formatter", "quality"],
            ),
            Capability(
                id="python.test",
                name="Python Test Runner",
                type=CapabilityType.TOOL,
                description="Run Python tests",
                language="python",
                tags=["python", "testing", "quality"],
            ),
        ]

        # TypeScript capabilities
        typescript_caps = [
            Capability(
                id="typescript.linter",
                name="TypeScript Linter",
                type=CapabilityType.TOOL,
                description="Run TypeScript linter",
                language="typescript",
                tags=["typescript", "linter", "quality"],
            ),
            Capability(
                id="typescript.formatter",
                name="TypeScript Formatter",
                type=CapabilityType.TOOL,
                description="Format TypeScript code",
                language="typescript",
                tags=["typescript", "formatter", "quality"],
            ),
            Capability(
                id="typescript.test",
                name="TypeScript Test Runner",
                type=CapabilityType.TOOL,
                description="Run TypeScript tests",
                language="typescript",
                tags=["typescript", "testing", "quality"],
            ),
        ]

        # Register languages
        self.register_language("python", python_caps)
        self.register_language("typescript", typescript_caps)

    def register_capability(self, capability: Capability) -> bool:
        """Register a capability."""
        try:
            # Check if capability already exists
            if capability.id in self.capabilities:
                logger.warning(f"Capability {capability.id} already exists, updating")

            # Register capability
            self.capabilities[capability.id] = capability

            # Update indexes
            self._update_indexes(capability)

            logger.info(f"Registered capability: {capability.id}")
            return True

        except Exception as e:
            logger.error(f"Failed to register capability {capability.id}: {e}")
            return False

    def unregister_capability(self, capability_id: str) -> bool:
        """Unregister a capability."""
        try:
            if capability_id not in self.capabilities:
                logger.warning(f"Capability {capability_id} not found")
                return False

            # Remove capability
            capability = self.capabilities.pop(capability_id)

            # Update indexes
            self._remove_from_indexes(capability)

            logger.info(f"Unregistered capability: {capability_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to unregister capability {capability_id}: {e}")
            return False

    def register_language(
        self,
        language: str,
        capabilities: List[Capability],
        default_capabilities: Optional[List[str]] = None,
        required_capabilities: Optional[List[str]] = None,
    ) -> bool:
        """Register language-specific capabilities."""
        try:
            # Create language capability
            lang_cap = LanguageCapability(
                language=language,
                capabilities=capabilities,
                default_capabilities=default_capabilities or [],
                required_capabilities=required_capabilities or [],
            )

            # Register language
            self.language_capabilities[language] = lang_cap

            # Update language index
            if language not in self.language_index:
                self.language_index[language] = []

            for cap in capabilities:
                if cap.id not in self.capabilities:
                    self.register_capability(cap)
                self.language_index[language].append(cap.id)

            logger.info(
                f"Registered language {language} with {len(capabilities)} capabilities"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to register language {language}: {e}")
            return False

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        """Get a capability by ID."""
        return self.capabilities.get(capability_id)

    def get_capabilities_by_type(
        self, capability_type: CapabilityType
    ) -> List[Capability]:
        """Get capabilities by type."""
        capability_ids = self.type_index.get(capability_type, [])
        return [
            self.capabilities[cap_id]
            for cap_id in capability_ids
            if cap_id in self.capabilities
        ]

    def get_capabilities_by_language(self, language: str) -> List[Capability]:
        """Get capabilities by language."""
        if language not in self.language_capabilities:
            return []

        lang_cap = self.language_capabilities[language]
        return lang_cap.capabilities

    def get_capabilities_by_tag(self, tag: str) -> List[Capability]:
        """Get capabilities by tag."""
        capability_ids = self.tag_index.get(tag, [])
        return [
            self.capabilities[cap_id]
            for cap_id in capability_ids
            if cap_id in self.capabilities
        ]

    def get_capabilities_by_status(self, status: CapabilityStatus) -> List[Capability]:
        """Get capabilities by status."""
        capability_ids = self.status_index.get(status, [])
        return [
            self.capabilities[cap_id]
            for cap_id in capability_ids
            if cap_id in self.capabilities
        ]

    def search_capabilities(
        self,
        query: str,
        capability_type: Optional[CapabilityType] = None,
        language: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[CapabilityStatus] = None,
    ) -> List[Capability]:
        """Search capabilities."""
        results = []

        # Get all capabilities
        all_capabilities = list(self.capabilities.values())

        for capability in all_capabilities:
            # Filter by type
            if capability_type and capability.type != capability_type:
                continue

            # Filter by language
            if language and capability.language != language:
                continue

            # Filter by status
            if status and capability.status != status:
                continue

            # Filter by tags
            if tags and not any(tag in capability.tags for tag in tags):
                continue

            # Filter by query
            if query:
                query_lower = query.lower()
                if (
                    query_lower not in capability.name.lower()
                    and query_lower not in capability.description.lower()
                    and query_lower not in capability.id.lower()
                ):
                    continue

            results.append(capability)

        return results

    def get_default_capabilities(self, language: str) -> List[Capability]:
        """Get default capabilities for a language."""
        if language not in self.language_capabilities:
            return []

        lang_cap = self.language_capabilities[language]
        default_ids = lang_cap.default_capabilities

        return [
            self.capabilities[cap_id]
            for cap_id in default_ids
            if cap_id in self.capabilities
        ]

    def get_required_capabilities(self, language: str) -> List[Capability]:
        """Get required capabilities for a language."""
        if language not in self.language_capabilities:
            return []

        lang_cap = self.language_capabilities[language]
        required_ids = lang_cap.required_capabilities

        return [
            self.capabilities[cap_id]
            for cap_id in required_ids
            if cap_id in self.capabilities
        ]

    def get_capability_dependencies(self, capability_id: str) -> List[Capability]:
        """Get dependencies for a capability."""
        capability = self.get_capability(capability_id)
        if not capability:
            return []

        dependencies = []
        for dep_id in capability.dependencies:
            dep_cap = self.get_capability(dep_id)
            if dep_cap:
                dependencies.append(dep_cap)

        return dependencies

    def check_capability_requirements(self, language: str) -> Dict[str, Any]:
        """Check if required capabilities are available for a language."""
        if language not in self.language_capabilities:
            return {"status": "error", "message": f"Language {language} not found"}

        lang_cap = self.language_capabilities[language]
        required_ids = lang_cap.required_capabilities

        missing = []
        available = []

        for req_id in required_ids:
            if req_id in self.capabilities:
                available.append(req_id)
            else:
                missing.append(req_id)

        return {
            "status": "success",
            "language": language,
            "required": required_ids,
            "available": available,
            "missing": missing,
            "complete": len(missing) == 0,
        }

    def _update_indexes(self, capability: Capability) -> None:
        """Update indexes for a capability."""
        # Type index
        if capability.type not in self.type_index:
            self.type_index[capability.type] = []
        if capability.id not in self.type_index[capability.type]:
            self.type_index[capability.type].append(capability.id)

        # Language index
        if capability.language:
            if capability.language not in self.language_index:
                self.language_index[capability.language] = []
            if capability.id not in self.language_index[capability.language]:
                self.language_index[capability.language].append(capability.id)

        # Tag index
        for tag in capability.tags:
            if tag not in self.tag_index:
                self.tag_index[tag] = []
            if capability.id not in self.tag_index[tag]:
                self.tag_index[tag].append(capability.id)

        # Status index
        if capability.status not in self.status_index:
            self.status_index[capability.status] = []
        if capability.id not in self.status_index[capability.status]:
            self.status_index[capability.status].append(capability.id)

    def _remove_from_indexes(self, capability: Capability) -> None:
        """Remove capability from indexes."""
        # Type index
        if (
            capability.type in self.type_index
            and capability.id in self.type_index[capability.type]
        ):
            self.type_index[capability.type].remove(capability.id)

        # Language index
        if capability.language and capability.language in self.language_index:
            if capability.id in self.language_index[capability.language]:
                self.language_index[capability.language].remove(capability.id)

        # Tag index
        for tag in capability.tags:
            if tag in self.tag_index and capability.id in self.tag_index[tag]:
                self.tag_index[tag].remove(capability.id)

        # Status index
        if (
            capability.status in self.status_index
            and capability.id in self.status_index[capability.status]
        ):
            self.status_index[capability.status].remove(capability.id)

    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_capabilities": len(self.capabilities),
            "total_languages": len(self.language_capabilities),
            "capabilities_by_type": {
                cap_type.value: len(cap_ids)
                for cap_type, cap_ids in self.type_index.items()
            },
            "capabilities_by_status": {
                status.value: len(cap_ids)
                for status, cap_ids in self.status_index.items()
            },
            "languages": list(self.language_capabilities.keys()),
            "tags": list(self.tag_index.keys()),
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        try:
            # Check basic registry
            stats = self.get_statistics()

            # Check language capabilities
            language_status = {}
            for language in self.language_capabilities:
                check = self.check_capability_requirements(language)
                language_status[language] = check["status"]

            return {
                "status": "healthy",
                "statistics": stats,
                "languages": language_status,
                "total_capabilities": stats["total_capabilities"],
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }


# Global capability registry instance
_capability_registry: Optional[CapabilityRegistry] = None


def get_capability_registry() -> CapabilityRegistry:
    """Get global capability registry instance."""
    global _capability_registry
    if _capability_registry is None:
        _capability_registry = CapabilityRegistry()
    return _capability_registry


def initialize_capability_registry() -> CapabilityRegistry:
    """Initialize global capability registry."""
    global _capability_registry
    _capability_registry = CapabilityRegistry()
    return _capability_registry
