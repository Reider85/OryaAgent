"""Tests for DFC BackgroundCompactor component."""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

from app.core.dfc.background_compactor import BackgroundCompactor
from app.core.dfc import DFC, CompactSummary


class TestBackgroundCompactor:
    """Test BackgroundCompactor functionality."""
    
    def test_compactor_initialization(self):
        """Test compactor initialization."""
        dfc = DFC()
        compactor = BackgroundCompactor(dfc)
        
        assert compactor.dfc is dfc
        assert compactor.compaction_interval == 60
        assert compactor.last_compaction == 0
        assert compactor.compaction_count == 0
        assert not compactor.is_running
    
    def test_compactor_start_stop(self):
        """Test compactor start and stop."""
        dfc = DFC()
        compactor = BackgroundCompactor(dfc)
        
        # Start compactor
        compactor.is_running = True
        assert compactor.is_running
        
        # Stop compactor
        compactor.stop()
        assert not compactor.is_running
    
    @pytest.mark.asyncio
    async def test_compactor_compact_if_needed_time_trigger(self):
        """Test compaction triggered by time."""
        dfc = DFC()
        compactor = BackgroundCompactor(dfc)
        
        # Add items to WARM
        dfc.warm["key1"] = "value1"
        dfc.warm["key2"] = "value2"
        
        # Mock time to trigger compaction
        with patch('time.time', return_value=1000):
            await compactor.compact_if_needed()
        
        # Check that compaction was triggered
        assert compactor.last_compaction == 1000
        assert compactor.compaction_count == 1
        assert len(dfc.cold) == 1  # 20% of 2 = 1
        assert len(dfc.warm) == 1  # 1 item left
    
    @pytest.mark.asyncio
    async def test_compactor_compact_if_needed_size_trigger(self):
        """Test compaction triggered by size."""
        dfc = DFC()
        compactor = BackgroundCompactor(dfc)
        
        # Set lower threshold for testing
        compactor.compaction_interval = 1
        compactor.compaction_threshold = 3
        
        # Add items to WARM
        dfc.warm["key1"] = "value1"
        dfc.warm["key2"] = "value2"
        dfc.warm["key3"] = "value3"  # Should trigger compaction
        
        await compactor.compact_if_needed()
        
        # Check that compaction was triggered
        assert compactor.compaction_count == 1
        assert len(dfc.cold) == 1  # 20% of 3 = 1
        assert len(dfc.warm) == 2  # 2 items left
    
    @pytest.mark.asyncio
    async def test_compactor_compact_warm_to_cold(self):
        """Test WARM to COLD compaction."""
        dfc = DFC()
        compactor = BackgroundCompactor(dfc)
        
        # Add items to WARM
        dfc.warm["key1"] = "value1"
        dfc.warm["key2"] = "value2"
        dfc.warm["key3"] = "value3"
        dfc.warm["key4"] = "value4"
        dfc.warm["key5"] = "value5"
        
        # Mock span
        with patch('app.core.dfc.background_compactor.emit_span') as mock_emit_span:
            mock_span = Mock()
            mock_emit_span.return_value.__enter__.return_value = mock_span
            
            await compactor.compact_warm_to_cold()
        
        # Check that items were moved to COLD
        assert len(dfc.cold) == 1  # 20% of 5 = 1
        assert len(dfc.warm) == 4  # 4 items left
        
        # Check that the compacted item has correct metadata
        cold_item = dfc.cold[0]
        assert cold_item.content_hash is not None
        assert cold_item.summary is not None
        assert cold_item.metadata["original_key"] in ["key1", "key2", "key3", "key4", "key5"]
        assert cold_item.metadata["original_value"] in ["value1", "value2", "value3", "value4", "value5"]
        
        # Check that span attributes were set
        mock_span.set_attribute.assert_called()
    
    @pytest.mark.asyncio
    async def test_compactor_run_loop(self):
        """Test compactor run loop."""
        dfc = DFC()
        compactor = BackgroundCompactor(dfc)
        
        # Mock compact_if_needed
        compactor.compact_if_needed = AsyncMock()
        
        # Start run loop with short interval
        compactor.compaction_interval = 0.1
        
        # Run for a short time
        task = asyncio.create_task(compactor.run())
        
        # Let it run a bit
        await asyncio.sleep(0.2)
        
        # Stop it
        compactor.stop()
        
        # Wait for task to complete
        await task
        
        # Check that compact_if_needed was called
        compactor.compact_if_needed.assert_called()
    
    @pytest.mark.asyncio
    async def test_compactor_run_loop_exception_handling(self):
        """Test compactor run loop exception handling."""
        dfc = DFC()
        compactor = BackgroundCompactor(dfc)
        
        # Mock compact_if_needed to raise exception
        compactor.compact_if_needed = AsyncMock(side_effect=Exception("Test error"))
        
        # Mock logger
        with patch('app.core.dfc.background_compactor.logger') as mock_logger:
            # Start run loop with short interval
            compactor.compaction_interval = 0.1
            
            # Run for a short time
            task = asyncio.create_task(compactor.run())
            
            # Let it run a bit
            await asyncio.sleep(0.2)
            
            # Stop it
            compactor.stop()
            
            # Wait for task to complete
            await task
            
            # Check that error was logged
            mock_logger.error.assert_called()
    
    def test_generate_content_hash(self):
        """Test content hash generation."""
        dfc = DFC()
        compactor = BackgroundCompactor(dfc)
        
        hash1 = compactor._generate_content_hash("key1", "value1")
        hash2 = compactor._generate_content_hash("key1", "value1")
        hash3 = compactor._generate_content_hash("key1", "value2")
        
        # Same content should produce same hash
        assert hash1 == hash2
        
        # Different content should produce different hash
        assert hash1 != hash3
    
    def test_create_summary(self):
        """Test summary creation."""
        dfc = DFC()
        compactor = BackgroundCompactor(dfc)
        
        summary = compactor._create_summary("key1", "value1")
        
        assert isinstance(summary, CompactSummary)
        assert summary.content_hash is not None
        assert "Summary of key1:" in summary.summary
        assert summary.metadata["original_key"] == "key1"
        assert summary.metadata["original_value"] == "value1"
        assert summary.created_at is not None