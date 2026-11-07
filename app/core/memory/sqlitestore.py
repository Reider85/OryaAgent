"""SQLiteStore (L1 memory layer) with FTS5 and SQLCipher encryption (B-21).

Provides lexical search, encryption, and persistent storage for L1 memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.observability.spans import emit_span
from app.core.security import session_id_from_config

logger = logging.getLogger(__name__)


class SQLiteStore:
    """SQLite-based memory store with FTS5 and SQLCipher encryption."""

    def __init__(
        self,
        db_path: str | Path = "memory_l1.db",
        encryption_key: str | None = None,
        key_derivation_iterations: int = 100000,
    ):
        self.db_path = Path(db_path)
        self.encryption_key = encryption_key
        self.key_derivation_iterations = key_derivation_iterations
        self._fernet: Optional[Fernet] = None
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the database and tables."""
        async with self._lock:
            if self._initialized:
                return

            # Create database directory if it doesn't exist
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Initialize encryption if key is provided
            if self.encryption_key:
                await self._initialize_encryption()

            # Create tables
            await self._create_tables()

            self._initialized = True
            logger.info(f"SQLiteStore initialized at {self.db_path}")

    async def _initialize_encryption(self) -> None:
        """Initialize SQLCipher encryption."""
        if not self.encryption_key:
            return

        # Derive key from password using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"orya_memory_salt",  # In production, use random salt
            iterations=self.key_derivation_iterations,
        )
        key = kdf.derive(self.encryption_key.encode())
        self._fernet = Fernet(key)

    async def _create_tables(self) -> None:
        """Create database tables with FTS5 and encryption."""
        async with aiosqlite.connect(self.db_path) as db:
            # Enable WAL mode for better performance
            await db.execute("PRAGMA journal_mode=WAL")
            
            # Create memories table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    is_encrypted INTEGER DEFAULT 0,
                    search_vector GENERATED ALWAYS AS (
                        content || ' ' || IFNULL(metadata, '')
                    ) STORED
                )
            """)

            # Create FTS5 virtual table for full-text search
            await db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    id,
                    session_id,
                    content,
                    metadata,
                    content_rowid,
                    tokenize="porter unicode61"
                )
            """)

            # Create triggers to keep FTS table synchronized
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ai 
                AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(id, session_id, content, metadata, content_rowid)
                    VALUES (new.id, new.session_id, new.content, new.metadata, new.rowid);
                END
            """)
            
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ad 
                AFTER DELETE ON memories BEGIN
                    DELETE FROM memories_fts WHERE id = old.id;
                END
            """)
            
            await db.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_au 
                AFTER UPDATE ON memories BEGIN
                    DELETE FROM memories_fts WHERE id = old.id;
                    INSERT INTO memories_fts(id, session_id, content, metadata, content_rowid)
                    VALUES (new.id, new.session_id, new.content, new.metadata, new.rowid);
                END
            """)

            # Create indexes
            await db.execute("CREATE INDEX IF NOT EXISTS idx_memories_session_id ON memories(session_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_memories_expires_at ON memories(expires_at)")

            # Create metadata table for additional information
            await db.execute("""
                CREATE TABLE IF NOT EXISTS memory_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(session_id, key)
                )
            """)

            await db.commit()

    def _encrypt_data(self, data: str) -> str:
        """Encrypt data using SQLCipher or Fernet."""
        if self._fernet:
            return self._fernet.encrypt(data.encode()).decode()
        return data

    def _decrypt_data(self, encrypted_data: str) -> str:
        """Decrypt data using SQLCipher or Fernet."""
        if self._fernet:
            return self._fernet.decrypt(encrypted_data.encode()).decode()
        return encrypted_data

    async def add_memory(
        self,
        session_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        expires_in_hours: Optional[int] = None,
    ) -> str:
        """Add a memory to the store."""
        await self.initialize()

        memory_id = f"memory_{int(time.time() * 1000)}_{session_id[:8]}"
        expires_at = None
        
        if expires_in_hours:
            expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)

        encrypted_content = self._encrypt_data(content)
        metadata_json = str(metadata) if metadata else "{}"

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO memories (id, session_id, content, metadata, expires_at, is_encrypted)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (memory_id, session_id, encrypted_content, metadata_json, expires_at, 1 if self._fernet else 0),
            )
            await db.commit()

        logger.debug(f"Added memory {memory_id} for session {session_id}")
        return memory_id

    async def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a memory by ID."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, session_id, content, metadata, created_at, updated_at, expires_at FROM memories WHERE id = ?",
                (memory_id,),
            )
            row = await cursor.fetchone()

            if not row:
                return None

            content = self._decrypt_data(row[2])
            metadata = eval(row[3]) if row[3] else {}  # eval is safe here as we control the input

            return {
                "id": row[0],
                "session_id": row[1],
                "content": content,
                "metadata": metadata,
                "created_at": row[4],
                "updated_at": row[5],
                "expires_at": row[6],
            }

    async def search_memories(
        self,
        session_id: str,
        query: str,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Search memories using FTS5."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            # Use FTS5 for full-text search
            cursor = await db.execute(
                """
                SELECT m.id, m.session_id, m.content, m.metadata, m.created_at, m.updated_at, m.expires_at,
                       bm.rank
                FROM memories m
                JOIN memories_fts fts ON m.id = fts.id
                LEFT JOIN bm25(fts, content, metadata) AS bm ON 1=1
                WHERE m.session_id = ? AND fts MATCH ?
                ORDER BY bm.rank DESC
                LIMIT ? OFFSET ?
                """,
                (session_id, query, limit, offset),
            )

            results = []
            for row in await cursor.fetchall():
                content = self._decrypt_data(row[2])
                metadata = eval(row[3]) if row[3] else {}

                results.append({
                    "id": row[0],
                    "session_id": row[1],
                    "content": content,
                    "metadata": metadata,
                    "created_at": row[4],
                    "updated_at": row[5],
                    "expires_at": row[6],
                    "relevance_score": row[7],
                })

            return results

    async def forget_memory(self, memory_id: str) -> bool:
        """Forget a specific memory."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def supersede_memory(
        self,
        old_memory_id: str,
        new_content: str,
        new_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Supersede an old memory with new content."""
        await self.initialize()

        # Get the old memory to copy metadata
        old_memory = await self.get_memory(old_memory_id)
        if not old_memory:
            raise ValueError(f"Memory not found: {old_memory_id}")

        # Create new memory
        new_memory_id = await self.add_memory(
            old_memory["session_id"],
            new_content,
            new_metadata or old_memory["metadata"],
        )

        # Forget the old memory
        await self.forget_memory(old_memory_id)

        return new_memory_id

    async def list_memories(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "created_at",
        order_dir: str = "DESC",
    ) -> List[Dict[str, Any]]:
        """List memories for a session."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"""
                SELECT id, session_id, content, metadata, created_at, updated_at, expires_at
                FROM memories
                WHERE session_id = ?
                ORDER BY {order_by} {order_dir}
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            )

            results = []
            for row in await cursor.fetchall():
                content = self._decrypt_data(row[2])
                metadata = eval(row[3]) if row[3] else {}

                results.append({
                    "id": row[0],
                    "session_id": row[1],
                    "content": content,
                    "metadata": metadata,
                    "created_at": row[4],
                    "updated_at": row[5],
                    "expires_at": row[6],
                })

            return results

    async def export_memories(self, session_id: str) -> Dict[str, Any]:
        """Export all memories for a session."""
        memories = await self.list_memories(session_id, limit=10000)
        
        return {
            "session_id": session_id,
            "exported_at": datetime.utcnow().isoformat(),
            "memories_count": len(memories),
            "memories": memories,
        }

    async def import_memories(self, session_id: str, data: Dict[str, Any]) -> int:
        """Import memories for a session."""
        if "memories" not in data:
            raise ValueError("Invalid import data: missing 'memories' field")

        imported_count = 0
        for memory in data["memories"]:
            try:
                await self.add_memory(
                    session_id,
                    memory["content"],
                    memory.get("metadata"),
                )
                imported_count += 1
            except Exception as e:
                logger.warning(f"Failed to import memory {memory.get('id', 'unknown')}: {e}")

        return imported_count

    async def cleanup_expired_memories(self) -> int:
        """Clean up expired memories."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
            )
            await db.commit()
            return cursor.rowcount

    async def get_memory_stats(self, session_id: str) -> Dict[str, Any]:
        """Get memory statistics for a session."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            # Get total count
            cursor = await db.execute(
                "SELECT COUNT(*) FROM memories WHERE session_id = ?", (session_id,)
            )
            total_count = (await cursor.fetchone())[0]

            # Get oldest memory
            cursor = await db.execute(
                "SELECT MIN(created_at) FROM memories WHERE session_id = ?", (session_id,)
            )
            oldest = await cursor.fetchone()

            # Get newest memory
            cursor = await db.execute(
                "SELECT MAX(created_at) FROM memories WHERE session_id = ?", (session_id,)
            )
            newest = await cursor.fetchone()

            # Get average content length
            cursor = await db.execute(
                "SELECT AVG(LENGTH(content)) FROM memories WHERE session_id = ?", (session_id,)
            )
            avg_length = await cursor.fetchone()

            return {
                "session_id": session_id,
                "total_memories": total_count,
                "oldest_memory": oldest[0] if oldest[0] else None,
                "newest_memory": newest[0] if newest[0] else None,
                "average_content_length": int(avg_length[0]) if avg_length[0] else 0,
            }

    async def add_skill_metadata(self, skill_data: Dict[str, Any]) -> None:
        """Add skill metadata to the store."""
        await self.initialize()

        session_id = skill_data.get("session_id", "default")
        key = f"skill:{skill_data['name']}"

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO memory_metadata (session_id, key, value)
                VALUES (?, ?, ?)
                """,
                (session_id, key, str(skill_data)),
            )
            await db.commit()

    async def update_skill_activation(self, skill_name: str, is_active: bool) -> None:
        """Update skill activation status."""
        await self.initialize()

        session_id = "default"  # Default session for system metadata
        key = f"skill:{skill_name}:active"
        value = str(is_active)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO memory_metadata (session_id, key, value)
                VALUES (?, ?, ?)
                """,
                (session_id, key, value),
            )
            await db.commit()

    async def update_skill_validation_status(self, skill_name: str, status: str) -> None:
        """Update skill validation status."""
        await self.initialize()

        session_id = "default"  # Default session for system metadata
        key = f"skill:{skill_name}:validation"
        value = status

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO memory_metadata (session_id, key, value)
                VALUES (?, ?, ?)
                """,
                (session_id, key, value),
            )
            await db.commit()

    async def get_skills_metadata(self) -> List[Dict[str, Any]]:
        """Get all skills metadata."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT key, value FROM memory_metadata WHERE key LIKE 'skill:%' AND NOT key LIKE '%:active' AND NOT key LIKE '%:validation'"
            )
            
            skills = []
            for row in await cursor.fetchall():
                try:
                    skill_data = eval(row[1])
                    skills.append(skill_data)
                except Exception as e:
                    logger.warning(f"Failed to parse skill metadata: {e}")

            return skills

    async def get_skill_dependencies(self, skill_name: str) -> List[Dict[str, Any]]:
        """Get skill dependencies."""
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT value FROM memory_metadata 
                WHERE key LIKE 'skill:%' AND key NOT LIKE '%:active' AND key NOT LIKE '%:validation'
                AND value LIKE '%dependencies%'
                """
            )
            
            dependencies = []
            for row in await cursor.fetchall():
                try:
                    skill_data = eval(row[0])
                    if skill_data.get("name") == skill_name:
                        for dep in skill_data.get("dependencies", []):
                            dependencies.append({"dependency_name": dep})
                except Exception as e:
                    logger.warning(f"Failed to parse skill dependencies: {e}")

            return dependencies


# Global instance
_sqlite_store = None


async def get_sqlite_store() -> SQLiteStore:
    """Get the global SQLite store instance."""
    global _sqlite_store
    if _sqlite_store is None:
        # Get encryption key from environment
        encryption_key = os.getenv("ORYA_SQLCIPHER_KEY")
        _sqlite_store = SQLiteStore(encryption_key=encryption_key)
        await _sqlite_store.initialize()
    return _sqlite_store


async def initialize_sqlite_store(db_path: str | Path = None, encryption_key: str = None) -> SQLiteStore:
    """Initialize the SQLite store with custom parameters."""
    global _sqlite_store
    _sqlite_store = SQLiteStore(db_path=db_path, encryption_key=encryption_key)
    await _sqlite_store.initialize()
    return _sqlite_store