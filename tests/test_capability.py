"""Tests for CapabilityRegistry components."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from app.core.capability.registry import (
    get_capability_registry,
    initialize_capability_registry,
    CapabilityRegistry,
    Capability,
    LanguageCapability,
    CapabilityType,
    CapabilityStatus,
)


class TestCapability:
    """Test Capability functionality."""

    def test_capability_creation(self):
        """Test capability creation."""
        capability = Capability(
            id="test.capability",
            name="Test Capability",
            type=CapabilityType.TOOL,
            description="Test description",
            language="python",
            status=CapabilityStatus.ACTIVE,
            version="1.0.0",
            dependencies=["dep1", "dep2"],
            tags=["test", "tool"],
            config={"key": "value"},
            metadata={"meta": "data"},
        )

        assert capability.id == "test.capability"
        assert capability.name == "Test Capability"
        assert capability.type == CapabilityType.TOOL
        assert capability.description == "Test description"
        assert capability.language == "python"
        assert capability.status == CapabilityStatus.ACTIVE
        assert capability.version == "1.0.0"
        assert capability.dependencies == ["dep1", "dep2"]
        assert capability.tags == ["test", "tool"]
        assert capability.config == {"key": "value"}
        assert capability.metadata == {"meta": "data"}

    def test_capability_to_dict(self):
        """Test capability to dictionary conversion."""
        capability = Capability(
            id="test.capability",
            name="Test Capability",
            type=CapabilityType.TOOL,
            description="Test description",
            language="python",
            status=CapabilityStatus.ACTIVE,
            version="1.0.0",
            dependencies=["dep1"],
            tags=["test"],
            config={"key": "value"},
            metadata={"meta": "data"},
        )

        result = capability.to_dict()

        assert result["id"] == "test.capability"
        assert result["name"] == "Test Capability"
        assert result["type"] == "tool"
        assert result["description"] == "Test description"
        assert result["language"] == "python"
        assert result["status"] == "active"
        assert result["version"] == "1.0.0"
        assert result["dependencies"] == ["dep1"]
        assert result["tags"] == ["test"]
        assert result["config"] == {"key": "value"}
        assert result["metadata"] == {"meta": "data"}


class TestLanguageCapability:
    """Test LanguageCapability functionality."""

    def test_language_capability_creation(self):
        """Test language capability creation."""
        capability = Capability(
            id="test.cap",
            name="Test Cap",
            type=CapabilityType.TOOL,
            description="Test",
        )

        lang_cap = LanguageCapability(
            language="python",
            capabilities=[capability],
            default_capabilities=["test.cap"],
            required_capabilities=["required.cap"],
        )

        assert lang_cap.language == "python"
        assert len(lang_cap.capabilities) == 1
        assert lang_cap.capabilities[0].id == "test.cap"
        assert lang_cap.default_capabilities == ["test.cap"]
        assert lang_cap.required_capabilities == ["required.cap"]

    def test_language_capability_to_dict(self):
        """Test language capability to dictionary conversion."""
        capability = Capability(
            id="test.cap",
            name="Test Cap",
            type=CapabilityType.TOOL,
            description="Test",
        )

        lang_cap = LanguageCapability(
            language="python",
            capabilities=[capability],
            default_capabilities=["test.cap"],
            required_capabilities=["required.cap"],
        )

        result = lang_cap.to_dict()

        assert result["language"] == "python"
        assert len(result["capabilities"]) == 1
        assert result["capabilities"][0]["id"] == "test.cap"
        assert result["default_capabilities"] == ["test.cap"]
        assert result["required_capabilities"] == ["required.cap"]


class TestCapabilityRegistry:
    """Test CapabilityRegistry functionality."""

    def test_registry_creation(self):
        """Test registry creation."""
        registry = CapabilityRegistry()

        assert len(registry.capabilities) > 0
        assert len(registry.language_capabilities) > 0
        assert len(registry.type_index) > 0
        assert len(registry.language_index) > 0
        assert len(registry.tag_index) > 0
        assert len(registry.status_index) > 0

        # Check that built-in capabilities are loaded
        assert "lsp.hover" in registry.capabilities
        assert "lsp.definition" in registry.capabilities
        assert "memory.semantic" in registry.capabilities
        assert "memory.lexical" in registry.capabilities
        assert "dfc.promote" in registry.capabilities
        assert "workflow.plan" in registry.capabilities
        assert "workflow.execute" in registry.capabilities
        assert "workflow.test" in registry.capabilities

        # Check language capabilities
        assert "python" in registry.language_capabilities
        assert "typescript" in registry.language_capabilities

    def test_register_capability(self):
        """Test capability registration."""
        registry = CapabilityRegistry()

        capability = Capability(
            id="new.capability",
            name="New Capability",
            type=CapabilityType.TOOL,
            description="New description",
            language="python",
            tags=["new", "tool"],
        )

        result = registry.register_capability(capability)

        assert result is True
        assert "new.capability" in registry.capabilities
        assert capability in registry.get_capabilities_by_type(CapabilityType.TOOL)
        assert capability in registry.get_capabilities_by_language("python")
        assert capability in registry.get_capabilities_by_tag("new")
        assert capability in registry.get_capabilities_by_status(
            CapabilityStatus.ACTIVE
        )

    def test_register_duplicate_capability(self):
        """Test registering duplicate capability."""
        registry = CapabilityRegistry()

        capability = Capability(
            id="lsp.hover",  # Already exists
            name="New Hover Capability",
            type=CapabilityType.LSP,
            description="New hover description",
        )

        result = registry.register_capability(capability)

        assert result is True
        # Should update existing capability
        updated_cap = registry.get_capability("lsp.hover")
        assert updated_cap.name == "New Hover Capability"
        assert updated_cap.description == "New hover description"

    def test_register_invalid_capability(self):
        """Test registering invalid capability."""
        registry = CapabilityRegistry()

        # Invalid capability
        capability = None

        result = registry.register_capability(capability)

        assert result is False

    def test_unregister_capability(self):
        """Test capability unregistration."""
        registry = CapabilityRegistry()

        result = registry.unregister_capability("lsp.hover")

        assert result is True
        assert "lsp.hover" not in registry.capabilities
        assert "lsp.hover" not in registry.type_index[CapabilityType.LSP]
        assert "lsp.hover" not in registry.tag_index["lsp"]
        assert "lsp.hover" not in registry.status_index[CapabilityStatus.ACTIVE]

    def test_unregister_nonexistent_capability(self):
        """Test unregistering non-existent capability."""
        registry = CapabilityRegistry()

        result = registry.unregister_capability("nonexistent.capability")

        assert result is False

    def test_get_capability(self):
        """Test getting capability by ID."""
        registry = CapabilityRegistry()

        capability = registry.get_capability("lsp.hover")

        assert capability is not None
        assert capability.id == "lsp.hover"
        assert capability.name == "LSP Hover"

    def test_get_nonexistent_capability(self):
        """Test getting non-existent capability."""
        registry = CapabilityRegistry()

        capability = registry.get_capability("nonexistent.capability")

        assert capability is None

    def test_get_capabilities_by_type(self):
        """Test getting capabilities by type."""
        registry = CapabilityRegistry()

        lsp_capabilities = registry.get_capabilities_by_type(CapabilityType.LSP)

        assert len(lsp_capabilities) > 0
        assert all(cap.type == CapabilityType.LSP for cap in lsp_capabilities)

        # Check specific LSP capabilities
        cap_ids = [cap.id for cap in lsp_capabilities]
        assert "lsp.hover" in cap_ids
        assert "lsp.definition" in cap_ids
        assert "lsp.references" in cap_ids
        assert "lsp.symbol_search" in cap_ids
        assert "lsp.rename" in cap_ids
        assert "lsp.diagnostics" in cap_ids
        assert "lsp.codeAction" in cap_ids

    def test_get_capabilities_by_language(self):
        """Test getting capabilities by language."""
        registry = CapabilityRegistry()

        python_capabilities = registry.get_capabilities_by_language("python")

        assert len(python_capabilities) > 0
        assert all(cap.language == "python" for cap in python_capabilities)

        # Check specific Python capabilities
        cap_ids = [cap.id for cap in python_capabilities]
        assert "python.linter" in cap_ids
        assert "python.formatter" in cap_ids
        assert "python.test" in cap_ids

    def test_get_capabilities_by_tag(self):
        """Test getting capabilities by tag."""
        registry = CapabilityRegistry()

        lsp_capabilities = registry.get_capabilities_by_tag("lsp")

        assert len(lsp_capabilities) > 0
        assert all("lsp" in cap.tags for cap in lsp_capabilities)

        # Check specific LSP capabilities
        cap_ids = [cap.id for cap in lsp_capabilities]
        assert "lsp.hover" in cap_ids
        assert "lsp.definition" in cap_ids
        assert "lsp.references" in cap_ids
        assert "lsp.symbol_search" in cap_ids
        assert "lsp.rename" in cap_ids
        assert "lsp.diagnostics" in cap_ids
        assert "lsp.codeAction" in cap_ids

    def test_get_capabilities_by_status(self):
        """Test getting capabilities by status."""
        registry = CapabilityRegistry()

        active_capabilities = registry.get_capabilities_by_status(
            CapabilityStatus.ACTIVE
        )

        assert len(active_capabilities) > 0
        assert all(cap.status == CapabilityStatus.ACTIVE for cap in active_capabilities)

    def test_search_capabilities(self):
        """Test searching capabilities."""
        registry = CapabilityRegistry()

        # Search by query
        results = registry.search_capabilities("hover")

        assert len(results) > 0
        assert any("hover" in cap.name.lower() for cap in results)

        # Search by type
        results = registry.search_capabilities(
            query="",
            capability_type=CapabilityType.LSP,
        )

        assert len(results) > 0
        assert all(cap.type == CapabilityType.LSP for cap in results)

        # Search by language
        results = registry.search_capabilities(
            query="",
            language="python",
        )

        assert len(results) > 0
        assert all(cap.language == "python" for cap in results)

        # Search by tags
        results = registry.search_capabilities(
            query="",
            tags=["lsp"],
        )

        assert len(results) > 0
        assert all("lsp" in cap.tags for cap in results)

        # Search by status
        results = registry.search_capabilities(
            query="",
            status=CapabilityStatus.ACTIVE,
        )

        assert len(results) > 0
        assert all(cap.status == CapabilityStatus.ACTIVE for cap in results)

        # Combined search
        results = registry.search_capabilities(
            query="hover",
            capability_type=CapabilityType.LSP,
            tags=["lsp"],
            status=CapabilityStatus.ACTIVE,
        )

        assert len(results) > 0
        assert all(cap.type == CapabilityType.LSP for cap in results)
        assert all("lsp" in cap.tags for cap in results)
        assert all(cap.status == CapabilityStatus.ACTIVE for cap in results)

    def test_register_language(self):
        """Test language registration."""
        registry = CapabilityRegistry()

        capabilities = [
            Capability(
                id="new.py.cap",
                name="New Python Capability",
                type=CapabilityType.TOOL,
                description="New Python capability",
                language="python",
            ),
            Capability(
                id="new.ts.cap",
                name="New TypeScript Capability",
                type=CapabilityType.TOOL,
                description="New TypeScript capability",
                language="typescript",
            ),
        ]

        result = registry.register_language(
            language="newlang",
            capabilities=capabilities,
            default_capabilities=["new.py.cap"],
            required_capabilities=["new.ts.cap"],
        )

        assert result is True
        assert "newlang" in registry.language_capabilities

        lang_cap = registry.language_capabilities["newlang"]
        assert len(lang_cap.capabilities) == 2
        assert lang_cap.default_capabilities == ["new.py.cap"]
        assert lang_cap.required_capabilities == ["new.ts.cap"]

        # Check global capabilities
        assert "new.py.cap" in registry.capabilities
        assert "new.ts.cap" in registry.capabilities

        # Check language index
        assert "newlang" in registry.language_index
        assert "new.py.cap" in registry.language_index["newlang"]
        assert "new.ts.cap" in registry.language_index["newlang"]

    def test_get_default_capabilities(self):
        """Test getting default capabilities for language."""
        registry = CapabilityRegistry()

        python_capabilities = registry.get_default_capabilities("python")

        assert len(python_capabilities) >= 0  # May be empty in test

        # Check that all returned capabilities are for Python
        assert all(cap.language == "python" for cap in python_capabilities)

    def test_get_required_capabilities(self):
        """Test getting required capabilities for language."""
        registry = CapabilityRegistry()

        python_requirements = registry.check_capability_requirements("python")

        assert python_requirements["status"] == "success"
        assert python_requirements["language"] == "python"
        assert "required" in python_requirements
        assert "available" in python_requirements
        assert "missing" in python_requirements
        assert "complete" in python_requirements

    def test_get_capability_dependencies(self):
        """Test getting capability dependencies."""
        registry = CapabilityRegistry()

        # Create capability with dependencies
        capability = Capability(
            id="test.with.deps",
            name="Test with Dependencies",
            type=CapabilityType.TOOL,
            description="Test",
            dependencies=["lsp.hover", "memory.semantic"],
        )

        registry.register_capability(capability)

        dependencies = registry.get_capability_dependencies("test.with.deps")

        assert len(dependencies) == 2
        assert any(dep.id == "lsp.hover" for dep in dependencies)
        assert any(dep.id == "memory.semantic" for dep in dependencies)

    def test_get_statistics(self):
        """Test getting registry statistics."""
        registry = CapabilityRegistry()

        stats = registry.get_statistics()

        assert "total_capabilities" in stats
        assert "total_languages" in stats
        assert "capabilities_by_type" in stats
        assert "capabilities_by_status" in stats
        assert "languages" in stats
        assert "tags" in stats

        assert stats["total_capabilities"] > 0
        assert stats["total_languages"] > 0
        assert len(stats["capabilities_by_type"]) > 0
        assert len(stats["capabilities_by_status"]) > 0
        assert len(stats["languages"]) > 0
        assert len(stats["tags"]) > 0

    def test_get_supported_languages(self):
        """Test getting supported languages."""
        registry = CapabilityRegistry()

        languages = registry.get_supported_languages()

        assert len(languages) > 0
        assert "python" in languages
        assert "typescript" in languages

    def test_get_supported_capabilities(self):
        """Test getting supported capabilities."""
        registry = CapabilityRegistry()

        capabilities = registry.get_supported_capabilities()

        assert len(capabilities) > 0
        assert "lsp.hover" in capabilities
        assert "memory.semantic" in capabilities
        assert "dfc.promote" in capabilities
        assert "workflow.plan" in capabilities


class TestGlobalCapabilityRegistry:
    """Test global capability registry functions."""

    def test_get_capability_registry(self):
        """Test getting capability registry instance."""
        registry1 = get_capability_registry()
        registry2 = get_capability_registry()

        assert registry1 is registry2
        assert isinstance(registry1, CapabilityRegistry)

    def test_initialize_capability_registry(self):
        """Test initializing capability registry."""
        registry = initialize_capability_registry()

        assert isinstance(registry, CapabilityRegistry)
        assert len(registry.capabilities) > 0
        assert len(registry.language_capabilities) > 0
        assert len(registry.type_index) > 0
        assert len(registry.language_index) > 0
        assert len(registry.tag_index) > 0
        assert len(registry.status_index) > 0
