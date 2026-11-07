"""SQLiteStore: lightweight storage for hooks audit and skills (B-21).

Provides simple SQLite-based storage for hooks audit logs and skills metadata.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiosqlite

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class SQLiteStore:
    """Simple SQLite-based key-value store with support for JSON data."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """Initialize the SQLite store."""
        settings = get_settings()
        
        # Use default path if not provided
        if db_path is None:
            db_path = Path(settings.data_dir) / "orya_store.db"
        
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        
        # Ensure data directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database tables
        self._init_tables()

    def _init_tables(self):
        """Initialize database tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hooks_audit (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    tool_name TEXT,
                    hook_name TEXT,
                    hook_type TEXT,
                    success BOOLEAN,
                    message TEXT,
                    duration_ms REAL,
                    timestamp TEXT,
                    metadata TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills_metadata (
                    name TEXT PRIMARY KEY,
                    description TEXT,
                    version TEXT,
                    author TEXT,
                    category TEXT,
                    tags TEXT,
                    tools TEXT,
                    hooks TEXT,
                    dependencies TEXT,
                    metadata TEXT,
                    is_active BOOLEAN,
                    activated_at TEXT,
                    deactivated_at TEXT,
                    validation_status TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills_dependencies (
                    skill_name TEXT,
                    dependency_name TEXT,
                    dependency_type TEXT,
                    PRIMARY KEY (skill_name, dependency_name)
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_hooks_audit_session_id 
                ON hooks_audit(session_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_hooks_audit_tool_name 
                ON hooks_audit(tool_name)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_hooks_audit_hook_name 
                ON hooks_audit(hook_name)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_hooks_audit_timestamp 
                ON hooks_audit(timestamp)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_skills_metadata_category 
                ON skills_metadata(category)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_skills_metadata_is_active 
                ON skills_metadata(is_active)
            """)
            
            conn.commit()

    async def _execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute a query and return results as dictionaries."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def _execute_insert(self, query: str, params: tuple) -> str:
        """Execute an insert query and return the row ID."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor.lastrowid

    async def _execute_update(self, query: str, params: tuple) -> int:
        """Execute an update query and return the number of affected rows."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor.rowcount

    async def _execute_delete(self, query: str, params: tuple) -> int:
        """Execute a delete query and return the number of affected rows."""
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor.rowcount

    # Hooks Audit Methods
    async def add_hook_execution(self, execution_data: Dict[str, Any]) -> str:
        """Add a hook execution record."""
        query = """
            INSERT INTO hooks_audit (
                id, session_id, tool_name, hook_name, hook_type, 
                success, message, duration_ms, timestamp, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        params = (
            execution_data.get("id"),
            execution_data.get("session_id"),
            execution_data.get("tool_name"),
            execution_data.get("hook_name"),
            execution_data.get("hook_type"),
            execution_data.get("success", False),
            execution_data.get("message"),
            execution_data.get("duration_ms", 0.0),
            execution_data.get("timestamp"),
            execution_data.get("metadata", {}),
        )
        
        await self._execute_insert(query, params)
        return execution_data.get("id", "")

    async def get_hook_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific hook execution record."""
        query = "SELECT * FROM hooks_audit WHERE id = ?"
        results = await self._execute_query(query, (execution_id,))
        return results[0] if results else None

    async def get_hook_executions(
        self,
        session_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        hook_name: Optional[str] = None,
        hook_type: Optional[str] = None,
        success: Optional[bool] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get hook execution records with optional filtering."""
        query_parts = ["SELECT * FROM hooks_audit WHERE 1=1"]
        params = []
        
        if session_id:
            query_parts.append("AND session_id = ?")
            params.append(session_id)
        
        if tool_name:
            query_parts.append("AND tool_name = ?")
            params.append(tool_name)
        
        if hook_name:
            query_parts.append("AND hook_name = ?")
            params.append(hook_name)
        
        if hook_type:
            query_parts.append("AND hook_type = ?")
            params.append(hook_type)
        
        if success is not None:
            query_parts.append("AND success = ?")
            params.append(success)
        
        if start_date:
            query_parts.append("AND timestamp >= ?")
            params.append(start_date)
        
        if end_date:
            query_parts.append("AND timestamp <= ?")
            params.append(end_date)
        
        query_parts.append("ORDER BY timestamp DESC")
        
        if limit:
            query_parts.append("LIMIT ?")
            params.append(limit)
        
        if offset:
            query_parts.append("OFFSET ?")
            params.append(offset)
        
        query = " ".join(query_parts)
        return await self._execute_query(query, tuple(params))

    async def delete_hook_execution(self, execution_id: str) -> bool:
        """Delete a hook execution record."""
        query = "DELETE FROM hooks_audit WHERE id = ?"
        result = await self._execute_delete(query, (execution_id,))
        return result > 0

    async def delete_old_hook_executions(self, older_than_days: int) -> int:
        """Delete hook execution records older than specified days."""
        cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)
        query = "DELETE FROM hooks_audit WHERE timestamp < ?"
        result = await self._execute_delete(query, (cutoff_date.isoformat(),))
        return result

    # Skills Metadata Methods
    async def add_skill_metadata(self, skill_data: Dict[str, Any]) -> str:
        """Add skill metadata."""
        query = """
            INSERT OR REPLACE INTO skills_metadata (
                name, description, version, author, category, tags,
                tools, hooks, dependencies, metadata, is_active,
                activated_at, deactivated_at, validation_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        params = (
            skill_data.get("name"),
            skill_data.get("description"),
            skill_data.get("version"),
            skill_data.get("author"),
            skill_data.get("category"),
            skill_data.get("tags", []),
            skill_data.get("tools", []),
            skill_data.get("hooks", []),
            skill_data.get("dependencies", []),
            skill_data.get("metadata", {}),
            skill_data.get("is_active", False),
            skill_data.get("activated_at"),
            skill_data.get("deactivated_at"),
            skill_data.get("validation_status", "unknown"),
        )
        
        await self._execute_insert(query, params)
        return skill_data.get("name", "")

    async def get_skill_metadata(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Get skill metadata."""
        query = "SELECT * FROM skills_metadata WHERE name = ?"
        results = await self._execute_query(query, (skill_name,))
        return results[0] if results else None

    async def get_skills_metadata(
        self,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get skills metadata with optional filtering."""
        query_parts = ["SELECT * FROM skills_metadata WHERE 1=1"]
        params = []
        
        if category:
            query_parts.append("AND category = ?")
            params.append(category)
        
        if is_active is not None:
            query_parts.append("AND is_active = ?")
            params.append(is_active)
        
        query_parts.append("ORDER BY name")
        
        if limit:
            query_parts.append("LIMIT ?")
            params.append(limit)
        
        if offset:
            query_parts.append("OFFSET ?")
            params.append(offset)
        
        query = " ".join(query_parts)
        return await self._execute_query(query, tuple(params))

    async def update_skill_activation(
        self, 
        skill_name: str, 
        activate: bool, 
        timestamp: Optional[str] = None
    ) -> bool:
        """Update skill activation status."""
        if timestamp is None:
            timestamp = datetime.utcnow().isoformat()
        
        if activate:
            query = """
                UPDATE skills_metadata 
                SET is_active = ?, activated_at = ?, deactivated_at = NULL 
                WHERE name = ?
            """
            params = (True, timestamp, skill_name)
        else:
            query = """
                UPDATE skills_metadata 
                SET is_active = ?, deactivated_at = ?, activated_at = NULL 
                WHERE name = ?
            """
            params = (False, timestamp, skill_name)
        
        result = await self._execute_update(query, params)
        return result > 0

    async def update_skill_validation_status(
        self, 
        skill_name: str, 
        validation_status: str
    ) -> bool:
        """Update skill validation status."""
        query = "UPDATE skills_metadata SET validation_status = ? WHERE name = ?"
        result = await self._execute_update(query, (validation_status, skill_name))
        return result > 0

    async def delete_skill_metadata(self, skill_name: str) -> bool:
        """Delete skill metadata."""
        query = "DELETE FROM skills_metadata WHERE name = ?"
        result = await self._execute_delete(query, (skill_name,))
        return result > 0

    # Skills Dependencies Methods
    async def add_skill_dependency(
        self, 
        skill_name: str, 
        dependency_name: str, 
        dependency_type: str = "required"
    ) -> bool:
        """Add a skill dependency."""
        query = """
            INSERT OR REPLACE INTO skills_dependencies 
            (skill_name, dependency_name, dependency_type) 
            VALUES (?, ?, ?)
        """
        result = await self._execute_update(query, (skill_name, dependency_name, dependency_type))
        return result > 0

    async def get_skill_dependencies(self, skill_name: str) -> List[Dict[str, Any]]:
        """Get dependencies for a skill."""
        query = """
            SELECT dependency_name, dependency_type 
            FROM skills_dependencies 
            WHERE skill_name = ?
        """
        return await self._execute_query(query, (skill_name,))

    async def delete_skill_dependency(self, skill_name: str, dependency_name: str) -> bool:
        """Delete a skill dependency."""
        query = "DELETE FROM skills_dependencies WHERE skill_name = ? AND dependency_name = ?"
        result = await self._execute_delete(query, (skill_name, dependency_name))
        return result > 0

    async def get_all_skills_dependencies(self) -> List[Dict[str, Any]]:
        """Get all skills dependencies."""
        query = """
            SELECT skill_name, dependency_name, dependency_type 
            FROM skills_dependencies 
            ORDER BY skill_name, dependency_name
        """
        return await self._execute_query(query)

    # Utility Methods
    async def get_hooks_statistics(self, days: int = 7) -> Dict[str, Any]:
        """Get hooks execution statistics."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        cutoff_str = cutoff_date.isoformat()
        
        # Total executions
        query = "SELECT COUNT(*) as total FROM hooks_audit WHERE timestamp >= ?"
        results = await self._execute_query(query, (cutoff_str,))
        total_executions = results[0]["total"] if results else 0
        
        # Success rate
        query = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                AVG(duration_ms) as avg_duration
            FROM hooks_audit 
            WHERE timestamp >= ?
        """
        results = await self._execute_query(query, (cutoff_str,))
        stats = results[0] if results else {}
        
        # Tool breakdown
        query = """
            SELECT 
                tool_name,
                COUNT(*) as total,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                AVG(duration_ms) as avg_duration
            FROM hooks_audit 
            WHERE timestamp >= ?
            GROUP BY tool_name
            ORDER BY total DESC
        """
        tool_breakdown = await self._execute_query(query, (cutoff_str,))
        
        return {
            "total_executions": total_executions,
            "successful_executions": stats.get("successful", 0),
            "success_rate": stats.get("successful", 0) / total_executions if total_executions > 0 else 0,
            "average_duration_ms": stats.get("avg_duration", 0),
            "tool_breakdown": tool_breakdown,
        }

    async def get_skills_statistics(self) -> Dict[str, Any]]:
        """Get skills metadata statistics."""
        query = "SELECT category, COUNT(*) as count FROM skills_metadata GROUP BY category"
        category_stats = await self._execute_query(query)
        
        query = "SELECT is_active, COUNT(*) as count FROM skills_metadata GROUP BY is_active"
        active_stats = await self._execute_query(query)
        
        query = "SELECT validation_status, COUNT(*) as count FROM skills_metadata GROUP BY validation_status"
        validation_stats = await self._execute_query(query)
        
        return {
            "total_skills": sum(stat["count"] for stat in active_stats),
            "active_skills": next((stat["count"] for stat in active_stats if stat["is_active"]), 0),
            "inactive_skills": next((stat["count"] for stat in active_stats if not stat["is_active"]), 0),
            "categories": category_stats,
            "validation_status": validation_stats,
        }

    async def cleanup_old_data(self, max_days: int = 90):
        """Clean up old data from the store."""
        # Delete old hook executions
        deleted_hooks = await self.delete_old_hook_executions(max_days)
        
        # Note: Skills metadata is kept indefinitely as it's small
        
        logger.info(f"Cleaned up {deleted_hooks} old hook execution records")
        return {"deleted_hook_executions": deleted_hooks}


# Global instance
_sqlite_store = None


def get_sqlite_store() -> SQLiteStore:
    """Get the global SQLite store instance."""
    global _sqlite_store
    if _sqlite_store is None:
        _sqlite_store = SQLiteStore()
    return _sqlite_store


# Export the main functions for use in other modules
async def add_hook_execution(execution_data: Dict[str, Any]) -> str:
    """Add a hook execution record."""
    store = get_sqlite_store()
    return await store.add_hook_execution(execution_data)


async def get_hook_execution(execution_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific hook execution record."""
    store = get_sqlite_store()
    return await store.get_hook_execution(execution_id)


async def get_hook_executions(**kwargs) -> List[Dict[str, Any]]:
    """Get hook execution records with optional filtering."""
    store = get_sqlite_store()
    return await store.get_hook_executions(**kwargs)


async def delete_hook_execution(execution_id: str) -> bool:
    """Delete a hook execution record."""
    store = get_sqlite_store()
    return await store.delete_hook_execution(execution_id)


async def add_skill_metadata(skill_data: Dict[str, Any]) -> str:
    """Add skill metadata."""
    store = get_sqlite_store()
    return await store.add_skill_metadata(skill_data)


async def get_skill_metadata(skill_name: str) -> Optional[Dict[str, Any]]:
    """Get skill metadata."""
    store = get_sqlite_store()
    return await store.get_skill_metadata(skill_name)


async def get_skills_metadata(**kwargs) -> List[Dict[str, Any]]:
    """Get skills metadata with optional filtering."""
    store = get_sqlite_store()
    return await store.get_skills_metadata(**kwargs)


async def update_skill_activation(skill_name: str, activate: bool) -> bool:
    """Update skill activation status."""
    store = get_sqlite_store()
    return await store.update_skill_activation(skill_name, activate)


async def update_skill_validation_status(skill_name: str, validation_status: str) -> bool:
    """Update skill validation status."""
    store = get_sqlite_store()
    return await store.update_skill_validation_status(skill_name, validation_status)


async def get_skill_dependencies(skill_name: str) -> List[Dict[str, Any]]:
    """Get dependencies for a skill."""
    store = get_sqlite_store()
    return await store.get_skill_dependencies(skill_name)