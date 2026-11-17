#!/usr/bin/env python3
"""Performance benchmark for UKB Router (B-27)."""

import asyncio
import time
import statistics
from app.core.ukb.router import get_ukb_router
from app.tools.ukb import ukb_lookup


async def benchmark_lookup_performance():
    """Benchmark lookup performance with various scenarios."""
    print("UKB Router Performance Benchmark")
    print("=" * 50)
    
    router = get_ukb_router()
    
    # Test scenarios
    test_scenarios = [
        ("Empty query", ""),
        ("Simple query", "hello world"),
        ("LSP capability", "UserService.create", "lsp.def"),
        ("Memory capability", "memory-tier design", "memory.semantic"),
        ("Complex query", "What are the best practices for microservices architecture?"),
    ]
    
    results = []
    
    for scenario in test_scenarios:
        scenario_name = scenario[0]
        query = scenario[1]
        capability = scenario[2] if len(scenario) > 2 else None
        
        print(f"\nTesting: {scenario_name}")
        
        # Warm up
        await router.lookup(query, capability=capability)
        
        # Benchmark
        times = []
        for i in range(10):
            start_time = time.time()
            await router.lookup(query, capability=capability)
            end_time = time.time()
            times.append((end_time - start_time) * 1000)  # Convert to milliseconds
        
        avg_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)
        p95_time = statistics.quantiles(times, n=20)[18]  # 95th percentile
        
        print(f"   Average: {avg_time:.2f}ms")
        print(f"   Fastest: {min_time:.2f}ms")
        print(f"   Slowest: {max_time:.2f}ms")
        print(f"   95th percentile: {p95_time:.2f}ms")
        
        results.append({
            "scenario": scenario_name,
            "avg_time": avg_time,
            "min_time": min_time,
            "max_time": max_time,
            "p95_time": p95_time,
            "query": query,
            "capability": capability
        })
    
    # Performance summary
    print("\n" + "=" * 50)
    print("📋 Performance Summary")
    print("=" * 50)
    
    all_times = [r["avg_time"] for r in results]
    print(f"Overall average: {statistics.mean(all_times):.2f}ms")
    print(f"Performance target (<500ms): {'PASS' if statistics.mean(all_times) < 500 else 'FAIL'}")
    
    # Cache performance
    print("\nCache Performance Test")
    print("-" * 30)
    
    query = "cache_test"
    
    # First call (cache miss)
    start_time = time.time()
    await router.lookup(query)
    cache_miss_time = (time.time() - start_time) * 1000
    
    # Second call (cache hit)
    start_time = time.time()
    await router.lookup(query)
    cache_hit_time = (time.time() - start_time) * 1000
    
    print(f"Cache miss: {cache_miss_time:.2f}ms")
    print(f"Cache hit: {cache_hit_time:.2f}ms")
    print(f"Cache speedup: {cache_miss_time / cache_hit_time:.1f}x")
    
    # Metrics
    print("\nMetrics")
    print("-" * 20)
    metrics = router.get_metrics()
    print(f"Total lookups: {metrics['lookups_total']}")
    print(f"Cache size: {metrics['cache_size']}")
    print(f"Cache hit rate: {metrics['cache_hit_rate']:.2%}")
    
    # Memory usage
    print("\nMemory Usage")
    print("-" * 20)
    import sys
    print(f"Router object size: {sys.getsizeof(router)} bytes")
    print(f"Cache size: {sys.getsizeof(router._cache)} bytes")
    
    return results


async def benchmark_concurrent_requests():
    """Benchmark concurrent request handling."""
    print("\nConcurrent Requests Benchmark")
    print("=" * 50)
    
    router = get_ukb_router()
    
    # Test different concurrency levels
    concurrency_levels = [1, 5, 10, 20, 50]
    
    for level in concurrency_levels:
        print(f"\nTesting {level} concurrent requests...")
        
        queries = [f"concurrent_test_{i}" for i in range(level)]
        
        start_time = time.time()
        tasks = [router.lookup(query) for query in queries]
        results = await asyncio.gather(*tasks)
        end_time = time.time()
        
        total_time = (end_time - start_time) * 1000
        avg_time_per_request = total_time / level
        
        print(f"   Total time: {total_time:.2f}ms")
        print(f"   Avg per request: {avg_time_per_request:.2f}ms")
        print(f"   Throughput: {level / (total_time / 1000):.1f} req/s")


async def benchmark_cache_efficiency():
    """Benchmark cache efficiency with repeated queries."""
    print("\nCache Efficiency Benchmark")
    print("=" * 50)
    
    router = get_ukb_router()
    
    # Generate diverse queries
    queries = [
        "python programming",
        "machine learning", 
        "web development",
        "database design",
        "system architecture",
        "user experience",
        "performance optimization",
        "security best practices",
        "cloud computing",
        "devops practices"
    ]
    
    # Phase 1: Populate cache (all cache misses)
    print("Phase 1: Populating cache...")
    start_time = time.time()
    for query in queries:
        await router.lookup(query)
    phase1_time = time.time() - start_time
    
    # Phase 2: Cache hits
    print("Phase 2: Cache hits...")
    start_time = time.time()
    for query in queries:
        await router.lookup(query, use_cache=True)
    phase2_time = time.time() - start_time
    
    print(f"Phase 1 (cache miss): {phase1_time:.2f}s")
    print(f"Phase 2 (cache hit): {phase2_time:.2f}s")
    print(f"Speedup: {phase1_time / phase2_time:.1f}x")
    
    # Cache stats
    metrics = router.get_metrics()
    print(f"Cache hit rate: {metrics['cache_hit_rate']:.2%}")
    print(f"Cache size: {metrics['cache_size']}")


async def main():
    """Run all benchmarks."""
    try:
        await benchmark_lookup_performance()
        await benchmark_concurrent_requests()
        await benchmark_cache_efficiency()
        
        print("\nAll benchmarks completed successfully!")
        
    except Exception as e:
        print(f"Benchmark failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())