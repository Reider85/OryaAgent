"""Tests for UKB Router components."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

from app.core.ukb.router import (
    get_ukb_router, 
    initialize_ukb_router,
    UKBRouter,
    RetrievedChunk,
)


class TestRetrievedChunk:
    """Test RetrievedChunk functionality."""
    
    def test_chunk_creation(self):
        """Test chunk creation."""
        chunk = RetrievedChunk(
            content="test content",
            source="test",
            score=0.8,
            metadata={"key": "value"},
        )
        
        assert chunk.content == "test content"
        assert chunk.source == "test"
        assert chunk.score == 0.8
        assert chunk.metadata == {"key": "value"}
        assert chunk.chunk_id is not None
        assert len(chunk.chunk_id) > 0
    
    def test_chunk_id_generation(self):
        """Test chunk ID generation."""
        chunk1 = RetrievedChunk("content1", "source1")
        chunk2 = RetrievedChunk("content2", "source1")
        chunk3 = RetrievedChunk("content1", "source2")
        
        # Same content from same source should have same ID
        assert chunk1.chunk_id == chunk1.chunk_id
        
        # Different content should have different IDs
        assert chunk1.chunk_id != chunk2.chunk_id
        
        # Same content from different source should have different IDs
        assert chunk1.chunk_id != chunk3.chunk_id
    
    def test_to_dict(self):
        """Test chunk to dictionary conversion."""
        chunk = RetrievedChunk(
            content="test content",
            source="test",
            score=0.8,
            metadata={"key": "value"},
        )
        
        result = chunk.to_dict()
        
        assert result["content"] == "test content"
        assert result["source"] == "test"
        assert result["score"] == 0.8
        assert result["metadata"] == {"key": "value"}
        assert result["chunk_id"] == chunk.chunk_id


class TestUKBRouter:
    """Test UKB Router functionality."""
    
    def test_router_creation(self):
        """Test router creation."""
        router = UKBRouter()
        
        assert len(router.namespaces) == 4
        assert "lsp" in router.namespaces
        assert "memory" in router.namespaces
        assert "code" in router.namespaces
        assert "kb" in router.namespaces
        
        assert len(router.routing_rules) > 0
        assert "lsp.def" in router.routing_rules
        assert "memory.semantic" in router.routing_rules
        assert "code.search" in router.routing_rules
        assert "kb.fact" in router.routing_rules
        
        assert len(router._cache) == 0
    
    @pytest.mark.asyncio
    async def test_lookup_with_capability(self):
        """Test lookup with specific capability."""
        router = UKBRouter()
        
        # Mock LSP namespace
        with patch.object(router, '_lsp_namespace') as mock_lsp:
            mock_lsp.return_value = [
                RetrievedChunk("def content", "lsp", 0.9),
                RetrievedChunk("hover content", "lsp", 0.8),
            ]
            
            result = await router.lookup(
                query="test",
                capability="lsp.def",
                top_k=1,
            )
            
            assert len(result) == 1
            assert result[0].content == "def content"
            assert result[0].source == "lsp"
            assert result[0].score == 0.9
            mock_lsp.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_lookup_without_capability(self):
        """Test lookup without specific capability."""
        router = UKBRouter()
        
        # Mock all namespaces
        with patch.object(router, '_lsp_namespace') as mock_lsp, \
             patch.object(router, '_memory_namespace') as mock_memory, \
             patch.object(router, '_code_namespace') as mock_code, \
             patch.object(router, '_kb_namespace') as mock_kb:
            
            mock_lsp.return_value = [RetrievedChunk("lsp content", "lsp", 0.9)]
            mock_memory.return_value = [RetrievedChunk("memory content", "memory", 0.8)]
            mock_code.return_value = [RetrievedChunk("code content", "code", 0.7)]
            mock_kb.return_value = [RetrievedChunk("kb content", "kb", 0.6)]
            
            result = await router.lookup(
                query="test",
                top_k=3,
            )
            
            assert len(result) == 3
            # Results should be sorted by score
            assert result[0].score == 0.9
            assert result[1].score == 0.8
            assert result[2].score == 0.7
            
            # All namespaces should be called
            mock_lsp.assert_called_once()
            mock_memory.assert_called_once()
            mock_code.assert_called_once()
            mock_kb.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_lookup_with_filters(self):
        """Test lookup with filters."""
        router = UKBRouter()
        
        with patch.object(router, '_lsp_namespace') as mock_lsp:
            mock_lsp.return_value = [
                RetrievedChunk("content1", "lsp", 0.9),
                RetrievedChunk("content2", "memory", 0.8),
                RetrievedChunk("content3", "lsp", 0.7),
            ]
            
            result = await router.lookup(
                query="test",
                capability="lsp.def",
                filters={"source": "lsp", "min_score": 0.8},
                top_k=10,
            )
            
            assert len(result) == 1
            assert result[0].source == "lsp"
            assert result[0].score == 0.9
    
    @pytest.mark.asyncio
    async def test_lookup_cache(self):
        """Test lookup caching."""
        router = UKBRouter()
        
        with patch.object(router, '_lsp_namespace') as mock_lsp:
            mock_lsp.return_value = [RetrievedChunk("content", "lsp", 0.9)]
            
            # First call
            result1 = await router.lookup(
                query="test",
                capability="lsp.def",
                use_cache=True,
            )
            
            # Second call should use cache
            result2 = await router.lookup(
                query="test",
                capability="lsp.def",
                use_cache=True,
            )
            
            # Should be same result
            assert len(result1) == len(result2) == 1
            
            # LSP namespace should only be called once
            mock_lsp.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_lookup_no_cache(self):
        """Test lookup without caching."""
        router = UKBRouter()
        
        with patch.object(router, '_lsp_namespace') as mock_lsp:
            mock_lsp.return_value = [RetrievedChunk("content", "lsp", 0.9)]
            
            # First call
            result1 = await router.lookup(
                query="test",
                capability="lsp.def",
                use_cache=False,
            )
            
            # Second call should not use cache
            result2 = await router.lookup(
                query="test",
                capability="lsp.def",
                use_cache=False,
            )
            
            # Should be same result
            assert len(result1) == len(result2) == 1
            
            # LSP namespace should be called twice
            assert mock_lsp.call_count == 2
    
    @pytest.mark.asyncio
    async def test_lookup_error_handling(self):
        """Test lookup error handling."""
        router = UKBRouter()
        
        # Mock namespace to raise error
        with patch.object(router, '_lsp_namespace') as mock_lsp:
            mock_lsp.side_effect = Exception("Test error")
            
            with patch.object(router, '_memory_namespace') as mock_memory:
                mock_memory.return_value = [RetrievedChunk("memory content", "memory", 0.8)]
                
                result = await router.lookup(
                    query="test",
                    capability="lsp.def",
                )
                
                # Should return memory results despite LSP error
                assert len(result) == 1
                assert result[0].source == "memory"
    
    @pytest.mark.asyncio
    async def test_lsp_namespace(self):
        """Test LSP namespace lookup."""
        router = UKBRouter()
        
        # Test different capabilities
        result_def = await router._lsp_namespace("test", "lsp.def")
        assert len(result_def) == 1
        assert "definition" in result_def[0].metadata["capability"]
        
        result_hover = await router._lsp_namespace("test", "lsp.hover")
        assert len(result_hover) == 1
        assert "hover" in result_hover[0].metadata["capability"]
        
        result_refs = await router._lsp_namespace("test", "lsp.refs")
        assert len(result_refs) == 1
        assert "reference" in result_refs[0].metadata["capability"]
        
        result_symbol = await router._lsp_namespace("test", "lsp.symbol_search")
        assert len(result_symbol) == 1
        assert "symbol" in result_symbol[0].metadata["capability"]
        
        result_general = await router._lsp_namespace("test", None)
        assert len(result_general) == 1
        assert result_general[0].source == "lsp"
    
    @pytest.mark.asyncio
    async def test_memory_namespace(self):
        """Test memory namespace lookup."""
        router = UKBRouter()
        
        # Test different capabilities
        result_semantic = await router._memory_namespace("test", "memory.semantic")
        assert len(result_semantic) == 1
        assert result_semantic[0].metadata["type"] == "semantic"
        
        result_lexical = await router._memory_namespace("test", "memory.lexical")
        assert len(result_lexical) == 1
        assert result_lexical[0].metadata["type"] == "lexical"
        
        result_general = await router._memory_namespace("test", None)
        assert len(result_general) == 1
        assert result_general[0].source == "memory"
    
    @pytest.mark.asyncio
    async def test_code_namespace(self):
        """Test code namespace lookup."""
        router = UKBRouter()
        
        result = await router._code_namespace("test", None)
        assert len(result) == 1
        assert result[0].source == "code"
        assert "pattern" in result[0].metadata["capability"]
    
    @pytest.mark.asyncio
    async def test_kb_namespace(self):
        """Test KB namespace lookup."""
        router = UKBRouter()
        
        result = await router._kb_namespace("test", None)
        assert len(result) == 1
        assert result[0].source == "kb"
        assert result[0].metadata["type"] == "fact"
    
    def test_merge_and_dedup(self):
        """Test result merging and deduplication."""
        router = UKBRouter()
        
        results = [
            RetrievedChunk("content1", "source1", 0.9),
            RetrievedChunk("content2", "source1", 0.8),
            RetrievedChunk("content1", "source1", 0.9),  # Duplicate
            RetrievedChunk("content3", "source2", 0.7),
        ]
        
        merged = router._merge_and_dedup(results)
        
        assert len(merged) == 3
        # Should preserve highest score for duplicates
        assert merged[0].score == 0.9
        assert merged[1].score == 0.8
        assert merged[2].score == 0.7
    
    def test_filter_and_rank(self):
        """Test result filtering and ranking."""
        router = UKBRouter()
        
        results = [
            RetrievedChunk("content1", "source1", 0.9),
            RetrievedChunk("content2", "source2", 0.8),
            RetrievedChunk("content3", "source1", 0.7),
        ]
        
        # Test filtering
        filtered = router._filter_and_rank(results, {"source": "source1"})
        assert len(filtered) == 2
        assert all(r.source == "source1" for r in filtered)
        
        # Test ranking
        ranked = router._filter_and_rank(results, top_k=2)
        assert len(ranked) == 2
        assert ranked[0].score == 0.9
        assert ranked[1].score == 0.8
    
    def test_cache_management(self):
        """Test cache management."""
        router = UKBRouter()
        
        # Add some cache entries
        router._cache["key1"] = [RetrievedChunk("content1", "source1")]
        router._cache["key2"] = [RetrievedChunk("content2", "source2")]
        
        assert len(router._cache) == 2
        
        # Clear cache
        router.clear_cache()
        assert len(router._cache) == 0
        
        # Get cache stats
        stats = router.get_cache_stats()
        assert stats["cache_size"] == 0
        assert stats["cache_keys"] == []
    
    def test_supported_namespaces(self):
        """Test getting supported namespaces."""
        router = UKBRouter()
        
        namespaces = router.get_supported_namespaces()
        assert len(namespaces) == 4
        assert "lsp" in namespaces
        assert "memory" in namespaces
        assert "code" in namespaces
        assert "kb" in namespaces
    
    def test_supported_capabilities(self):
        """Test getting supported capabilities."""
        router = UKBRouter()
        
        capabilities = router.get_supported_capabilities()
        assert len(capabilities) > 0
        assert "lsp.def" in capabilities
        assert "memory.semantic" in capabilities
        assert "code.search" in capabilities
        assert "kb.fact" in capabilities
    
    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test router health check."""
        router = UKBRouter()
        
        health = await router.health_check()
        
        assert "status" in health
        assert "supported_languages" in health
        assert "running_servers" in health
        assert "total_tools" in health


class TestGlobalUKBRouter:
    """Test global UKB router functions."""
    
    def test_get_ukb_router(self):
        """Test getting UKB router instance."""
        router1 = get_ukb_router()
        router2 = get_ukb_router()
        
        assert router1 is router2
        assert isinstance(router1, UKBRouter)
    
    def test_initialize_ukb_router(self):
        """Test initializing UKB router."""
        router = initialize_ukb_router()
        
        assert isinstance(router, UKBRouter)
        assert len(router.namespaces) == 4
        assert len(router.routing_rules) > 0