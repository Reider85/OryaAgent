"""Tests for DFC HeatCache component."""

import pytest
from collections import OrderedDict

from app.core.dfc.heat_cache import HeatCache


class TestHeatCache:
    """Test HeatCache functionality."""
    
    def test_heat_cache_initialization(self):
        """Test HeatCache initialization."""
        cache = HeatCache(max_size=1000)
        
        assert cache.max_size == 1000
        assert isinstance(cache.cache, OrderedDict)
        assert cache.hits == 0
        assert cache.misses == 0
    
    def test_heat_cache_put_and_get(self):
        """Test basic put and get operations."""
        cache = HeatCache(max_size=1000)
        
        # Put items
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        # Get items
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("nonexistent") is None
    
    def test_heat_cache_order_maintenance(self):
        """Test that LRU order is maintained."""
        cache = HeatCache(max_size=1000)
        
        # Add items
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")
        
        # Access key1 to move it to end
        cache.get("key1")
        
        # Add key4 to trigger eviction
        cache.put("key4", "value4")
        
        # key2 should be evicted (oldest that hasn't been accessed)
        assert cache.get("key2") is None
        # key1, key3, key4 should remain
        assert cache.get("key1") == "value1"
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"
    
    def test_heat_cache_eviction(self):
        """Test cache eviction when over size."""
        cache = HeatCache(max_size=10)
        
        # Add items until over size
        cache.put("key1", "value1")  # 6 chars
        cache.put("key2", "value2")  # 6 chars
        cache.put("key3", "value3")  # 6 chars - should trigger eviction
        
        # key1 should be evicted
        assert cache.get("key1") is None
        # key2 and key3 should remain
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3")
    
    def test_heat_cache_clear(self):
        """Test cache clear operation."""
        cache = HeatCache(max_size=1000)
        
        # Add items
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        # Access items
        cache.get("key1")
        cache.get("nonexistent")
        
        # Clear cache
        cache.clear()
        
        # Check that cache is empty
        assert len(cache.cache) == 0
        assert cache.hits == 0
        assert cache.misses == 0
        assert cache.get("key1") is None
        assert cache.get("key2") is None
    
    def test_heat_cache_stats(self):
        """Test cache statistics."""
        cache = HeatCache(max_size=1000)
        
        # Add some items
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        # Get some items
        cache.get("key1")
        cache.get("nonexistent")
        cache.get("key2")
        cache.get("nonexistent")
        
        stats = cache.get_stats()
        
        # Check basic stats
        assert stats["size"] == 12  # "value1" + "value2"
        assert stats["max_size"] == 1000
        assert stats["items"] == 2
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.5
    
    def test_heat_cache_stats_empty(self):
        """Test cache statistics for empty cache."""
        cache = HeatCache(max_size=1000)
        
        stats = cache.get_stats()
        
        # Check empty cache stats
        assert stats["size"] == 0
        assert stats["max_size"] == 1000
        assert stats["items"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0
    
    def test_heat_cache_large_values(self):
        """Test cache with large values."""
        cache = HeatCache(max_size=50)
        
        # Add large value
        large_value = "x" * 30
        cache.put("key1", large_value)
        
        # Add another large value that should trigger eviction
        cache.put("key2", "y" * 30)
        
        # key1 should be evicted
        assert cache.get("key1") is None
        # key2 should remain
        assert cache.get("key2") == "y" * 30
    
    def test_heat_cache_unicode_values(self):
        """Test cache with Unicode values."""
        cache = HeatCache(max_size=1000)
        
        # Add Unicode values
        cache.put("key1", "value with 🚀 unicode")
        cache.put("key2", "value with 中文")
        
        # Get values
        assert cache.get("key1") == "value with 🚀 unicode"
        assert cache.get("key2") == "value with 中文"
    
    def test_heat_cache_special_characters(self):
        """Test cache with special characters in keys."""
        cache = HeatCache(max_size=1000)
        
        # Add keys with special characters
        cache.put("key.1", "value1")
        cache.put("key-2", "value2")
        cache.put("key_3", "value3")
        cache.put("key 4", "value4")
        cache.put("key/5", "value5")
        
        # Get values
        assert cache.get("key.1") == "value1"
        assert cache.get("key-2") == "value2"
        assert cache.get("key_3") == "value3"
        assert cache.get("key 4") == "value4"
        assert cache.get("key/5") == "value5"