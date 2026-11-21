"""Basic DFC functionality tests."""

from unittest.mock import AsyncMock

import pytest

from app.core.dfc.dfc import DFC, CompactSummary, HeatCache


class TestDFC:
    """Test basic DFC functionality."""

    def test_dfc_initialization(self):
        """Test DFC initialization."""
        dfc = DFC()

        assert dfc.heat is not None
        assert dfc.hot is not None
        assert dfc.warm is not None
        assert dfc.cold is not None
        assert dfc.compactor is not None

    def test_heat_cache_basic(self):
        """Test HeatCache basic functionality."""
        cache = HeatCache(max_size=100)

        # Test put and get
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

        # Test LRU eviction
        for i in range(10):
            cache.put(f"key{i}", f"value{i}")

        # Should still have key1 (most recently used)
        assert cache.get("key1") == "value1"

    def test_promote_to_hot(self):
        """Test promoting items to HOT layer."""
        dfc = DFC()

        # Promote items
        dfc.promote_to_hot("tool1", "result1")
        dfc.promote_to_hot("tool2", "result2")

        # Check items are in HOT
        assert "tool1" in dfc.hot
        assert "tool2" in dfc.hot
        assert dfc.hot["tool1"] == "result1"
        assert dfc.hot["tool2"] == "result2"

    def test_hot_warm_demotion(self):
        """Test demotion from HOT to WARM when exceeding size."""
        dfc = DFC(max_hot_size=10)

        # Add items until we exceed the limit
        dfc.promote_to_hot("key1", "value1")
        dfc.promote_to_hot("key2", "value2")
        dfc.promote_to_hot("key3", "value3")  # Should trigger demotion

        # Should have 1 key in HOT (newest) and 2 keys in WARM (older ones)
        assert len(dfc.hot) == 1
        assert len(dfc.warm) == 2
        assert "key3" in dfc.hot  # Most recent should stay
        assert "key2" in dfc.warm  # Second most recent should be demoted
        assert "key1" in dfc.warm  # Oldest should be demoted

    def test_snapshot(self):
        """Test creating DFC snapshot."""
        dfc = DFC()

        # Add some data
        dfc.promote_to_hot("tool1", "result1")
        dfc.warm["memory1"] = "memory_content"
        dfc.cold.append(
            CompactSummary(
                content_hash="hash1", summary="summary1", metadata={"key": "value"}
            )
        )

        # Create snapshot
        snapshot = dfc.snapshot()

        # Check that snapshot is independent
        assert snapshot is not dfc
        assert snapshot.hot["tool1"] == "result1"
        assert snapshot.warm["memory1"] == "memory_content"
        assert len(snapshot.cold) == 1

    def test_assemble_hot(self):
        """Test assembling HOT context."""
        dfc = DFC()

        # Add some data
        dfc.promote_to_hot("tool1", "result1")
        dfc.promote_to_hot("tool2", "result2")

        # Create plan
        plan = {
            "cacheable_prefix": "System: You are a helpful assistant.",
            "prefetch_hints": ["hint1", "hint2"],
        }

        # Assemble HOT context
        context = dfc.assemble_hot(plan)

        # Should contain cacheable prefix and dynamic content
        assert "System: You are a helpful assistant." in context
        assert "tool1: result1" in context
        assert "tool2: result2" in context


class TestHeatCache:
    """Test HeatCache functionality."""

    def test_heat_cache_stats(self):
        """Test HeatCache statistics."""
        cache = HeatCache(max_size=100)

        # Initially empty
        stats = cache.get_stats()
        assert stats["size"] == 0
        assert stats["max_size"] == 100

        # Add items
        cache.put("key1", "value1")
        cache.put("key2", "value2")

        # Check stats
        stats = cache.get_stats()
        assert stats["size"] > 0
        assert stats["max_size"] == 100


class TestCompactSummary:
    """Test CompactSummary functionality."""

    def test_compact_summary_creation(self):
        """Test creating CompactSummary."""
        summary = CompactSummary(
            content_hash="hash123", summary="Test summary", metadata={"source": "test"}
        )

        assert summary.content_hash == "hash123"
        assert summary.summary == "Test summary"
        assert summary.metadata["source"] == "test"
        # created_at is set in __post_init__, so it should exist
        assert hasattr(summary, "created_at")


@pytest.mark.asyncio
class TestDFCAsync:
    """Test async DFC functionality."""

    async def test_dfc_initialization_from_redis(self):
        """Test DFC initialization from Redis."""
        # Mock Redis client
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        dfc = DFC(redis_client=mock_redis)
        await dfc.initialize()

        # Check that Redis was called
        mock_redis.get.assert_called()

    async def test_dfc_save_to_redis(self):
        """Test DFC save to Redis."""
        # Mock Redis client
        mock_redis = AsyncMock()

        dfc = DFC(redis_client=mock_redis)

        # Add some data
        dfc.promote_to_hot("tool1", "result1")
        dfc.warm["memory1"] = "memory_content"

        # Save to Redis
        await dfc.save_to_redis()

        # Check that Redis was called
        mock_redis.set.assert_called()

    async def test_background_compactor(self):
        """Test background compactor."""
        dfc = DFC()

        # Add items to WARM layer
        dfc.warm["item1"] = "content1"
        dfc.warm["item2"] = "content2"
        dfc.warm["item3"] = "content3"

        # Start background compactor
        await dfc.start_background_compactor()

        # Check that compactor task was created
        assert dfc.compactor_task is not None
        assert not dfc.compactor_task.done()

        # Stop compactor
        await dfc.stop_background_compactor()

        # Check that compactor task was cancelled
        assert dfc.compactor_task.done()
