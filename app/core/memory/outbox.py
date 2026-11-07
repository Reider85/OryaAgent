"""MemoryOutbox and drain-worker for async memory operations (B-21).

Provides a queue-based system for handling memory operations asynchronously.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.core.memory.sqlitestore import get_sqlite_store
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


class MemoryOperationType(Enum):
    """Types of memory operations."""
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    EXPORT = "export"
    IMPORT = "import"


class MemoryOperationStatus(Enum):
    """Status of memory operations."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class MemoryOperation:
    """Represents a memory operation in the outbox."""

    def __init__(
        self,
        operation_type: MemoryOperationType,
        session_id: str,
        data: Dict[str, Any],
        operation_id: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.operation_id = operation_id or f"op_{int(time.time() * 1000)}_{session_id[:8]}"
        self.operation_type = operation_type
        self.session_id = session_id
        self.data = data
        self.status = MemoryOperationStatus.PENDING
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_count = 0
        self.created_at = datetime.utcnow()
        self.processed_at: Optional[datetime] = None
        self.error_message: Optional[str] = None
        self.result: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert operation to dictionary."""
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type.value,
            "session_id": self.session_id,
            "data": self.data,
            "status": self.status.value,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat(),
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "error_message": self.error_message,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MemoryOperation:
        """Create operation from dictionary."""
        operation = cls(
            operation_type=MemoryOperationType(data["operation_type"]),
            session_id=data["session_id"],
            data=data["data"],
            operation_id=data["operation_id"],
            max_retries=data.get("max_retries", 3),
            retry_delay=data.get("retry_delay", 1.0),
        )
        operation.status = MemoryOperationStatus(data["status"])
        operation.retry_count = data.get("retry_count", 0)
        operation.created_at = datetime.fromisoformat(data["created_at"])
        operation.processed_at = (
            datetime.fromisoformat(data["processed_at"]) if data.get("processed_at") else None
        )
        operation.error_message = data.get("error_message")
        operation.result = data.get("result")
        return operation


class MemoryOutbox:
    """Queue for handling memory operations asynchronously."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._queue: asyncio.Queue[MemoryOperation] = asyncio.Queue(maxsize=max_size)
        self._processing = False
        self._drain_task: Optional[asyncio.Task] = None
        self._sqlite_store = None

    async def initialize(self) -> None:
        """Initialize the outbox with SQLite store."""
        self._sqlite_store = await get_sqlite_store()

    async def add_operation(
        self,
        operation_type: MemoryOperationType,
        session_id: str,
        data: Dict[str, Any],
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> str:
        """Add an operation to the outbox."""
        if not self._sqlite_store:
            await self.initialize()

        operation = MemoryOperation(
            operation_type=operation_type,
            session_id=session_id,
            data=data,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        # Add to queue
        try:
            self._queue.put_nowait(operation)
            logger.debug(f"Added operation {operation.operation_id} to outbox")
            return operation.operation_id
        except asyncio.QueueFull:
            logger.error(f"Outbox queue is full ({self.max_size} operations)")
            raise RuntimeError("Outbox queue is full")

    async def get_operation(self) -> Optional[MemoryOperation]:
        """Get the next operation to process."""
        try:
            return await self._queue.get()
        except asyncio.QueueEmpty:
            return None

    async def mark_operation_completed(self, operation: MemoryOperation, result: Any = None) -> None:
        """Mark an operation as completed."""
        operation.status = MemoryOperationStatus.COMPLETED
        operation.processed_at = datetime.utcnow()
        operation.result = result
        
        # Log completion
        logger.debug(f"Operation {operation.operation_id} completed")

    async def mark_operation_failed(self, operation: MemoryOperation, error: str) -> None:
        """Mark an operation as failed."""
        operation.status = MemoryOperationStatus.FAILED
        operation.processed_at = datetime.utcnow()
        operation.error_message = error
        
        # Log failure
        logger.error(f"Operation {operation.operation_id} failed: {error}")

    async def retry_operation(self, operation: MemoryOperation) -> bool:
        """Retry a failed operation."""
        if operation.retry_count >= operation.max_retries:
            await self.mark_operation_failed(
                operation, f"Max retries ({operation.max_retries}) exceeded"
            )
            return False

        operation.retry_count += 1
        operation.status = MemoryOperationStatus.RETRYING
        operation.processed_at = None
        operation.error_message = None
        
        # Add back to queue with delay
        await asyncio.sleep(operation.retry_delay)
        try:
            self._queue.put_nowait(operation)
            logger.info(f"Retrying operation {operation.operation_id} (attempt {operation.retry_count})")
            return True
        except asyncio.QueueFull:
            await self.mark_operation_failed(
                operation, "Queue full, cannot retry operation"
            )
            return False

    async def drain_queue(self, batch_size: int = 10, max_wait_time: float = 5.0) -> None:
        """Process operations from the queue in batches."""
        if self._processing:
            return

        self._processing = True
        logger.info("Starting memory outbox drain worker")

        try:
            while True:
                batch = []
                start_time = time.time()

                # Collect a batch of operations
                while len(batch) < batch_size and (time.time() - start_time) < max_wait_time:
                    operation = await self.get_operation()
                    if operation:
                        batch.append(operation)
                    else:
                        await asyncio.sleep(0.1)

                if batch:
                    await self._process_batch(batch)

                # Small delay before next batch
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info("Memory outbox drain worker cancelled")
        except Exception as e:
            logger.error(f"Memory outbox drain worker error: {e}")
        finally:
            self._processing = False

    async def _process_batch(self, batch: List[MemoryOperation]) -> None:
        """Process a batch of operations."""
        if not self._sqlite_store:
            await self.initialize()

        for operation in batch:
            try:
                operation.status = MemoryOperationStatus.PROCESSING
                logger.debug(f"Processing operation {operation.operation_id}")

                # Process based on operation type
                if operation.operation_type == MemoryOperationType.ADD:
                    result = await self._sqlite_store.add_memory(
                        operation.session_id,
                        operation.data["content"],
                        operation.data.get("metadata"),
                        operation.data.get("expires_in_hours"),
                    )
                elif operation.operation_type == MemoryOperationType.UPDATE:
                    result = await self._sqlite_store.supersede_memory(
                        operation.data["old_memory_id"],
                        operation.data["new_content"],
                        operation.data.get("new_metadata"),
                    )
                elif operation.operation_type == MemoryOperationType.DELETE:
                    result = await self._sqlite_store.forget_memory(operation.data["memory_id"])
                elif operation.operation_type == MemoryOperationType.SEARCH:
                    result = await self._sqlite_store.search_memories(
                        operation.session_id,
                        operation.data["query"],
                        operation.data.get("limit", 10),
                        operation.data.get("offset", 0),
                    )
                elif operation.operation_type == MemoryOperationType.EXPORT:
                    result = await self._sqlite_store.export_memories(operation.session_id)
                elif operation.operation_type == MemoryOperationType.IMPORT:
                    result = await self._sqlite_store.import_memories(
                        operation.session_id, operation.data["data"]
                    )
                else:
                    raise ValueError(f"Unknown operation type: {operation.operation_type}")

                await self.mark_operation_completed(operation, result)

            except Exception as e:
                logger.error(f"Error processing operation {operation.operation_id}: {e}")
                
                # Retry or mark as failed
                if not await self.retry_operation(operation):
                    await self.mark_operation_failed(operation, str(e))

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            "queue_size": self._queue.qsize(),
            "max_size": self.max_size,
            "is_processing": self._processing,
            "drain_task_running": self._drain_task and not self._drain_task.done(),
        }

    async def clear_queue(self) -> int:
        """Clear all pending operations."""
        cleared_count = 0
        while not self._queue.empty():
            try:
                operation = self._queue.get_nowait()
                await self.mark_operation_failed(
                    operation, "Operation cleared by user"
                )
                cleared_count += 1
            except asyncio.QueueEmpty:
                break
        
        logger.info(f"Cleared {cleared_count} operations from queue")
        return cleared_count

    async def stop_drain_worker(self) -> None:
        """Stop the drain worker."""
        if self._drain_task and not self._drain_task.done():
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
        
        self._drain_task = None
        logger.info("Memory outbox drain worker stopped")


# Global instance
_memory_outbox = None


async def get_memory_outbox() -> MemoryOutbox:
    """Get the global memory outbox instance."""
    global _memory_outbox
    if _memory_outbox is None:
        _memory_outbox = MemoryOutbox()
        await _memory_outbox.initialize()
    return _memory_outbox


async def initialize_memory_outbox(max_size: int = 1000) -> MemoryOutbox:
    """Initialize the memory outbox with custom parameters."""
    global _memory_outbox
    _memory_outbox = MemoryOutbox(max_size=max_size)
    await _memory_outbox.initialize()
    return _memory_outbox


async def start_drain_worker(
    interval: float = 1.0, batch_size: int = 10, max_wait_time: float = 5.0
) -> asyncio.Task:
    """Start the memory drain worker as a background task."""
    outbox = await get_memory_outbox()
    
    if outbox._drain_task and not outbox._drain_task.done():
        return outbox._drain_task

    async def worker():
        while True:
            try:
                await outbox.drain_queue(batch_size=batch_size, max_wait_time=max_wait_time)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Drain worker error: {e}")
                await asyncio.sleep(interval)

    outbox._drain_task = asyncio.create_task(worker())
    return outbox._drain_task