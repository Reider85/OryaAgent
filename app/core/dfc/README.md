# DFC (Dynamic Fast Context) Implementation

This implementation provides the DFC (Dynamic Fast Context) component for OryaAgent BETA phase, featuring 5 layers (HEAT/HOT/WARM/COLD/ICE) with background compaction.

## Overview

DFC is a dynamic context management system that maintains 5 layers of information:
- **HEAT**: Predicted context (placeholder in BETA, full implementation in PROD)
- **HOT**: Active context for current turn (4-8K tokens)
- **WARM**: Recent context from previous turns (16-32K tokens)
- **COLD**: Compacted summaries of older context (unlimited)
- **ICE**: External context through UKB (unlimited)

## Key Features

- **5-Layer Architecture**: Efficient context management with automatic layer transitions
- **Background Compaction**: Asynchronous compaction of WARM→COLD layers
- **Redis Persistence**: Automatic persistence of HOT and WARM layers
- **Metrics Integration**: Comprehensive metrics for monitoring and debugging
- **Span Integration**: Detailed tracing for observability
- **Integration Ready**: Seamless integration with existing OryaAgent components

## Files Structure

```
app/core/dfc/
├── __init__.py                 # Package exports
├── dfc.py                     # Main DFC implementation
├── heat_cache.py              # HEAT cache implementation
├── background_compactor.py    # Background compaction logic
├── context_assembler.py       # Context assembly for prompts
├── models.py                  # Data models and types
├── metrics.py                 # Metrics collection
└── integration.py            # Integration with existing components
```

## Usage

### Basic Usage

```python
from app.core.dfc import initialize_dfc, get_dfc

# Initialize DFC
dfc = initialize_dfc(
    redis_client=redis_client,
    ukb_router=ukb_router,
    lsp_bus=lsp_bus,
    memory=memory_store,
)

# Get global instance
dfc = get_dfc()

# Promote items to HOT layer
dfc.promote_to_hot("key1", "value1")

# Assemble HOT context
plan = {"cacheable_prefix": "System prompt...", "prefetch_hints": ["hint1", "hint2"]}
hot_context = dfc.assemble_hot(plan)
```

### Integration Usage

```python
from app.core.dfc.integration import initialize_dfc_integration

# Initialize integration
integration = initialize_dfc_integration(
    redis_client=redis_client,
    ukb_router=ukb_router,
    lsp_bus=lsp_bus,
    memory=memory_store,
)

# Promote tool results
await integration.promote_tool_result("write", result)

# Get context for prompts
context = integration.get_context_for_prompt(plan)
```

### Background Compaction

```python
# Start background compactor
await dfc.start_background_compactor()

# Stop background compactor
await dfc.stop_background_compactor()
```

## Configuration

### Layer Sizes

- **HOT**: 8,000 tokens (configurable)
- **WARM**: 32,000 tokens (configurable)
- **HEAT**: 4,000 tokens (configurable)
- **COLD**: Unlimited (with compaction)
- **ICE**: Unlimited (through UKB)

### Compaction Settings

- **Interval**: 60 seconds
- **Threshold**: 100 items in WARM layer
- **Ratio**: 20% of WARM items compacted per run

## Metrics

The DFC implementation provides comprehensive metrics:

- `orya_dfc_hot_size_tokens`: Current HOT layer size
- `orya_dfc_warm_size_tokens`: Current WARM layer size
- `orya_dfc_cold_size`: Number of items in COLD layer
- `orya_dfc_compaction_total`: Total compaction operations
- `orya_dfc_compaction_duration_ms`: Compaction duration
- `orya_dfc_heat_cache_hits_total`: HEAT cache hits
- `orya_dfc_heat_cache_misses_total`: HEAT cache misses

## Testing

Run the test suite:

```bash
# Run all DFC tests
pytest tests/test_dfc.py

# Run specific test modules
pytest tests/test_dfc_heat_cache.py
pytest tests/test_dfc_background_compactor.py
pytest tests/test_dfc_integration.py
```

## Implementation Details

### Layer Management

- **HOT Layer**: OrderedDict with LRU eviction
- **WARM Layer**: OrderedDict with manual compaction
- **COLD Layer**: List of CompactSummary objects
- **HEAT Layer**: Predictive cache (placeholder in BETA)

### Background Compaction

- Runs asynchronously in the background
- Compacts 20% of WARM items to COLD layer
- Triggers based on time (60s) or size (100 items)
- Non-blocking, doesn't affect agent performance

### Redis Integration

- Persists HOT and WARM layers
- Uses 1-hour TTL for automatic cleanup
- Automatic restoration on initialization

### Observability

- Comprehensive span integration
- Detailed metrics collection
- Performance monitoring

## Future Enhancements (PROD)

- **HEAT Cache**: Full implementation with predictive algorithms
- **Concurrent Operations**: Parallel processing for better performance
- **Advanced Compaction**: Smart compaction strategies
- **Layer Compression**: Efficient storage for COLD layer
- **Distributed Support**: Multi-node DFC coordination

## Integration Points

### With System Prompt Builder

```python
from app.core.system_prompt_builder import SystemPromptBuilder

prompt_builder = SystemPromptBuilder(dfc)
system_prompt = prompt_builder.build_system_prompt(
    base_prompt="Your system prompt...", tools=tools, plan=plan
)
```

### With Tri-Model Pipeline

```python
# In Tri-Model Pipeline executor phase
hot_context = dfc.assemble_hot(plan)
# Use hot_context in model prompt
```

### With Retrieval Orchestrator

```python
# Promote retrieval results to HOT layer
dfc.promote_to_hot("retrieval_result", result)
```

## Performance Considerations

- **Memory Usage**: DFC maintains active context in memory
- **CPU Usage**: Background compaction runs asynchronously
- **Network Usage**: Redis persistence for layer state
- **Latency**: HOT context assembly is synchronous and fast

## Monitoring

Monitor DFC health through:

1. **Metrics**: Track layer sizes and compaction activity
2. **Spans**: Monitor context assembly and compaction duration
3. **Logs**: Debug information for troubleshooting
4. **Redis**: Check persistence layer status

## Troubleshooting

### Common Issues

1. **High Memory Usage**: Check layer sizes, adjust configuration
2. **Slow Performance**: Monitor compactivity, adjust interval
3. **Redis Connection**: Check Redis availability and configuration
4. **Memory Leaks**: Monitor layer sizes, check for proper cleanup

### Debug Mode

Enable debug logging:

```python
import logging

logging.getLogger("app.core.dfc").setLevel(logging.DEBUG)
```

## Contributing

When contributing to DFC:

1. Follow the existing code patterns
2. Add comprehensive tests
3. Update metrics and spans
4. Document new features
5. Test integration with existing components