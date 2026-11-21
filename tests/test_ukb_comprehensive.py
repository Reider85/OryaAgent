"""Comprehensive tests for UKB Router (B-27) - Performance & Integration Tests."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.ukb.config import UKBConfig
from app.core.ukb.router import RetrievedChunk, get_ukb_router
from app.tools.ukb import ukb_lookup


class TestUKBPerformance:
    """Test UKB performance and metrics."""

    @pytest.fixture
    def router(self):
        """Create a UKB router instance."""
        return get_ukb_router()

    @pytest.mark.asyncio
    async def test_cache_performance(self, router):
        """Test cache performance improvements."""
        query = "performance_test"

        # First call (cache miss)
        start_time = time.time()
        await router.lookup(query)
        first_call_time = time.time() - start_time

        # Second call (cache hit)
        start_time = time.time()
        await router.lookup(query, use_cache=True)
        second_call_time = time.time() - start_time

        # Cache hit should be significantly faster
        assert second_call_time < first_call_time

        # Verify cache stats
        metrics = router.get_metrics()
        assert metrics["cache_size"] > 0
        assert metrics["cache_hit_rate"] > 0

    @pytest.mark.asyncio
    async def test_concurrent_lookups(self, router):
        """Test concurrent lookup performance."""
        queries = [f"query_{i}" for i in range(10)]

        start_time = time.time()
        tasks = [router.lookup(query) for query in queries]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # All lookups should complete successfully
        assert len(results) == 10
        assert all(isinstance(r, list) for r in results)

        # Should be fast due to concurrent execution
        assert total_time < 2.0  # Should complete in under 2 seconds

    @pytest.mark.asyncio
    async def test_memory_usage(self, router):
        """Test memory usage with multiple lookups."""
        initial_cache_size = len(router._cache)

        # Perform multiple lookups to populate cache
        for i in range(20):
            await router.lookup(f"memory_test_{i}")

        # Cache should grow but remain reasonable
        final_cache_size = len(router._cache)
        assert final_cache_size > initial_cache_size
        assert final_cache_size < 100  # Should not grow unboundedly

    def test_metrics_collection(self, router):
        """Test metrics collection accuracy."""
        initial_metrics = router.get_metrics()

        # Simulate some lookups
        asyncio.run(router.lookup("test1"))
        asyncio.run(router.lookup("test2"))

        final_metrics = router.get_metrics()

        # Metrics should be updated
        assert final_metrics["lookups_total"] > initial_metrics["lookups_total"]
        assert "namespace_lookups" in final_metrics


class TestUKBIntegration:
    """Test UKB integration with other systems."""

    @pytest.mark.asyncio
    async def test_tool_registry_integration(self):
        """Test UKB tool integration with tool registry."""
        from app.core.tools import get_tools

        tools = get_tools()
        tool_names = [tool.name for tool in tools]

        assert "ukb_lookup" in tool_names
        assert len(tool_names) >= 13  # Should include all existing tools + ukb_lookup

    @pytest.mark.asyncio
    async def test_lsp_integration_mock(self):
        """Test LSP integration with mock data."""

        # Mock the LSP server
        with patch("app.mcp.lsp_mcp.get_lsp_mcp_server") as mock_get_server:
            mock_server = MagicMock()
            mock_server.call_tool.return_value = {
                "content": [{"text": '[{"content": "Mock LSP result", "score": 0.9}]'}]
            }
            mock_get_server.return_value = mock_server

            router = get_ukb_router()
            results = await router._lsp_namespace("test_query", "lsp.def")

            assert len(results) == 1
            assert "Mock LSP result" in results[0].content

    @pytest.mark.asyncio
    async def test_memory_integration_mock(self):
        """Test memory integration with mock data."""
        router = get_ukb_router()
        results = await router._memory_namespace("test_query", "memory.semantic")

        assert len(results) == 1
        assert results[0].source == "memory"
        assert results[0].score > 0.5

    def test_configuration_system(self):
        """Test configuration system."""
        config = UKBConfig.get_beta_config()

        assert config.enabled_namespaces == ["lsp", "memory"]
        assert config.use_mock_implementations is True
        assert config.cache_ttl_seconds == 300
        assert config.is_namespace_enabled("lsp") is True
        assert config.is_namespace_enabled("code") is False

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test error handling for various scenarios."""
        router = get_ukb_router()

        # Empty query
        results = await router.lookup("")
        assert isinstance(results, list)

        # Unknown capability
        results = await router.lookup("test", capability="unknown.capability")
        assert isinstance(results, list)

        # Invalid namespace (should not crash)
        results = await router.lookup("test", capability="invalid_namespace.def")
        assert isinstance(results, list)


class TestUKBEdgeCases:
    """Test UKB edge cases and error scenarios."""

    @pytest.mark.asyncio
    async def test_duplicate_content_handling(self):
        """Test handling of duplicate content across namespaces."""
        router = get_ukb_router()

        # Create duplicate chunks
        chunk1 = RetrievedChunk("same content", "lsp", score=0.9)
        chunk2 = RetrievedChunk("same content", "memory", score=0.8)

        results = [chunk1, chunk2]
        merged = router._merge_and_dedup(results)

        # Should have only one unique chunk
        assert len(merged) == 1
        assert merged[0].content == "same content"

    @pytest.mark.asyncio
    async def test_top_k_filtering(self):
        """Test top_k filtering functionality."""
        router = get_ukb_router()

        # Create results with varying scores
        results = [
            RetrievedChunk("high priority", "test", score=0.9),
            RetrievedChunk("medium priority", "test", score=0.7),
            RetrievedChunk("low priority", "test", score=0.5),
            RetrievedChunk("lowest priority", "test", score=0.3),
        ]

        # Test top_k=2
        filtered = router._filter_and_rank(results, top_k=2)
        assert len(filtered) == 2
        assert filtered[0].score == 0.9  # Highest score first
        assert filtered[1].score == 0.7

    @pytest.mark.asyncio
    async def test_cache_key_generation(self):
        """Test cache key generation uniqueness."""
        router = get_ukb_router()

        # Different queries should generate different keys
        key1 = router._generate_cache_key("query1", "lsp.def", {"filter": "value"})
        key2 = router._generate_cache_key("query2", "lsp.def", {"filter": "value"})
        assert key1 != key2

        # Same queries should generate same keys
        key3 = router._generate_cache_key("query1", "lsp.def", {"filter": "value"})
        assert key1 == key3

    def test_cache_management(self):
        """Test cache management functions."""
        router = get_ukb_router()

        # Initially cache should be empty
        assert len(router._cache) == 0

        # Add some cache entries
        router._cache["test"] = [RetrievedChunk("test content", "test")]

        # Verify cache stats
        stats = router.get_cache_stats()
        assert stats["cache_size"] == 1
        assert "test" in stats["cache_keys"]

        # Clear cache
        router.clear_cache()
        assert len(router._cache) == 0


class TestUKBToolInterface:
    """Test UKB tool interface and user experience."""

    @pytest.mark.asyncio
    async def test_tool_basic_functionality(self):
        """Test basic tool functionality."""
        # Test with valid query
        results = await ukb_lookup._arun("test query")
        assert isinstance(results, list)

        # Test with capability
        results = await ukb_lookup._arun("test query", capability="lsp.def")
        assert isinstance(results, list)

        # Test with top_k
        results = await ukb_lookup._arun("test query", top_k=3)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_tool_error_handling(self):
        """Test tool error handling."""
        # Test with empty query
        results = await ukb_lookup._arun("")
        assert isinstance(results, list)

        # Test with None query (should be handled gracefully)
        results = await ukb_lookup._arun(None)
        assert isinstance(results, list)

    def test_tool_schema(self):
        """Test tool schema and interface."""
        assert ukb_lookup.name == "ukb_lookup"
        assert "Unified knowledge bus" in ukb_lookup.description
        assert "capability" in str(ukb_lookup.args_schema)
        assert "top_k" in str(ukb_lookup.args_schema)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
