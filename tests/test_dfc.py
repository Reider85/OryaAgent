"""Tests for DFC (Document-based File Cache) components."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
import tempfile
import os

from app.core.dfc.dfc import (
    get_dfc,
    initialize_dfc,
    DFC,
    DFCLayer,
    HeatLayer,
    HotLayer,
    WarmLayer,
    ColdLayer,
    IceLayer,
    BackgroundCompactor,
    Document,
    DocumentMetadata,
    CacheEntry,
    CacheStats,
)


class TestDocument:
    """Test Document functionality."""
    
    def test_document_creation(self):
        """Test document creation."""
        metadata = DocumentMetadata(
            source="test.py",
            size=1024,
            access_time=1234567890,
            create_time=1234567890,
            modify_time=1234567890,
            language="python",
            tags=["test", "python"],
        )
        
        doc = Document(
            content="def test():\n    pass",
            metadata=metadata,
        )
        
        assert doc.content == "def test():\n    pass"
        assert doc.metadata == metadata
        assert doc.id is not None
        assert len(doc.id) > 0
    
    def test_document_id_generation(self):
        """Test document ID generation."""
        metadata1 = DocumentMetadata(source="test1.py")
        metadata2 = DocumentMetadata(source="test2.py")
        
        doc1 = Document("content1", metadata1)
        doc2 = Document("content2", metadata2)
        
        # Different content should have different IDs
        assert doc1.id != doc2.id
        
        # Same content should have same ID
        doc3 = Document("content1", metadata1)
        assert doc1.id == doc3.id
    
    def test_document_to_dict(self):
        """Test document to dictionary conversion."""
        metadata = DocumentMetadata(
            source="test.py",
            size=1024,
            access_time=1234567890,
        )
        
        doc = Document(
            content="def test():\n    pass",
            metadata=metadata,
        )
        
        result = doc.to_dict()
        
        assert result["content"] == "def test():\n    pass"
        assert result["metadata"]["source"] == "test.py"
        assert result["metadata"]["size"] == 1024
        assert result["metadata"]["access_time"] == 1234567890
        assert result["id"] == doc.id


class TestDocumentMetadata:
    """Test DocumentMetadata functionality."""
    
    def test_metadata_creation(self):
        """Test metadata creation."""
        metadata = DocumentMetadata(
            source="test.py",
            size=1024,
            access_time=1234567890,
            create_time=1234567890,
            modify_time=1234567890,
            language="python",
            tags=["test", "python"],
        )
        
        assert metadata.source == "test.py"
        assert metadata.size == 1024
        assert metadata.access_time == 1234567890
        assert metadata.create_time == 1234567890
        assert metadata.modify_time == 1234567890
        assert metadata.language == "python"
        assert metadata.tags == ["test", "python"]
    
    def test_metadata_to_dict(self):
        """Test metadata to dictionary conversion."""
        metadata = DocumentMetadata(
            source="test.py",
            size=1024,
            access_time=1234567890,
        )
        
        result = metadata.to_dict()
        
        assert result["source"] == "test.py"
        assert result["size"] == 1024
        assert result["access_time"] == 1234567890


class TestCacheEntry:
    """Test CacheEntry functionality."""
    
    def test_cache_entry_creation(self):
        """Test cache entry creation."""
        metadata = DocumentMetadata(source="test.py")
        doc = Document("content", metadata)
        
        entry = CacheEntry(
            document=doc,
            score=0.8,
            access_count=5,
            last_accessed=1234567890,
            expiration_time=1234567890 + 3600,
        )
        
        assert entry.document == doc
        assert entry.score == 0.8
        assert entry.access_count == 5
        assert entry.last_accessed == 1234567890
        assert entry.expiration_time == 1234567890 + 3600
    
    def test_cache_entry_is_expired(self):
        """Test cache entry expiration check."""
        metadata = DocumentMetadata(source="test.py")
        doc = Document("content", metadata)
        
        # Not expired
        entry = CacheEntry(
            document=doc,
            score=0.8,
            expiration_time=1234567890 + 3600,
        )
        
        assert not entry.is_expired(1234567890)
        
        # Expired
        entry = CacheEntry(
            document=doc,
            score=0.8,
            expiration_time=1234567890 - 3600,
        )
        
        assert entry.is_expired(1234567890)
    
    def test_cache_entry_access(self):
        """Test cache entry access."""
        metadata = DocumentMetadata(source="test.py")
        doc = Document("content", metadata)
        
        entry = CacheEntry(
            document=doc,
            score=0.8,
            access_count=5,
            last_accessed=1234567890,
        )
        
        # Access entry
        entry.access(1234567891)
        
        assert entry.access_count == 6
        assert entry.last_accessed == 1234567891
    
    def test_cache_entry_to_dict(self):
        """Test cache entry to dictionary conversion."""
        metadata = DocumentMetadata(source="test.py")
        doc = Document("content", metadata)
        
        entry = CacheEntry(
            document=doc,
            score=0.8,
            access_count=5,
            last_accessed=1234567890,
        )
        
        result = entry.to_dict()
        
        assert result["document"]["content"] == "content"
        assert result["document"]["metadata"]["source"] == "test.py"
        assert result["score"] == 0.8
        assert result["access_count"] == 5
        assert result["last_accessed"] == 1234567890


class TestCacheStats:
    """Test CacheStats functionality."""
    
    def test_cache_stats_creation(self):
        """Test cache stats creation."""
        stats = CacheStats(
            total_documents=100,
            total_size=102400,
            hits=50,
            misses=30,
            eviction_count=10,
            compaction_count=5,
        )
        
        assert stats.total_documents == 100
        assert stats.total_size == 102400
        assert stats.hits == 50
        assert stats.misses == 30
        assert stats.eviction_count == 10
        assert stats.compaction_count == 5
    
    def test_cache_stats_hit_rate(self):
        """Test cache stats hit rate calculation."""
        stats = CacheStats(
            total_documents=100,
            total_size=102400,
            hits=50,
            misses=30,
            eviction_count=10,
            compaction_count=5,
        )
        
        assert stats.hit_rate == 50 / (50 + 30)  # 62.5%
    
    def test_cache_stats_to_dict(self):
        """Test cache stats to dictionary conversion."""
        stats = CacheStats(
            total_documents=100,
            total_size=102400,
            hits=50,
            misses=30,
            eviction_count=10,
            compaction_count=5,
        )
        
        result = stats.to_dict()
        
        assert result["total_documents"] == 100
        assert result["total_size"] == 102400
        assert result["hits"] == 50
        assert result["misses"] == 30
        assert result["eviction_count"] == 10
        assert result["compaction_count"] == 5
        assert "hit_rate" in result


class TestDFCLayer:
    """Test base DFCLayer functionality."""
    
    def test_layer_creation(self):
        """Test layer creation."""
        layer = DFCLayer("test", 1000)
        
        assert layer.name == "test"
        assert layer.max_size == 1000
        assert layer.entries == {}
        assert layer.size == 0
        assert layer.stats == CacheStats(0, 0, 0, 0, 0, 0)
    
    def test_layer_add_document(self):
        """Test adding document to layer."""
        layer = DFCLayer("test", 1000)
        
        metadata = DocumentMetadata(source="test.py", size=100)
        doc = Document("content", metadata)
        
        # Add document
        result = layer.add_document(doc, score=0.8)
        
        assert result is True
        assert len(layer.entries) == 1
        assert layer.size == 100
        assert layer.stats.total_documents == 1
        assert layer.stats.total_size == 100
        
        # Check entry
        entry = layer.entries[doc.id]
        assert entry.document == doc
        assert entry.score == 0.8
        assert entry.access_count == 0
    
    def test_layer_add_document_size_exceeded(self):
        """Test adding document when size is exceeded."""
        layer = DFCLayer("test", 100)  # Small size limit
        
        metadata = DocumentMetadata(source="test.py", size=200)  # Document too large
        doc = Document("content", metadata)
        
        # Add document
        result = layer.add_document(doc, score=0.8)
        
        assert result is False
        assert len(layer.entries) == 0
        assert layer.size == 0
    
    def test_layer_get_document(self):
        """Test getting document from layer."""
        layer = DFCLayer("test", 1000)
        
        metadata = DocumentMetadata(source="test.py", size=100)
        doc = Document("content", metadata)
        
        # Add document
        layer.add_document(doc, score=0.8)
        
        # Get document
        result = layer.get_document(doc.id)
        
        assert result is not None
        assert result.document == doc
        assert result.access_count == 1  # Should be incremented
        
        # Check stats
        assert layer.stats.hits == 1
        assert layer.stats.misses == 0
    
    def test_layer_get_nonexistent_document(self):
        """Test getting non-existent document."""
        layer = DFCLayer("test", 1000)
        
        # Get non-existent document
        result = layer.get_document("nonexistent")
        
        assert result is None
        assert layer.stats.hits == 0
        assert layer.stats.misses == 1
    
    def test_layer_remove_document(self):
        """Test removing document from layer."""
        layer = DFCLayer("test", 1000)
        
        metadata = DocumentMetadata(source="test.py", size=100)
        doc = Document("content", metadata)
        
        # Add document
        layer.add_document(doc, score=0.8)
        
        # Remove document
        result = layer.remove_document(doc.id)
        
        assert result is True
        assert len(layer.entries) == 0
        assert layer.size == 0
        assert layer.stats.total_documents == 0
        assert layer.stats.total_size == 0
    
    def test_layer_remove_nonexistent_document(self):
        """Test removing non-existent document."""
        layer = DFCLayer("test", 1000)
        
        # Remove non-existent document
        result = layer.remove_document("nonexistent")
        
        assert result is False
    
    def test_layer_evict_documents(self):
        """Test document eviction."""
        layer = DFCLayer("test", 200)  # Small size limit
        
        # Add documents
        for i in range(3):
            metadata = DocumentMetadata(source=f"test{i}.py", size=100)
            doc = Document(f"content{i}", metadata)
            layer.add_document(doc, score=0.8 - i * 0.1)  # Decreasing scores
        
        # Should have 2 documents (200 / 100)
        assert len(layer.entries) == 2
        assert layer.size == 200
        
        # Add another document - should trigger eviction
        metadata = DocumentMetadata(source="test3.py", size=100)
        doc = Document("content3", metadata)
        layer.add_document(doc, score=0.9)  # High score
        
        # Should still have 2 documents, but different ones
        assert len(layer.entries) == 2
        assert layer.size == 200
        assert layer.stats.eviction_count == 1
    
    def test_layer_clear(self):
        """Test clearing layer."""
        layer = DFCLayer("test", 1000)
        
        # Add documents
        for i in range(3):
            metadata = DocumentMetadata(source=f"test{i}.py", size=100)
            doc = Document(f"content{i}", metadata)
            layer.add_document(doc, score=0.8)
        
        # Clear layer
        layer.clear()
        
        assert len(layer.entries) == 0
        assert layer.size == 0
        assert layer.stats.total_documents == 0
        assert layer.stats.total_size == 0
    
    def test_layer_get_stats(self):
        """Test getting layer statistics."""
        layer = DFCLayer("test", 1000)
        
        # Add documents
        for i in range(3):
            metadata = DocumentMetadata(source=f"test{i}.py", size=100)
            doc = Document(f"content{i}", metadata)
            layer.add_document(doc, score=0.8)
        
        # Get stats
        stats = layer.get_stats()
        
        assert stats.total_documents == 3
        assert stats.total_size == 300
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.eviction_count == 0
        assert stats.compaction_count == 0


class TestHeatLayer:
    """Test HeatLayer functionality."""
    
    def test_heat_layer_creation(self):
        """Test heat layer creation."""
        layer = HeatLayer(1000)
        
        assert layer.name == "HEAT"
        assert layer.max_size == 1000
        assert layer.max_documents == 10
        assert layer.entries == {}
        assert layer.size == 0
    
    def test_heat_layer_scoring(self):
        """Test heat layer scoring."""
        layer = HeatLayer(1000)
        
        # Add documents with different access patterns
        for i in range(5):
            metadata = DocumentMetadata(source=f"test{i}.py", size=100)
            doc = Document(f"content{i}", metadata)
            layer.add_document(doc, score=0.5 + i * 0.1)  # Increasing scores
        
        # Check that documents are sorted by score
        doc_ids = list(layer.entries.keys())
        scores = [layer.entries[doc_id].score for doc_id in doc_ids]
        
        # Scores should be in descending order
        assert scores == sorted(scores, reverse=True)
    
    def test_heat_layer_max_documents(self):
        """Test heat layer max documents limit."""
        layer = HeatLayer(1000, max_documents=3)
        
        # Add more documents than max
        for i in range(5):
            metadata = DocumentMetadata(source=f"test{i}.py", size=100)
            doc = Document(f"content{i}", metadata)
            layer.add_document(doc, score=0.8)
        
        # Should only keep max_documents
        assert len(layer.entries) == 3


class TestHotLayer:
    """Test HotLayer functionality."""
    
    def test_hot_layer_creation(self):
        """Test hot layer creation."""
        layer = HotLayer(2000)
        
        assert layer.name == "HOT"
        assert layer.max_size == 2000
        assert layer.max_documents == 50
        assert layer.entries == {}
        assert layer.size == 0


class TestWarmLayer:
    """Test WarmLayer functionality."""
    
    def test_warm_layer_creation(self):
        """Test warm layer creation."""
        layer = WarmLayer(5000)
        
        assert layer.name == "WARM"
        assert layer.max_size == 5000
        assert layer.max_documents == 100
        assert layer.entries == {}
        assert layer.size == 0


class TestColdLayer:
    """Test ColdLayer functionality."""
    
    def test_cold_layer_creation(self):
        """Test cold layer creation."""
        layer = ColdLayer(10000)
        
        assert layer.name == "COLD"
        assert layer.max_size == 10000
        assert layer.max_documents == 200
        assert layer.entries == {}
        assert layer.size == 0


class TestIceLayer:
    """Test IceLayer functionality."""
    
    def test_ice_layer_creation(self):
        """Test ice layer creation."""
        layer = IceLayer(20000)
        
        assert layer.name == "ICE"
        assert layer.max_size == 20000
        assert layer.max_documents == 500
        assert layer.entries == {}
        assert layer.size == 0
    
    def test_ice_layer_long_term_storage(self):
        """Test ice layer long term storage."""
        layer = IceLayer(20000)
        
        # Add documents
        for i in range(10):
            metadata = DocumentMetadata(source=f"test{i}.py", size=500)
            doc = Document(f"content{i}", metadata)
            layer.add_document(doc, score=0.1)  # Low scores for ice layer
        
        # Should store all documents
        assert len(layer.entries) == 10
        assert layer.size == 5000


class TestBackgroundCompactor:
    """Test BackgroundCompactor functionality."""
    
    def test_compactor_creation(self):
        """Test compactor creation."""
        compactor = BackgroundCompactor()
        
        assert compactor.interval == 60  # Default 60 seconds
        assert compactor.is_running is False
        assert compactor.task is None
    
    @pytest.mark.asyncio
    async def test_compactor_start_stop(self):
        """Test compactor start and stop."""
        compactor = BackgroundCompactor()
        
        # Mock DFC
        mock_dfc = Mock()
        mock_dfc.compact = AsyncMock()
        
        # Start compactor
        await compactor.start(mock_dfc)
        
        assert compactor.is_running is True
        assert compactor.task is not None
        
        # Stop compactor
        await compactor.stop()
        
        assert compactor.is_running is False
        assert compactor.task is None
    
    @pytest.mark.asyncio
    async def test_compactor_compaction(self):
        """Test compaction process."""
        compactor = BackgroundCompactor(interval=1)  # Short interval for testing
        
        # Mock DFC
        mock_dfc = Mock()
        mock_dfc.compact = AsyncMock()
        
        # Start compactor
        await compactor.start(mock_dfc)
        
        # Wait for compaction
        await asyncio.sleep(1.1)
        
        # Check that compaction was called
        mock_dfc.compact.assert_called()
        
        # Stop compactor
        await compactor.stop()
    
    @pytest.mark.asyncio
    async def test_compactor_error_handling(self):
        """Test compactor error handling."""
        compactor = BackgroundCompactor(interval=1)
        
        # Mock DFC to raise error
        mock_dfc = Mock()
        mock_dfc.compact = AsyncMock(side_effect=Exception("Compaction failed"))
        
        # Start compactor
        await compactor.start(mock_dfc)
        
        # Wait for compaction
        await asyncio.sleep(1.1)
        
        # Check that error was logged but compactor continues
        mock_dfc.compact.assert_called()
        
        # Stop compactor
        await compactor.stop()


class TestDFC:
    """Test DFC main functionality."""
    
    def test_dfc_creation(self):
        """Test DFC creation."""
        dfc = DFC()
        
        assert dfc.heat_layer is not None
        assert dfc.hot_layer is not None
        assert dfc.warm_layer is not None
        assert dfc.cold_layer is not None
        assert dfc.ice_layer is not None
        assert dfc.compactor is not None
        assert dfc.total_size == 0
        assert dfc.total_documents == 0
    
    def test_dfc_add_document(self):
        """Test adding document to DFC."""
        dfc = DFC()
        
        metadata = DocumentMetadata(source="test.py", size=100)
        doc = Document("content", metadata)
        
        # Add document
        result = dfc.add_document(doc)
        
        assert result is True
        assert dfc.total_size == 100
        assert dfc.total_documents == 1
        
        # Document should be in heat layer
        assert doc.id in dfc.heat_layer.entries
        assert dfc.heat_layer.size == 100
    
    def test_dfc_get_document(self):
        """Test getting document from DFC."""
        dfc = DFC()
        
        metadata = DocumentMetadata(source="test.py", size=100)
        doc = Document("content", metadata)
        
        # Add document
        dfc.add_document(doc)
        
        # Get document
        result = dfc.get_document(doc.id)
        
        assert result is not None
        assert result.document == doc
        assert result.access_count == 1
        
        # Document should be promoted to hot layer
        assert doc.id in dfc.hot_layer.entries
        assert doc.id not in dfc.heat_layer.entries
    
    def test_dfc_get_nonexistent_document(self):
        """Test getting non-existent document."""
        dfc = DFC()
        
        # Get non-existent document
        result = dfc.get_document("nonexistent")
        
        assert result is None
    
    def test_dfc_remove_document(self):
        """Test removing document from DFC."""
        dfc = DFC()
        
        metadata = DocumentMetadata(source="test.py", size=100)
        doc = Document("content", metadata)
        
        # Add document
        dfc.add_document(doc)
        
        # Remove document
        result = dfc.remove_document(doc.id)
        
        assert result is True
        assert dfc.total_size == 0
        assert dfc.total_documents == 0
        assert doc.id not in dfc.heat_layer.entries
    
    def test_dfc_remove_nonexistent_document(self):
        """Test removing non-existent document."""
        dfc = DFC()
        
        # Remove non-existent document
        result = dfc.remove_document("nonexistent")
        
        assert result is False
    
    def test_dfc_promote_to_heat(self):
        """Test promoting document to heat layer."""
        dfc = DFC()
        
        metadata = DocumentMetadata(source="test.py", size=100)
        doc = Document("content", metadata)
        
        # Add document to cold layer
        dfc.cold_layer.add_document(doc, score=0.3)
        
        # Promote to heat
        dfc.promote_to_heat(doc.id)
        
        # Document should be in heat layer
        assert doc.id in dfc.heat_layer.entries
        assert doc.id not in dfc.cold_layer.entries
    
    def test_dfc_promote_to_hot(self):
        """Test promoting document to hot layer."""
        dfc = DFC()
        
        metadata = DocumentMetadata(source="test.py", size=100)
        doc = Document("content", metadata)
        
        # Add document to warm layer
        dfc.warm_layer.add_document(doc, score=0.5)
        
        # Promote to hot
        dfc.promote_to_hot(doc.id)
        
        # Document should be in hot layer
        assert doc.id in dfc.hot_layer.entries
        assert doc.id not in dfc.warm_layer.entries
    
    def test_dfc_compact(self):
        """Test DFC compaction."""
        dfc = DFC()
        
        # Add documents to warm layer
        for i in range(5):
            metadata = DocumentMetadata(source=f"test{i}.py", size=100)
            doc = Document(f"content{i}", metadata)
            dfc.warm_layer.add_document(doc, score=0.3)
        
        # Add documents to cold layer
        for i in range(5):
            metadata = DocumentMetadata(source=f"cold{i}.py", size=100)
            doc = Document(f"cold_content{i}", metadata)
            dfc.cold_layer.add_document(doc, score=0.1)
        
        # Compact
        dfc.compact()
        
        # Documents should be moved to ice layer
        for i in range(5):
            doc_id = dfc.warm_layer._generate_document_id(f"test{i}.py")
            if doc_id in dfc.warm_layer.entries:
                # Document stays in warm if it has high score
                pass
            else:
                # Document should be in ice layer
                assert doc_id in dfc.ice_layer.entries
        
        for i in range(5):
            doc_id = dfc.cold_layer._generate_document_id(f"cold{i}.py")
            if doc_id in dfc.cold_layer.entries:
                # Document stays in cold if it has high score
                pass
            else:
                # Document should be in ice layer
                assert doc_id in dfc.ice_layer.entries
    
    def test_dfc_clear(self):
        """Test clearing DFC."""
        dfc = DFC()
        
        # Add documents
        for i in range(5):
            metadata = DocumentMetadata(source=f"test{i}.py", size=100)
            doc = Document(f"content{i}", metadata)
            dfc.add_document(doc)
        
        # Clear DFC
        dfc.clear()
        
        assert dfc.total_size == 0
        assert dfc.total_documents == 0
        assert len(dfc.heat_layer.entries) == 0
        assert len(dfc.hot_layer.entries) == 0
        assert len(dfc.warm_layer.entries) == 0
        assert len(dfc.cold_layer.entries) == 0
        assert len(dfc.ice_layer.entries) == 0
    
    def test_dfc_get_stats(self):
        """Test getting DFC statistics."""
        dfc = DFC()
        
        # Add documents
        for i in range(5):
            metadata = DocumentMetadata(source=f"test{i}.py", size=100)
            doc = Document(f"content{i}", metadata)
            dfc.add_document(doc)
        
        # Get stats
        stats = dfc.get_stats()
        
        assert stats.total_documents == 5
        assert stats.total_size == 500
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.eviction_count == 0
        assert stats.compaction_count == 0
    
    def test_dfc_get_layer_stats(self):
        """Test getting layer statistics."""
        dfc = DFC()
        
        # Add documents
        for i in range(5):
            metadata = DocumentMetadata(source=f"test{i}.py", size=100)
            doc = Document(f"content{i}", metadata)
            dfc.add_document(doc)
        
        # Get layer stats
        layer_stats = dfc.get_layer_stats()
        
        assert "heat" in layer_stats
        assert "hot" in layer_stats
        assert "warm" in layer_stats
        assert "cold" in layer_stats
        assert "ice" in layer_stats
        
        # Check heat layer stats
        heat_stats = layer_stats["heat"]
        assert heat_stats.total_documents == 5
        assert heat_stats.total_size == 500
    
    @pytest.mark.asyncio
    async def test_dfc_start_stop_compactor(self):
        """Test starting and stopping DFC compactor."""
        dfc = DFC()
        
        # Start compactor
        await dfc.start_compactor()
        
        assert dfc.compactor.is_running is True
        
        # Stop compactor
        await dfc.stop_compactor()
        
        assert dfc.compactor.is_running is False
    
    @pytest.mark.asyncio
    async def test_dfc_health_check(self):
        """Test DFC health check."""
        dfc = DFC()
        
        health = await dfc.health_check()
        
        assert health["status"] == "healthy"
        assert "total_size" in health
        assert "total_documents" in health
        assert "layers" in health
        assert "compactor" in health
        assert health["total_size"] == 0
        assert health["total_documents"] == 0
        assert health["layers"]["heat"]["status"] == "healthy"
        assert health["layers"]["hot"]["status"] == "healthy"
        assert health["layers"]["warm"]["status"] == "healthy"
        assert health["layers"]["cold"]["status"] == "healthy"
        assert health["layers"]["ice"]["status"] == "healthy"
        assert health["compactor"]["status"] == "stopped"


class TestGlobalDFC:
    """Test global DFC functions."""
    
    def test_get_dfc(self):
        """Test getting DFC instance."""
        dfc1 = get_dfc()
        dfc2 = get_dfc()
        
        assert dfc1 is dfc2
        assert isinstance(dfc1, DFC)
    
    def test_initialize_dfc(self):
        """Test initializing DFC."""
        dfc = initialize_dfc()
        
        assert isinstance(dfc, DFC)
        assert dfc.heat_layer is not None
        assert dfc.hot_layer is not None
        assert dfc.warm_layer is not None
        assert dfc.cold_layer is not None
        assert dfc.ice_layer is not None
        assert dfc.compactor is not None