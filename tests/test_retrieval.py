"""Tests for RetrievalOrchestrator components."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

from app.core.retrieval.orchestrator import (
    get_retrieval_orchestrator,
    initialize_retrieval_orchestrator,
    RetrievalOrchestrator,
    RetrievalRequest,
    UKBRetrievalStrategy,
    SemanticRetrievalStrategy,
    LexicalRetrievalStrategy,
    HybridRetrievalStrategy,
)


class TestRetrievalRequest:
    """Test RetrievalRequest functionality."""

    def test_request_creation(self):
        """Test request creation."""
        request = RetrievalRequest(
            query="test query",
            capability="lsp.def",
            filters={"source": "lsp"},
            top_k=5,
            strategies=["ukb", "semantic"],
            context={"file_type": "py"},
        )

        assert request.query == "test query"
        assert request.capability == "lsp.def"
        assert request.filters == {"source": "lsp"}
        assert request.top_k == 5
        assert request.strategies == ["ukb", "semantic"]
        assert request.context == {"file_type": "py"}

    def test_request_defaults(self):
        """Test request with defaults."""
        request = RetrievalRequest("test query")

        assert request.query == "test query"
        assert request.capability is None
        assert request.filters == {}
        assert request.top_k == 5
        assert request.strategies == ["ukb", "semantic", "lexical"]
        assert request.context == {}


class TestRetrievalStrategy:
    """Test base RetrievalStrategy functionality."""

    def test_strategy_creation(self):
        """Test strategy creation."""
        strategy = UKBRetrievalStrategy()

        assert strategy.name == "ukb"
        assert hasattr(strategy, "retrieve")


class TestUKBRetrievalStrategy:
    """Test UKB retrieval strategy."""

    @pytest.mark.asyncio
    async def test_ukb_retrieval(self):
        """Test UKB retrieval strategy."""
        strategy = UKBRetrievalStrategy()

        # Mock UKB router
        mock_ukb = Mock()
        mock_ukb.lookup = AsyncMock(
            return_value=[Mock(content="test content", source="lsp", score=0.9)]
        )

        request = RetrievalRequest("test query", capability="lsp.def")
        results = await strategy.retrieve(request, mock_ukb)

        assert len(results) == 1
        assert results[0].content == "test content"
        assert results[0].source == "lsp"
        assert results[0].score == 0.9

        mock_ukb.lookup.assert_called_once_with(
            query="test query",
            capability="lsp.def",
            filters={},
            top_k=5,
            use_cache=True,
        )


class TestSemanticRetrievalStrategy:
    """Test semantic retrieval strategy."""

    @pytest.mark.asyncio
    async def test_semantic_retrieval(self):
        """Test semantic retrieval strategy."""
        strategy = SemanticRetrievalStrategy()

        # Mock UKB router
        mock_ukb = Mock()
        mock_ukb.lookup = AsyncMock(
            return_value=[Mock(content="semantic content", source="memory", score=0.8)]
        )

        request = RetrievalRequest("test query")
        results = await strategy.retrieve(request, mock_ukb)

        assert len(results) == 1
        assert results[0].content == "semantic content"
        assert results[0].source == "memory"
        assert results[0].score == 0.8

        mock_ukb.lookup.assert_called_once_with(
            query="test query",
            capability="memory.semantic",
            filters={},
            top_k=5,
            use_cache=True,
        )


class TestLexicalRetrievalStrategy:
    """Test lexical retrieval strategy."""

    @pytest.mark.asyncio
    async def test_lexical_retrieval(self):
        """Test lexical retrieval strategy."""
        strategy = LexicalRetrievalStrategy()

        # Mock UKB router
        mock_ukb = Mock()
        mock_ukb.lookup = AsyncMock(
            return_value=[Mock(content="lexical content", source="memory", score=0.7)]
        )

        request = RetrievalRequest("test query")
        results = await strategy.retrieve(request, mock_ukb)

        assert len(results) == 1
        assert results[0].content == "lexical content"
        assert results[0].source == "memory"
        assert results[0].score == 0.7

        mock_ukb.lookup.assert_called_once_with(
            query="test query",
            capability="memory.lexical",
            filters={},
            top_k=5,
            use_cache=True,
        )


class TestHybridRetrievalStrategy:
    """Test hybrid retrieval strategy."""

    @pytest.mark.asyncio
    async def test_hybrid_retrieval(self):
        """Test hybrid retrieval strategy."""
        # Create mock strategies
        ukb_strategy = Mock()
        ukb_strategy.name = "ukb"
        ukb_strategy.retrieve = AsyncMock(
            return_value=[
                Mock(content="ukb content", source="lsp", score=0.9, chunk_id="ukb_123")
            ]
        )

        semantic_strategy = Mock()
        semantic_strategy.name = "semantic"
        semantic_strategy.retrieve = AsyncMock(
            return_value=[
                Mock(
                    content="semantic content",
                    source="memory",
                    score=0.8,
                    chunk_id="semantic_456",
                )
            ]
        )

        lexical_strategy = Mock()
        lexical_strategy.name = "lexical"
        lexical_strategy.retrieve = AsyncMock(
            return_value=[
                Mock(
                    content="lexical content",
                    source="memory",
                    score=0.7,
                    chunk_id="lexical_789",
                )
            ]
        )

        strategy = HybridRetrievalStrategy(
            [ukb_strategy, semantic_strategy, lexical_strategy]
        )

        request = RetrievalRequest("test query", top_k=3)
        results = await strategy.retrieve(request, Mock())

        assert len(results) == 3
        # Should be sorted by score
        assert results[0].score == 0.9
        assert results[1].score == 0.8
        assert results[2].score == 0.7

        # All strategies should be called
        ukb_strategy.retrieve.assert_called_once()
        semantic_strategy.retrieve.assert_called_once()
        lexical_strategy.retrieve.assert_called_once()

    @pytest.mark.asyncio
    async def test_hybrid_retrieval_with_errors(self):
        """Test hybrid retrieval with strategy errors."""
        # Create strategies with one error
        ukb_strategy = Mock()
        ukb_strategy.name = "ukb"
        ukb_strategy.retrieve = AsyncMock(
            return_value=[
                Mock(content="ukb content", source="lsp", score=0.9, chunk_id="ukb_123")
            ]
        )

        error_strategy = Mock()
        error_strategy.name = "error"
        error_strategy.retrieve = AsyncMock(side_effect=Exception("Test error"))

        strategy = HybridRetrievalStrategy([ukb_strategy, error_strategy])

        request = RetrievalRequest("test query")
        results = await strategy.retrieve(request, Mock())

        # Should still return results from successful strategies
        assert len(results) == 1
        assert results[0].content == "ukb content"


class TestRetrievalOrchestrator:
    """Test RetrievalOrchestrator functionality."""

    def test_orchestrator_creation(self):
        """Test orchestrator creation."""
        orchestrator = RetrievalOrchestrator()

        assert len(orchestrator.strategies) == 4
        assert "ukb" in orchestrator.strategies
        assert "semantic" in orchestrator.strategies
        assert "lexical" in orchestrator.strategies
        assert "hybrid" in orchestrator.strategies

        assert len(orchestrator.strategy_rules) > 0
        assert "lsp.def" in orchestrator.strategy_rules
        assert "memory.semantic" in orchestrator.strategy_rules
        assert "code.search" in orchestrator.strategy_rules
        assert "kb.fact" in orchestrator.strategy_rules

        assert len(orchestrator._cache) == 0

    @pytest.mark.asyncio
    async def test_retrieve_with_explicit_strategies(self):
        """Test retrieve with explicit strategies."""
        orchestrator = RetrievalOrchestrator()

        # Mock UKB router
        with patch.object(orchestrator, "ukb_router") as mock_ukb:
            mock_ukb.lookup = AsyncMock(
                return_value=[
                    Mock(
                        content="test content",
                        source="lsp",
                        score=0.9,
                        chunk_id="test_123",
                    )
                ]
            )

            result = await orchestrator.retrieve(
                query="test query",
                capability="lsp.def",
                strategies=["ukb"],
                top_k=3,
            )

            assert len(result) == 1
            assert result[0].content == "test content"

            # Should use only ukb strategy
            mock_ukb.lookup.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_with_default_strategies(self):
        """Test retrieve with default strategies."""
        orchestrator = RetrievalOrchestrator()

        # Mock UKB router
        with patch.object(orchestrator, "ukb_router") as mock_ukb:
            mock_ukb.lookup = AsyncMock(
                return_value=[
                    Mock(
                        content="test content",
                        source="lsp",
                        score=0.9,
                        chunk_id="test_123",
                    )
                ]
            )

            result = await orchestrator.retrieve(
                query="test query",
                capability="lsp.def",
                top_k=3,
            )

            assert len(result) == 1
            assert result[0].content == "test content"

            # Should use default strategies for capability
            assert mock_ukb.lookup.call_count == 1

    @pytest.mark.asyncio
    async def test_retrieve_with_context_scoring(self):
        """Test retrieve with context-aware scoring."""
        orchestrator = RetrievalOrchestrator()

        # Mock UKB router
        with patch.object(orchestrator, "ukb_router") as mock_ukb:
            mock_ukb.lookup = AsyncMock(
                return_value=[
                    Mock(
                        content="content1",
                        source="python",
                        score=0.8,
                        chunk_id="python_123",
                    ),
                    Mock(
                        content="content2",
                        source="typescript",
                        score=0.7,
                        chunk_id="ts_456",
                    ),
                ]
            )

            result = await orchestrator.retrieve(
                query="test query",
                context={"language": "python"},
                top_k=3,
            )

            assert len(result) == 2
            # Python content should be boosted
            assert result[0].score > 0.8  # Boosted from 0.8
            assert result[1].score == 0.7

    @pytest.mark.asyncio
    async def test_retrieve_with_filters(self):
        """Test retrieve with filters."""
        orchestrator = RetrievalOrchestrator()

        # Mock UKB router
        with patch.object(orchestrator, "ukb_router") as mock_ukb:
            mock_ukb.lookup = AsyncMock(
                return_value=[
                    Mock(
                        content="content1", source="lsp", score=0.9, chunk_id="lsp_123"
                    ),
                    Mock(
                        content="content2",
                        source="memory",
                        score=0.8,
                        chunk_id="mem_456",
                    ),
                    Mock(
                        content="content3", source="lsp", score=0.7, chunk_id="lsp_789"
                    ),
                ]
            )

            result = await orchestrator.retrieve(
                query="test query",
                filters={"source": "lsp", "min_score": 0.8},
                top_k=3,
            )

            assert len(result) == 2
            assert all(r.source == "lsp" for r in result)
            assert all(r.score >= 0.8 for r in result)

    @pytest.mark.asyncio
    async def test_retrieve_with_cache(self):
        """Test retrieve with caching."""
        orchestrator = RetrievalOrchestrator()

        # Mock UKB router
        with patch.object(orchestrator, "ukb_router") as mock_ukb:
            mock_ukb.lookup = AsyncMock(
                return_value=[
                    Mock(
                        content="test content",
                        source="lsp",
                        score=0.9,
                        chunk_id="test_123",
                    )
                ]
            )

            # First call
            result1 = await orchestrator.retrieve(
                query="test query",
                use_cache=True,
            )

            # Second call should use cache
            result2 = await orchestrator.retrieve(
                query="test query",
                use_cache=True,
            )

            assert len(result1) == len(result2) == 1
            assert result1[0].content == result2[0].content

            # UKB router should only be called once
            mock_ukb.lookup.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_without_cache(self):
        """Test retrieve without caching."""
        orchestrator = RetrievalOrchestrator()

        # Mock UKB router
        with patch.object(orchestrator, "ukb_router") as mock_ukb:
            mock_ukb.lookup = AsyncMock(
                return_value=[
                    Mock(
                        content="test content",
                        source="lsp",
                        score=0.9,
                        chunk_id="test_123",
                    )
                ]
            )

            # First call
            result1 = await orchestrator.retrieve(
                query="test query",
                use_cache=False,
            )

            # Second call should not use cache
            result2 = await orchestrator.retrieve(
                query="test query",
                use_cache=False,
            )

            assert len(result1) == len(result2) == 1
            assert result1[0].content == result2[0].content

            # UKB router should be called twice
            assert mock_ukb.lookup.call_count == 2

    @pytest.mark.asyncio
    async def test_retrieve_error_handling(self):
        """Test retrieve error handling."""
        orchestrator = RetrievalOrchestrator()

        # Mock UKB router to raise error
        with patch.object(orchestrator, "ukb_router") as mock_ukb:
            mock_ukb.lookup = AsyncMock(side_effect=Exception("Test error"))

            result = await orchestrator.retrieve(
                query="test query",
                strategies=["ukb"],
            )

            # Should return empty list on error
            assert len(result) == 0

    def test_select_strategies(self):
        """Test strategy selection."""
        orchestrator = RetrievalOrchestrator()

        # Test capability-based selection
        strategies = orchestrator._select_strategies("lsp.def")
        assert "ukb" in strategies

        strategies = orchestrator._select_strategies("memory.semantic")
        assert "semantic" in strategies

        strategies = orchestrator._select_strategies("code.search")
        assert "hybrid" in strategies

        # Test default selection
        strategies = orchestrator._select_strategies(None)
        assert "hybrid" in strategies

        strategies = orchestrator._select_strategies("unknown")
        assert "hybrid" in strategies

    def test_strategy_management(self):
        """Test strategy management."""
        orchestrator = RetrievalOrchestrator()

        # Add new strategy
        new_strategy = Mock()
        new_strategy.name = "test"
        orchestrator.add_strategy("test", new_strategy)

        assert "test" in orchestrator.strategies
        assert orchestrator.strategies["test"] == new_strategy

        # Remove strategy
        orchestrator.remove_strategy("test")

        assert "test" not in orchestrator.strategies

    def test_get_available_strategies(self):
        """Test getting available strategies."""
        orchestrator = RetrievalOrchestrator()

        strategies = orchestrator.get_available_strategies()

        assert len(strategies) == 4
        assert "ukb" in strategies
        assert "semantic" in strategies
        assert "lexical" in strategies
        assert "hybrid" in strategies

    def test_get_supported_capabilities(self):
        """Test getting supported capabilities."""
        orchestrator = RetrievalOrchestrator()

        capabilities = orchestrator.get_supported_capabilities()

        assert len(capabilities) > 0
        assert "lsp.def" in capabilities
        assert "memory.semantic" in capabilities
        assert "code.search" in capabilities
        assert "kb.fact" in capabilities
        assert "default" in capabilities

    def test_cache_management(self):
        """Test cache management."""
        orchestrator = RetrievalOrchestrator()

        # Add some cache entries
        orchestrator._cache["key1"] = [Mock(content="content1", source="lsp")]
        orchestrator._cache["key2"] = [Mock(content="content2", source="memory")]

        assert len(orchestrator._cache) == 2

        # Clear cache
        orchestrator.clear_cache()
        assert len(orchestrator._cache) == 0

        # Get cache stats
        stats = orchestrator.get_cache_stats()
        assert stats["cache_size"] == 0
        assert stats["cache_keys"] == []

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test orchestrator health check."""
        orchestrator = RetrievalOrchestrator()

        # Mock UKB router
        with patch.object(orchestrator, "ukb_router") as mock_ukb:
            mock_ukb.lookup = AsyncMock(
                return_value=[
                    Mock(
                        content="test content",
                        source="lsp",
                        score=0.9,
                        chunk_id="test_123",
                    )
                ]
            )

            health = await orchestrator.health_check()

            assert health["status"] == "healthy"
            assert "ukb_router" in health
            assert "strategies" in health
            assert "cache_size" in health


class TestGlobalRetrievalOrchestrator:
    """Test global retrieval orchestrator functions."""

    def test_get_retrieval_orchestrator(self):
        """Test getting retrieval orchestrator instance."""
        orchestrator1 = get_retrieval_orchestrator()
        orchestrator2 = get_retrieval_orchestrator()

        assert orchestrator1 is orchestrator2
        assert isinstance(orchestrator1, RetrievalOrchestrator)

    def test_initialize_retrieval_orchestrator(self):
        """Test initializing retrieval orchestrator."""
        orchestrator = initialize_retrieval_orchestrator()

        assert isinstance(orchestrator, RetrievalOrchestrator)
        assert len(orchestrator.strategies) == 4
        assert len(orchestrator.strategy_rules) > 0
