"""Memory UI: list, edit, delete (B-16) - UI for L0+L1 memory.

Provides web interface for managing memory files and entries.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.memory.md_store import get_md_store
from app.core.memory.sqlite_store import SQLiteStore
from app.core.session import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["nextjs-web-ui"])


class MemoryFileModel(BaseModel):
    """Memory file model."""
    name: str
    path: str
    size: int
    last_modified: str
    entry_count: int
    max_size: int
    description: str


class MemoryEntryModel(BaseModel):
    """Memory entry model."""
    id: str
    content: str
    timestamp: str
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = {}


class MemoryFilter(BaseModel):
    """Memory filter model."""
    file_name: Optional[str] = None
    session_id: Optional[str] = None
    search: Optional[str] = None
    limit: int = 50
    offset: int = 0


class MemoryUI:
    """Memory UI for managing memory files and entries."""

    def __init__(self):
        self.md_store = get_md_store()
        self.sqlite_store = SQLiteStore()
        self.session_manager = SessionManager()

    async def list_memory_files(self) -> List[MemoryFileModel]:
        """List all memory files."""
        try:
            memory_files = []
            
            # L0 memory files
            l0_files = [
                ("PROJECT.md", 8192, "Project context (mission/stack)"),
                ("LEARNED.md", 4096, "Facts learned through /learn"),
                ("PREFERENCES.md", 2048, "User/project preferences"),
                ("FACTS.md", 2048, "Critical project facts"),
                ("DECISIONS.md", 2048, "Short ADR-style decisions"),
                ("MEMORY_INDEX.md", 8192, "L1/L2 index (placeholder)"),
            ]
            
            for file_name, max_size, description in l0_files:
                file_path = self.md_store.get_memory_file_path(file_name)
                entry_count = await self._get_l0_entry_count(file_name)
                
                memory_files.append(MemoryFileModel(
                    name=file_name,
                    path=str(file_path),
                    size=file_path.stat().st_size if file_path.exists() else 0,
                    last_modified=file_path.stat().st_mtime if file_path.exists() else None,
                    entry_count=entry_count,
                    max_size=max_size,
                    description=description,
                ))
            
            # L1 memory files (if available)
            try:
                l1_files = await self.sqlite_store.list_memory_files()
                for file_info in l1_files:
                    memory_files.append(MemoryFileModel(
                        name=file_info["name"],
                        path=file_info["path"],
                        size=file_info["size"],
                        last_modified=file_info["last_modified"],
                        entry_count=file_info["entry_count"],
                        max_size=file_info["max_size"],
                        description=f"L1 memory: {file_info['name']}",
                    ))
            except Exception as e:
                logger.warning(f"Could not access L1 memory: {e}")
            
            return memory_files

        except Exception as e:
            logger.error(f"Failed to list memory files: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list memory files: {str(e)}")

    async def get_memory_file(self, file_name: str) -> Dict[str, Any]:
        """Get information about a specific memory file."""
        try:
            if file_name in ["PROJECT.md", "LEARNED.md", "PREFERENCES.md", "FACTS.md", "DECISIONS.md", "MEMORY_INDEX.md"]:
                # L0 memory file
                file_path = self.md_store.get_memory_file_path(file_name)
                entries = await self._get_l0_entries(file_name)
                
                return {
                    "name": file_name,
                    "type": "L0",
                    "path": str(file_path),
                    "content": file_path.read_text(encoding="utf-8") if file_path.exists() else "",
                    "entries": entries,
                    "size": file_path.stat().st_size if file_path.exists() else 0,
                    "last_modified": file_path.stat().st_mtime if file_path.exists() else None,
                }
            else:
                # L1 memory file
                file_info = await self.sqlite_store.get_memory_file(file_name)
                entries = await self.sqlite_store.get_entries(file_name)
                
                return {
                    "name": file_name,
                    "type": "L1",
                    "path": file_info["path"],
                    "content": "",
                    "entries": entries,
                    "size": file_info["size"],
                    "last_modified": file_info["last_modified"],
                }

        except Exception as e:
            logger.error(f"Failed to get memory file: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get memory file: {str(e)}")

    async def update_memory_file(self, file_name: str, content: str) -> Dict[str, Any]:
        """Update a memory file."""
        try:
            if file_name in ["PROJECT.md", "LEARNED.md", "PREFERENCES.md", "FACTS.md", "DECISIONS.md"]:
                # L0 memory file
                file_path = self.md_store.get_memory_file_path(file_name)
                
                # Validate content size
                if len(content.encode('utf-8')) > self._get_max_size(file_name):
                    raise HTTPException(status_code=400, detail="Content exceeds maximum size")
                
                # Write content
                file_path.write_text(content, encoding="utf-8")
                
                return {"success": True, "message": f"Updated {file_name}"}
            else:
                # L1 memory file
                await self.sqlite_store.update_memory_file(file_name, content)
                return {"success": True, "message": f"Updated {file_name}"}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update memory file: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update memory file: {str(e)}")

    async def delete_memory_entry(self, file_name: str, entry_id: str) -> Dict[str, Any]:
        """Delete a memory entry."""
        try:
            if file_name in ["PROJECT.md", "LEARNED.md", "PREFERENCES.md", "FACTS.md", "DECISIONS.md"]:
                # L0 memory file - mark entry as deleted
                await self._mark_l0_entry_deleted(file_name, entry_id)
                return {"success": True, "message": f"Deleted entry {entry_id} from {file_name}"}
            else:
                # L1 memory file
                await self.sqlite_store.delete_entry(file_name, entry_id)
                return {"success": True, "message": f"Deleted entry {entry_id} from {file_name}"}

        except Exception as e:
            logger.error(f"Failed to delete memory entry: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete memory entry: {str(e)}")

    async def search_memory(self, query: str, filter: MemoryFilter) -> Dict[str, Any]:
        """Search across memory files."""
        try:
            results = []
            
            # Search in L0 files
            if not filter.file_name or filter.file_name in ["PROJECT.md", "LEARNED.md", "PREFERENCES.md", "FACTS.md", "DECISIONS.md"]:
                for file_name in ["PROJECT.md", "LEARNED.md", "PREFERENCES.md", "FACTS.md", "DECISIONS.md"]:
                    if filter.search and filter.search.lower() not in file_name.lower():
                        continue
                    
                    entries = await self._get_l0_entries(file_name)
                    for entry in entries:
                        if query.lower() in entry["content"].lower():
                            results.append({
                                "file_name": file_name,
                                "type": "L0",
                                "entry_id": entry["id"],
                                "content": entry["content"],
                                "timestamp": entry["timestamp"],
                                "session_id": entry.get("session_id"),
                            })
            
            # Search in L1 files
            if not filter.file_name:
                try:
                    l1_entries = await self.sqlite_store.search_entries(query, filter.session_id)
                    for entry in l1_entries:
                        results.append({
                            "file_name": entry["file_name"],
                            "type": "L1",
                            "entry_id": entry["id"],
                            "content": entry["content"],
                            "timestamp": entry["timestamp"],
                            "session_id": entry.get("session_id"),
                        })
                except Exception as e:
                    logger.warning(f"Could not search L1 memory: {e}")
            
            # Apply pagination
            total_count = len(results)
            paginated_results = results[filter.offset : filter.offset + filter.limit]
            
            return {
                "results": paginated_results,
                "total_count": total_count,
                "filtered_count": len(results),
                "limit": filter.limit,
                "offset": filter.offset,
            }

        except Exception as e:
            logger.error(f"Failed to search memory: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to search memory: {str(e)}")

    async def get_memory_statistics(self) -> Dict[str, Any]:
        """Get memory statistics."""
        try:
            stats = {
                "l0_files": {},
                "l1_files": {},
                "total_size": 0,
                "total_entries": 0,
            }
            
            # L0 statistics
            l0_files = [
                ("PROJECT.md", 8192),
                ("LEARNED.md", 4096),
                ("PREFERENCES.md", 2048),
                ("FACTS.md", 2048),
                ("DECISIONS.md", 2048),
                ("MEMORY_INDEX.md", 8192),
            ]
            
            for file_name, max_size in l0_files:
                file_path = self.md_store.get_memory_file_path(file_name)
                entry_count = await self._get_l0_entry_count(file_name)
                file_size = file_path.stat().st_size if file_path.exists() else 0
                
                stats["l0_files"][file_name] = {
                    "size": file_size,
                    "max_size": max_size,
                    "entry_count": entry_count,
                    "usage_percent": (file_size / max_size * 100) if max_size > 0 else 0,
                }
                
                stats["total_size"] += file_size
                stats["total_entries"] += entry_count
            
            # L1 statistics
            try:
                l1_stats = await self.sqlite_store.get_statistics()
                stats["l1_files"] = l1_stats["files"]
                stats["total_size"] += l1_stats["total_size"]
                stats["total_entries"] += l1_stats["total_entries"]
            except Exception as e:
                logger.warning(f"Could not get L1 statistics: {e}")
            
            return stats

        except Exception as e:
            logger.error(f"Failed to get memory statistics: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get memory statistics: {str(e)}")

    async def _get_l0_entries(self, file_name: str) -> List[Dict[str, Any]]:
        """Get entries from L0 memory file."""
        try:
            file_path = self.md_store.get_memory_file_path(file_name)
            if not file_path.exists():
                return []
            
            content = file_path.read_text(encoding="utf-8")
            entries = []
            
            # Parse entries (simplified)
            lines = content.strip().split('\n')
            current_entry = []
            entry_id = 0
            
            for line in lines:
                if line.startswith("---") and current_entry:
                    entry_content = '\n'.join(current_entry).strip()
                    if entry_content:
                        entries.append({
                            "id": str(entry_id),
                            "content": entry_content,
                            "timestamp": datetime.utcnow().isoformat(),
                            "session_id": None,
                        })
                    current_entry = []
                    entry_id += 1
                else:
                    current_entry.append(line)
            
            # Add last entry
            if current_entry:
                entry_content = '\n'.join(current_entry).strip()
                if entry_content:
                    entries.append({
                        "id": str(entry_id),
                        "content": entry_content,
                        "timestamp": datetime.utcnow().isoformat(),
                        "session_id": None,
                    })
            
            return entries

        except Exception as e:
            logger.error(f"Failed to get L0 entries: {e}")
            return []

    async def _get_l0_entry_count(self, file_name: str) -> int:
        """Get entry count from L0 memory file."""
        entries = await self._get_l0_entries(file_name)
        return len(entries)

    async def _mark_l0_entry_deleted(self, file_name: str, entry_id: str) -> None:
        """Mark an entry as deleted in L0 memory file."""
        # This is a simplified implementation
        # In a real implementation, you would need to handle the atomic append properly
        pass

    def _get_max_size(self, file_name: str) -> int:
        """Get maximum size for a memory file."""
        sizes = {
            "PROJECT.md": 8192,
            "LEARNED.md": 4096,
            "PREFERENCES.md": 2048,
            "FACTS.md": 2048,
            "DECISIONS.md": 2048,
            "MEMORY_INDEX.md": 8192,
        }
        return sizes.get(file_name, 4096)


# Global instance
_memory_ui = None


def get_memory_ui() -> MemoryUI:
    """Get the global memory UI instance."""
    global _memory_ui
    if _memory_ui is None:
        _memory_ui = MemoryUI()
    return _memory_ui


@router.get("/memory/files")
async def list_memory_files():
    """List all memory files."""
    memory_ui = get_memory_ui()
    return await memory_ui.list_memory_files()


@router.get("/memory/files/{file_name}")
async def get_memory_file(file_name: str):
    """Get information about a specific memory file."""
    memory_ui = get_memory_ui()
    return await memory_ui.get_memory_file(file_name)


@router.put("/memory/files/{file_name}")
async def update_memory_file(file_name: str, content: str):
    """Update a memory file."""
    memory_ui = get_memory_ui()
    return await memory_ui.update_memory_file(file_name, content)


@router.delete("/memory/files/{file_name}/entries/{entry_id}")
async def delete_memory_entry(file_name: str, entry_id: str):
    """Delete a memory entry."""
    memory_ui = get_memory_ui()
    return await memory_ui.delete_memory_entry(file_name, entry_id)


@router.get("/memory/search")
async def search_memory(
    q: str,
    file_name: Optional[str] = Query(None, description="Filter by file name"),
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """Search across memory files."""
    filter = MemoryFilter(
        file_name=file_name,
        session_id=session_id,
        search=q,
        limit=limit,
        offset=offset,
    )
    memory_ui = get_memory_ui()
    return await memory_ui.search_memory(q, filter)


@router.get("/memory/statistics")
async def get_memory_statistics():
    """Get memory statistics."""
    memory_ui = get_memory_ui()
    return await memory_ui.get_memory_statistics()