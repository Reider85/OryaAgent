# B-02: oriahs_search Tool Implementation

## Overview

B-02 implements semantic codebase search through MCP (Model Context Protocol) integration. The `oriahs_search` tool provides hybrid search capabilities combining lexical and semantic matching through the OriaHS backend.

## Features

- **Semantic Search**: Hybrid retrieval using sparse (lexical) and dense (semantic) vectors
- **MCP Integration**: Communicates with oriahs-mcp server through Model Context Protocol
- **Caching**: Results cached for 1 hour to improve performance
- **Security**: Injection detection and content sanitization
- **Fallback**: Graceful degradation to lexical search when MCP unavailable
- **Observability**: Comprehensive metrics and spans for monitoring

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   oriahs_search │    │   MCP Client    │    │  oriahs-mcp     │
│      Tool       │───▶│   Infrastructure│───▶│    Server       │
│                 │    │                 │    │                 │
│ • Query parsing │    │ • Health checks │    │ • Hybrid search │
│ • Result format │    │ • Tool calls    │    │ • OriaHS API    │
│ • Cache handling│    │ • Error handling│    │ • Authentication│
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Implementation

### 1. MCP Client Infrastructure (`app/mcp/client.py`)

- `MCPClient`: HTTP client for MCP server communication
- `MCPClientConfig`: Configuration for MCP connection
- Health checks and automatic retry logic
- Thread-safe concurrent access

### 2. OriaHS MCP Server (`app/mcp/oriahs_mcp.py`)

- `OriaHSMCPServer`: MCP server wrapping OriaHS API
- `OriaHSConfig`: Configuration for OriaHS backend
- Tool: `hybrid_search` with query, top_k, and filters parameters
- Health check endpoint for monitoring

### 3. oriahs_search Tool (`app/tools/oriahs_search.py`)

- LangChain @tool decorator integration
- Query validation and parameter checking
- Result parsing and formatting
- Security checks and content sanitization
- Caching with 1-hour TTL

### 4. Configuration (`app/core/mcp_config.py`)

- Environment variable-based configuration
- Fallback behavior settings
- Timeout and retry configuration

### 5. Observability (`app/core/observability/metrics.py`)

- Metrics for MCP operations
- Metrics for semantic search
- Context managers for automatic metric collection
- Integration with existing span infrastructure

## Usage

### Basic Search

```python
from app.tools.oriahs_search import oriahs_search

# Simple semantic search
result = await oriahs_search.ainvoke({"query": "authentication system"})

# Search with custom parameters
result = await oriahs_search.ainvoke(
    {"query": "user authentication", "top_k": 5, "filters": {"file_type": "python"}}
)
```

### Configuration

Environment variables:

```bash
# MCP server configuration
MCP_SERVER_URL=http://localhost:8765
MCP_AUTH_TOKEN=your_auth_token_here
MCP_TIMEOUT=10.0
MCP_MAX_RETRIES=3

# OriaHS backend configuration
ORIAHS_BASE_URL=http://localhost:8000
ORIAHS_TOKEN=your_oriahs_token_here
ORIAHS_TIMEOUT=10.0
ORIAHS_MAX_RETRIES=3

# Fallback behavior
ORIAHS_SEARCH_FALLBACK_ENABLED=true
ORIAHS_SEARCH_FALLBACK_TO_GREP=true
ORIAHS_SEARCH_CACHE_TTL=3600
```

## API Reference

### oriahs_search Tool

**Parameters:**
- `query` (str, required): Natural language search query
- `top_k` (int, optional): Maximum results (1-50, default: 10)
- `filters` (dict, optional): Search filters (file type, date range, etc.)

**Returns:**
- Formatted string with search results including:
  - Result rank and score
  - File path
  - Content preview (truncated to 500 chars)
  - File type

**Errors:**
- `ToolException` for invalid parameters or MCP unavailability
- Graceful fallback to lexical search suggestion

### MCP Server Endpoints

**Health Check:**
```
GET /health
```

**Tool Listing:**
```
GET /tools
```

**Tool Execution:**
```
POST /call
{
  "name": "hybrid_search",
  "arguments": {
    "query": "search string",
    "top_k": 10,
    "filters": {}
  }
}
```

## Testing

### Unit Tests (`tests/test_oriahs_search.py`)

- Mock-based testing for MCP client
- Result parsing and formatting tests
- Error handling and fallback behavior
- Cache hit/miss scenarios

### Integration Tests (`tests/integration/test_oriahs_mcp_integration.py`)

- End-to-end search flow testing
- Actual MCP server connection (when available)
- Configuration testing
- Health check verification

### Performance Tests (`tests/performance/test_oriahs_search_performance.py`)

- Latency testing (<2s target)
- Concurrent search performance
- Memory usage stability
- Cache performance (<100ms for hits)

## Deployment

### Docker Setup

```bash
# Build the oriahs-mcp server
docker build -f deploy/Dockerfile.oriahs-mcp -t orya-agent-oriahs-mcp .

# Run with docker-compose
docker compose --profile app up -d
```

### Docker Compose Services

- `oriahs-mcp`: MCP server container
- `api`: Main API service with MCP configuration
- `chainlit`: UI service with MCP dependency

### Production Considerations

- Monitor MCP server health and availability
- Set appropriate timeouts and retry limits
- Configure authentication tokens
- Monitor search latency and success rates
- Plan for OriaHS backend scaling

## Monitoring

### Metrics

- `orya_mcp_call_total`: Total MCP tool calls
- `orya_mcp_call_latency_ms`: MCP call latency
- `orya_mcp_server_health_status`: Server health gauge
- `orya_semantic_search_total`: Total searches
- `orya_semantic_search_latency_ms`: Search latency
- `orya_semantic_search_results_count`: Results per search
- `orya_semantic_search_cache_hits_total`: Cache hits

### Spans

- `mcp.call`: MCP tool operations
- `semantic.search`: Semantic search operations
- Includes attributes for tool name, status, latency, and errors

## Security

- Input validation for search queries
- Injection detection on search results
- Content sanitization with untrusted markers
- Secure MCP server communication
- Path validation for search results

## Performance

- **Target Latency**: <2s for search operations
- **Cache Hit Latency**: <100ms
- **Concurrent Searches**: Support for multiple concurrent requests
- **Memory Usage**: Stable across multiple operations
- **Timeout Protection**: Prevents hanging on slow responses

## Error Handling

- **MCP Server Unavailable**: Falls back to lexical search suggestion
- **Connection Errors**: Retries with exponential backoff
- **Invalid Results**: Graceful parsing with error logging
- **Timeout Protection**: Automatic timeout for slow operations

## Future Enhancements

- **Additional Search Modes**: Vector-only, keyword-only search
- **Advanced Filters**: Date ranges, file size, custom metadata
- **Result Streaming**: Progressive result delivery
- **Search History**: Query history and recommendations
- **Multi-language Support**: Enhanced language-specific search

## Troubleshooting

### Common Issues

1. **MCP Server Not Available**
   - Check MCP server logs
   - Verify network connectivity
   - Check authentication configuration

2. **Slow Search Performance**
   - Monitor OriaHS backend latency
   - Check network bandwidth
   - Consider increasing cache TTL

3. **Poor Search Results**
   - Verify query formulation
   - Check OriaHS backend indexing
   - Review search parameters

### Debug Commands

```bash
# Check MCP server health
curl http://localhost:8765/health

# Test MCP tool listing
curl http://localhost:8765/tools

# Monitor search metrics
curl http://localhost:8000/metrics | grep orya_semantic_search
```

This implementation provides a robust, production-ready semantic search capability that integrates seamlessly with the existing OryaAgent architecture while providing comprehensive observability and error handling.