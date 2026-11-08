"""Tests for DFC integration."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from app.core.dfc.integration import (
    DFCIntegration,
    get_dfc_integration,
    initialize_dfc_integration,
)
from app.core.dfc import DFC


class TestDFCIntegration:
    """Test DFC integration functionality."""

    def test_dfc_integration_initialization(self):
        """Test DFC integration initialization."""
        dfc = DFC()
        integration = DFCIntegration(dfc)

        assert integration.dfc is dfc
        assert integration.metrics is not None

    @pytest.mark.asyncio
    async def test_initialize_from_session(self):
        """Test initialization from session state."""
        dfc = DFC()
        integration = DFCIntegration(dfc)

        # Mock session state
        session_state = {
            "recent_tool_results": {
                "write": {"file": "test.py", "content": "# test"},
                "read": {"file": "test.py", "content": "# test"},
            },
            "memory_items": [
                {"id": "1", "content": "Memory item 1"},
                {"id": "2", "content": "Memory item 2"},
            ],
        }

        # Mock background compactor
        with patch.object(dfc, "start_background_compactor") as mock_start:
            await integration.initialize_from_session("session_1", session_state)

            # Check that background compactor was started
            mock_start.assert_called_once()

            # Check that HOT layer was populated
            assert "write" in dfc.hot
            assert "read" in dfc.hot
            assert "memory_1" in dfc.warm
            assert "memory_2" in dfc.warm

    @pytest.mark.asyncio
    async def test_promote_tool_result(self):
        """Test promoting tool result to HOT layer."""
        dfc = DFC()
        integration = DFCIntegration(dfc)

        # Mock tool result
        tool_result = {"file": "test.py", "content": "# test code"}

        # Mock Redis save
        with patch.object(dfc, "save_to_redis") as mock_save:
            await integration.promote_tool_result("write", tool_result)

            # Check that result was promoted
            assert "write" in dfc.hot
            assert dfc.hot["write"] == "{'file': 'test.py', 'content': '# test code'}"

            # Check that metrics were updated
            integration.metrics.increment_promote_to_hot.assert_called()

            # Check that Redis was called
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_promote_memory_item(self):
        """Test promoting memory item to HOT layer."""
        dfc = DFC()
        integration = DFCIntegration(dfc)

        # Mock memory item
        memory_item = Mock()
        memory_item.id = "memory_1"
        memory_item.content = "Memory content"

        # Mock Redis save
        with patch.object(dfc, "save_to_redis") as mock_save:
            await integration.promote_memory_item(memory_item)

            # Check that item was promoted
            assert "memory_memory_1" in dfc.hot
            assert dfc.hot["memory_memory_1"] == "Memory content"

            # Check that metrics were updated
            integration.metrics.increment_promote_to_hot.assert_called()

            # Check that Redis was called
            mock_save.assert_called_once()

    def test_get_context_for_prompt(self):
        """Test getting context for system prompt."""
        dfc = DFC()
        integration = DFCIntegration(dfc)

        # Add items to layers
        dfc.promote_to_hot("key1", "value1")
        dfc.warm["key2"] = "value2"
        dfc.cold.append(Mock(content_hash="hash1", summary="summary1"))

        # Mock plan
        plan = {
            "cacheable_prefix": "System prompt",
            "prefetch_hints": ["hint1", "hint2"],
        }

        # Get context
        context = integration.get_context_for_prompt(plan)

        # Check that context contains expected elements
        assert "System prompt" in context
        assert "key1: value1" in context
        assert "hint1" in context
        assert "hint2" in context

        # Check that metrics were updated
        integration.metrics.update_layer_sizes.assert_called()

    @pytest.mark.asyncio
    async def test_create_session_snapshot(self):
        """Test creating session snapshot."""
        dfc = DFC()
        integration = DFCIntegration(dfc)

        # Add items to layers
        dfc.promote_to_hot("key1", "value1")
        dfc.warm["key2"] = "value2"

        # Mock cold item
        cold_item = Mock()
        cold_item.content_hash = "hash1"
        cold_item.summary = "summary1"
        cold_item.metadata = {"test": "data"}
        dfc.cold.append(cold_item)

        # Create snapshot
        snapshot = await integration.create_session_snapshot("session_1")

        # Check that snapshot contains expected data
        assert "hot" in snapshot
        assert "warm" in snapshot
        assert "cold" in snapshot
        assert "heat_cache_stats" in snapshot

        # Check HOT layer
        assert snapshot["hot"] == [["key1", "value1"]]

        # Check WARM layer
        assert snapshot["warm"] == [["key2", "value2"]]

        # Check COLD layer
        assert snapshot["cold"] == [
            {
                "content_hash": "hash1",
                "summary": "summary1",
                "metadata": {"test": "data"},
            }
        ]

        # Check metrics
        integration.metrics.observe_snapshot_duration.assert_called()

    def test_serialize_result(self):
        """Test result serialization."""
        dfc = DFC()
        integration = DFCIntegration(dfc)

        # Test dict-like object
        result = {"file": "test.py", "content": "# test"}
        serialized = integration._serialize_result(result)
        assert "file" in serialized
        assert "content" in serialized

        # Test object with to_dict method
        result = Mock()
        result.to_dict.return_value = {"file": "test.py"}
        serialized = integration._serialize_result(result)
        assert "file" in serialized

        # Test object with __dict__
        result = Mock()
        result.__dict__ = {"file": "test.py"}
        serialized = integration._serialize_result(result)
        assert "file" in serialized

        # Test simple object
        result = "simple string"
        serialized = integration._serialize_result(result)
        assert serialized == "simple string"

    def test_serialize_memory_item(self):
        """Test memory item serialization."""
        dfc = DFC()
        integration = DFCIntegration(dfc)

        # Test object with to_markdown method
        memory_item = Mock()
        memory_item.to_markdown.return_value = "# Memory content"
        serialized = integration._serialize_memory_item(memory_item)
        assert serialized == "# Memory content"

        # Test object with content
        memory_item = Mock()
        memory_item.content = "Memory content"
        serialized = integration._serialize_memory_item(memory_item)
        assert serialized == "Memory content"

        # Test simple object
        memory_item = "simple memory"
        serialized = integration._serialize_memory_item(memory_item)
        assert serialized == "simple memory"


class TestDFCIntegrationGlobal:
    """Test global DFC integration functions."""

    def test_get_dfc_integration(self):
        """Test getting global DFC integration."""
        # Reset global state
        import app.core.dfc.integration as integration_module

        integration_module._dfc_integration = None

        # Should raise error when not initialized
        with pytest.raises(RuntimeError, match="DFC not initialized"):
            get_dfc_integration()

    def test_initialize_dfc_integration(self):
        """Test initializing global DFC integration."""
        # Reset global state
        import app.core.dfc.integration as integration_module

        integration_module._dfc_integration = None

        # Initialize
        integration = initialize_dfc_integration()

        # Check that integration was created
        assert integration is not None
        assert integration_module._dfc_integration is integration

        # Check that global function returns the same instance
        assert get_dfc_integration() is integration
