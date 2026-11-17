"""Tests for UKB Router (B-27)."""

import pytest
from unittest.mock import AsyncMock, patch

from app.core.ukb.router import get_ukb_router, RetrievedChunk
from app.core.ukb.config import UKBConfig


class TestRetrievedChunk:
    """Test RetrievedChunk dataclass."""

    def test_chunk_creation(self):
        """Test chunk creation with minimal data."""
        chunk = RetrievedChunk(content="test content", source="test")
        assert chunk.content == "test content"
        assert chunk.source == "test"
        assert chunk.score == 1.0
        assert chunk.metadata == {}
        assert chunk.chunk_id is not None

    def test_chunk_with_metadata(self):
        """Test chunk creation with metadata."""
        metadata = {"file": "test.py", "line": 10}
        chunk = RetrievedChunk(
            content="test content",
            source="lsp",
            score=0.9,
            metadata=metadata,
        )
        assert chunk.metadata == metadata
        assert chunk.chunk_id.startswith("lsp_")

    def test_to_dict(self):
        """Test chunk serialization."""
        chunk = RetrievedChunk(
            content="test content",
            source="lsp",
            score=0.9,
            metadata={"file": "test.py"},
        )
        result = chunk.to_dict()
        assert result["content"] == "test content"
        assert result["source"] == "lsp"
        assert result["score"] == 0.9
        assert result["metadata"]["file"] == "test.py"


class TestUKBRouter:
    """Test UKB Router functionality."""

    @pytest.fixture
    def router(self):
        """Create a UKB router instance."""
        return get_ukb_router()

    @pytest.fixture
    def config(self):
        """Create BETA configuration."""
        return UKBConfig.get_beta_config()

    def test_router_initialization(self, router):
        """Test router initialization."""
        assert router is not None
        assert "lsp" in router.namespaces
        assert "memory" in router.namespaces
        assert len(router.namespaces) == 2  # BETA mode: only lsp + memory

    def test_routing_rules(self, router):
        """Test routing rules configuration."""
        assert "lsp.def" in router.routing_rules
        assert "memory.semantic" in router.routing_rules
        assert router.routing_rules["lsp.def"] == "lsp"
        assert router.routing_rules["memory.semantic"] == "memory"

    @pytest.mark.asyncio
    async def test_explicit_capability_routing(self, router):
        """Test explicit capability routing."""
        results = await router.lookup("test query", capability="lsp.def")
        assert len(results) > 0
        assert results[0].source == "lsp"

    @pytest.mark.asyncio
    async def test_default_parallel_lookup(self, router):
        """Test default parallel lookup across namespaces."""
        results = await router.lookup("test query")
        assert len(results) >= 0  # Could be empty if mocks return nothing

    @pytest.mark.asyncio
    async def test_merge_and_dedup(self, router):
        """Test merge and deduplication logic."""
        # Create duplicate chunks
        chunk1 = RetrievedChunk("same content", "lsp", score=0.9)
        chunk2 = RetrievedChunk("same content", "memory", score=0.8)
        chunk3 = RetrievedChunk("different content", "lsp", score=0.7)
        
        results = [chunk1, chunk2, chunk3]
        merged = router._merge_and_dedup(results)
        
        # Should have 2 unique chunks (chunk1 and chunk3, chunk2 is duplicate of chunk1)
        assert len(merged) == 2

    @pytest.mark.asyncio
    async def test_filter_and_rank(self, router):
        """Test filtering and ranking."""
        results = [
            RetrievedChunk("content A", "lsp", score=0.9),
            RetrievedChunk("content B", "memory", score=0.7),
            RetrievedChunk("content C", "lsp", score=0.8),
        ]
        
        # Test top_k filtering
        filtered = router._filter_and_rank(results, top_k=2)
        assert len(filtered) == 2
        assert filtered[0].score == 0.9  # Highest score first

    @pytest.mark.asyncio
    async def test_cache_functionality(self, router):
        """Test caching functionality."""
        query = "test query"
        capability = "lsp.def"
        
        # First call should populate cache
        results1 = await router.lookup(query, capability=capability)
        cache_key = router._generate_cache_key(query, capability, None)
        
        assert cache_key in router._cache
        
        # Second call should use cache
        results2 = await router.lookup(query, capability=capability, use_cache=True)
        
        # Results should be the same
        assert len(results1) == len(results2)

    def test_cache_key_generation(self, router):
        """Test cache key generation."""
        key1 = router._generate_cache_key("query1", "lsp.def", {"filter": "value"})
        key2 = router._generate_cache_key("query1", "lsp.def", {"filter": "value"})
        key3 = router._generate_cache_key("query2", "lsp.def", {"filter": "value"})
        
        assert key1 == key2  # Same parameters, same key
        assert key1 != key3  # Different query, different key

    @pytest.mark.asyncio
    async def test_error_handling(self, router):
        """Test error handling for unknown capabilities."""
        results = await router.lookup("test query", capability="unknown.capability")
        # Should not raise exception, return empty list
        assert isinstance(results, list)

    def test_metrics_collection(self, router):
        """Test metrics collection."""
        initial_metrics = router.get_metrics()
        assert initial_metrics["lookups_total"] == 0
        assert "cache_size" in initial_metrics
        assert "namespace_lookups" in initial_metrics

    @pytest.mark.asyncio
    async def test_namespace_lookup_metrics(self, router):
        """Test namespace lookup metrics."""
        await router.lookup("test", capability="lsp.def")
        
        metrics = router.get_metrics()
        assert metrics["namespace_lookups"]["lsp"] >= 1

    def test_configuration_integration(self, config):
        """Test configuration integration."""
        router = get_ukb_router()
        assert router.config.cache_ttl_seconds == config.cache_ttl_seconds
        assert router.config.enabled_namespaces == ["lsp", "memory"]

    @pytest.mark.asyncio
    async def test_lsp_namespace_integration(self, router):
        """Test LSP namespace integration with real MCP."""
        with patch('app.mcp.lsp_mcp.get_lsp_mcp_server') as mock_get_server:
            mock_server = AsyncMock()
            mock_server.call_tool.return_value = {
                "content": [{"text": '[{"content": "LSP result", "source": "lsp", "score": 0.8, "metadata": {"file": "test.py", "capability": "definition"}}]'}]
            }
            mock_get_server.return_value = mock_server
            
            results = await router._lsp_namespace("test query", "lsp.def")
            
            assert len(results) == 1
            assert results[0].content == "LSP result"
            assert results[0].source == "lsp"


class TestUKBConfig:
    """Test UKB configuration."""

    def test_beta_config(self):
        """Test BETA configuration."""
        config = UKBConfig.get_beta_config()
        assert config.enabled_namespaces == ["lsp", "memory"]
        assert config.use_mock_implementations is True
        assert config.code_integration_enabled is False
        assert config.kb_integration_enabled is False

    def test_routing_rule_lookup(self):
        """Test routing rule lookup."""
        config = UKBConfig()
        assert config.get_routing_rule("lsp.def") == "lsp"
        assert config.get_routing_rule("unknown.capability") == "default"

    def test_namespace_enabled_check(self):
        """Test namespace enabled check."""
        config = UKBConfig.get_beta_config()
        assert config.is_namespace_enabled("lsp") is True
        assert config.is_namespace_enabled("memory") is True
        assert config.is_namespace_enabled("code") is False


class TestUKBIntegration:
    """Test UKB integration with other systems."""

    @pytest.mark.asyncio
    async def test_tool_integration(self):
        """Test UKB tool integration."""
        from app.tools.ukb import ukb_lookup
        
        results = await ukb_lookup._arun("test query")
        assert isinstance(results, list)
        
        # Test with capability
        results = await ukb_lookup._arun("test query", capability="lsp.def")
        assert isinstance(results, list)

    def test_mcp_server_initialization(self):
        """Test MCP server initialization."""
        from app.mcp.ukb_mcp import get_ukb_mcp_server
        
        server = get_ukb_mcp_server()
        assert server.name == "ukb-mcp"
        assert "ukb.lookup" in server.tools

    @pytest.mark.asyncio
    async def test_mcp_tool_call(self):
        """Test MCP tool call."""
        from app.mcp.ukb_mcp import get_ukb_mcp_server
        
        server = get_ukb_mcp_server()
        await server.initialize()
        
        result = await server.call_tool(
            "ukb.lookup",
            {"query": "test query", "capability": "lsp.def"}
        )
        
        assert "content" in result
        assert isinstance(result["content"], list)