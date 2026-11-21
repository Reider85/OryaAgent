#!/usr/bin/env python3
"""Simple performance test for UKB Router."""

import asyncio
import time

from app.core.ukb.router import get_ukb_router
from app.tools.ukb import ukb_lookup


async def test_performance():
    """Test basic performance metrics."""
    print("UKB Router Performance Test")
    print("=" * 40)

    router = get_ukb_router()

    # Test single lookup
    start_time = time.time()
    await router.lookup("performance test")
    end_time = time.time()

    lookup_time = (end_time - start_time) * 1000
    print(f"Single lookup: {lookup_time:.2f}ms")

    # Test cache performance
    start_time = time.time()
    await router.lookup("performance test")  # Should be cached
    end_time = time.time()

    cache_time = (end_time - start_time) * 1000
    print(f"Cache hit: {cache_time:.2f}ms")

    # Test tool interface
    start_time = time.time()
    await ukb_lookup._arun("tool test", capability="lsp.def")
    end_time = time.time()

    tool_time = (end_time - start_time) * 1000
    print(f"Tool interface: {tool_time:.2f}ms")

    # Test metrics
    metrics = router.get_metrics()
    print(f"Total lookups: {metrics['lookups_total']}")
    print(f"Cache size: {metrics['cache_size']}")

    print("\nPerformance Summary:")
    print(
        f"- Single lookup: {lookup_time:.2f}ms {'PASS' if lookup_time < 500 else 'FAIL'}"
    )
    print(f"- Cache hit: {cache_time:.2f}ms {'PASS' if cache_time < 10 else 'FAIL'}")
    print(
        f"- Tool interface: {tool_time:.2f}ms {'PASS' if tool_time < 500 else 'FAIL'}"
    )


if __name__ == "__main__":
    asyncio.run(test_performance())
