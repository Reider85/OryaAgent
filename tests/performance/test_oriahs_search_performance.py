"""Performance tests for oriahs_search tool (B-02)."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.oriahs_search import oriahs_search


class TestOriaHSPerformance:
    """Performance tests for semantic search operations."""

    @pytest.mark.asyncio
    async def test_search_latency_target(self):
        """Test that search completes within target latency (<2s)."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            {
                "score": 0.95,
                "path": "app/main.py",
                "content": "def main(): pass",
                "type": "function",
            }
        ]

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            start_time = time.time()
            await oriahs_search.ainvoke({"query": "performance test"})
            latency = time.time() - start_time

            # Should complete within 2 seconds
            assert latency < 2.0, f"Search took {latency:.2f}s, target <2s"

    @pytest.mark.asyncio
    async def test_cache_hit_latency(self):
        """Test that cache hits are very fast (<100ms)."""
        # Mock cache
        mock_cache = AsyncMock()
        mock_cache.get.return_value = "cached result"

        with patch("app.tools.oriahs_search.get_cache", return_value=mock_cache):
            with patch("app.tools.oriahs_search.get_mcp_client") as mock_get_client:
                start_time = time.time()
                result = await oriahs_search.ainvoke({"query": "cache test"})
                latency = time.time() - start_time

                # Cache hits should be very fast
                assert latency < 0.1, f"Cache hit took {latency:.2f}s, target <100ms"
                assert result == "cached result"
                mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_concurrent_searches(self):
        """Test performance of concurrent searches."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            {
                "score": 0.95,
                "path": "app/test.py",
                "content": "def test(): pass",
                "type": "function",
            }
        ]

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            # Start multiple concurrent searches
            start_time = time.time()
            tasks = [oriahs_search.ainvoke({"query": f"test {i}"}) for i in range(5)]
            results = await asyncio.gather(*tasks)
            total_latency = time.time() - start_time

            # All searches should complete within 3 seconds total
            assert total_latency < 3.0, (
                f"Concurrent searches took {total_latency:.2f}s, target <3s"
            )

            # Verify all results are valid
            for result in results:
                assert "Score: 0.950" in result
                assert "app/test.py" in result

    @pytest.mark.asyncio
    async def test_large_result_set_performance(self):
        """Test performance with large result sets."""
        # Generate large result set
        large_results = []
        for i in range(100):  # 100 results
            large_results.append(
                {
                    "score": 0.95 - (i * 0.01),
                    "path": f"app/file_{i}.py",
                    "content": f"def function_{i}(): return {i}",
                    "type": "function",
                }
            )

        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = large_results

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            start_time = time.time()
            result = await oriahs_search.ainvoke({"query": "large test", "top_k": 100})
            latency = time.time() - start_time

            # Large result sets should still be reasonable
            assert latency < 1.0, f"Large result set took {latency:.2f}s, target <1s"

            # Verify all results are included
            assert "[1] Score: 0.950" in result
            assert "[100] Score: 0.050" in result
            assert "app/file_99.py" in result

    @pytest.mark.asyncio
    async def test_health_check_overhead(self):
        """Test that health check overhead is minimal."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            {
                "score": 0.95,
                "path": "app/test.py",
                "content": "def test(): pass",
                "type": "function",
            }
        ]

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            start_time = time.time()
            await oriahs_search.ainvoke({"query": "health check test"})
            latency = time.time() - start_time

            # Health check overhead should be minimal
            assert latency < 0.5, (
                f"Search with health check took {latency:.2f}s, target <500ms"
            )

            # Verify health check was called
            mock_client.health_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_handling_performance(self):
        """Test performance of error handling paths."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = False

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            start_time = time.time()
            with pytest.raises(Exception, match="not available"):
                await oriahs_search.ainvoke({"query": "error test"})
            latency = time.time() - start_time

            # Error handling should be fast
            assert latency < 0.1, f"Error handling took {latency:.2f}s, target <100ms"

    @pytest.mark.asyncio
    async def test_memory_usage_stability(self):
        """Test that memory usage remains stable across multiple searches."""
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            {
                "score": 0.95,
                "path": "app/test.py",
                "content": "def test(): pass",
                "type": "function",
            }
        ]

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            # Run multiple searches
            for i in range(10):
                await oriahs_search.ainvoke({"query": f"memory test {i}"})

            final_memory = process.memory_info().rss
            memory_increase = final_memory - initial_memory

            # Memory increase should be reasonable (< 10MB)
            assert memory_increase < 10 * 1024 * 1024, (
                f"Memory increased by {memory_increase / 1024 / 1024:.1f}MB"
            )

    @pytest.mark.asyncio
    async def test_timeout_protection(self):
        """Test that slow MCP calls don't hang indefinitely."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.side_effect = TimeoutError("Request timeout")

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            start_time = time.time()
            with pytest.raises(Exception, match="Search failed"):
                await oriahs_search.ainvoke({"query": "timeout test"})
            latency = time.time() - start_time

            # Should fail within timeout period
            assert latency < 1.0, f"Timeout handling took {latency:.2f}s, target <1s"
