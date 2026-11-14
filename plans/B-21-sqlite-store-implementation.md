# B-21 Implementation Plan - SQLiteStore (L1, FTS5, SQLCipher) + MemoryOutbox + drain-worker

## Overview
B-21 implements the L1 memory layer using SQLite with FTS5 search and SQLCipher encryption, replacing the limited L0 MDStore for structured memory operations. This includes MemoryOutbox for async processing and a drain-worker for vector embeddings.

## Key Components to Implement

### 1. SQLiteStore Core (`app/core/memory/sqlite_store.py`)
- **Data Model**: Memory items with FTS5 indexing
- **Operations**: insert, search, forget, supersede, export, import
- **Encryption**: SQLCipher with OS keychain integration
- **Async**: All operations using aiosqlite

### 2. MemoryOutbox (`app/core/memory/outbox.py`) 
- **Queue System**: Async queue for memory operations
- **Batch Processing**: Drain operations in configurable batch sizes
- **Status Tracking**: Mark items as done/failed

### 3. Drain Worker (`app/core/memory/drain_worker.py`)
- **Background Processing**: Async task for embeddings and L2 sync
- **Embeddings**: Local bge-m3 model for vector generation
- **OriaHS Integration**: POST to L2 vector database with retry logic
- **Exponential Backoff**: Handle OriaHS unavailability

### 4. Keychain Integration (`app/core/keychain.py`)
- **OS Keychain Access**: Cross-platform secure key storage
- **Fallback**: Environment variable `ORYA_MEMORY_KEY`
- **Error Handling**: Graceful degradation with warnings

### 5. Embedding Service (`app/core/memory/embedding.py`)
- **bge-m3 Integration**: Local 1024-dimension embeddings
- **Performance**: CPU-optimized for cost efficiency
- **Caching**: Optional embedding result caching

## Implementation Phases

### Phase 1: Core SQLiteStore (1 day)
1. Set up SQLCipher database schema
2. Implement basic CRUD operations
3. Add FTS5 indexing with porter unicode61 tokenizer
4. Implement SQLCipher encryption with keychain integration
5. Create comprehensive test suite

### Phase 2: MemoryOutbox and Drain Worker (0.5 days)
1. Implement MemoryOutbox queue system
2. Create drain-worker background task
3. Add batch processing logic
4. Implement OriaHS integration with retry logic
5. Add exponential backoff for failed operations

### Phase 3: Integration and Testing (0.5 days)
1. Integration with existing MDStore (L0)
2. Update memory API endpoints
3. Add Chainlit slash commands
4. Performance testing and optimization
5. End-to-end testing

## Technical Requirements

### Database Schema
- `memory_items`: Main storage with encryption
- `memory_fts`: FTS5 virtual table for search
- `memory_outbox`: Async queue for processing
- Proper indexes for performance

### Security
- SQLCipher encryption at rest
- OS keychain integration (Keychain/secret-tool/DPAPI)
- Fallback to env var with warning
- No plaintext keys in code or logs

### Performance
- Async operations only (no blocking)
- Batch processing (50 items per batch)
- Local embeddings to avoid API costs
- Proper error handling and retries

## Acceptance Criteria
- ✅ SQLiteStore operations work with encrypted database
- ✅ FTS5 search returns relevant results
- ✅ MemoryOutbox processes items asynchronously
- ✅ Drain-worker successfully posts to OriaHS
- ✅ Export/import maintains data integrity
- ✅ All operations are async and non-blocking
- ✅ SQLCipher file unreadable without key

## Dependencies
- M-25 (MDStore) - existing L0 memory
- M-27 (Compactor) - L0→L1 compaction logic
- External: aiosqlite, sentence-transformers/fastembed, SQLCipher

## Risk Mitigation
- **Database corruption**: Regular backups and validation
- **Keychain failure**: Fallback to env var with clear warnings
- **OriaHS unavailability**: Robust retry with exponential backoff
- **Performance issues**: Proper indexing and batch processing

## Files to Create
- `app/core/memory/sqlite_store.py`
- `app/core/memory/outbox.py`
- `app/core/memory/drain_worker.py`
- `app/core/memory/embedding.py`
- `app/core/keychain.py`
- `tests/test_sqlite_store.py`
- `tests/test_memory_outbox.py`
- `tests/test_drain_worker.py`
- `tests/test_memory_integration.py`