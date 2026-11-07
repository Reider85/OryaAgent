"""Memory UI: import/export (B-17) - JSON import/export.

Provides functionality to import and export memory data in JSON format.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.memory.md_store import get_md_store
from app.core.memory.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["nextjs-web-ui"])


class MemoryExportModel(BaseModel):
    """Memory export model."""
    timestamp: str
    version: str
    l0_files: Dict[str, str]
    l1_files: List[Dict[str, Any]]


class MemoryImportModel(BaseModel):
    """Memory import model."""
    source_file: str
    merge_mode: str = "overwrite"  # "overwrite", "merge", "skip_existing"
    validate_only: bool = False


class MemoryImportExport:
    """Memory import/export functionality."""

    def __init__(self):
        self.md_store = get_md_store()
        self.sqlite_store = SQLiteStore()

    async def export_memory_data(self, include_l1: bool = True) -> MemoryExportModel:
        """Export all memory data to JSON format."""
        try:
            export_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "version": "1.0.0",
                "l0_files": {},
                "l1_files": [],
            }

            # Export L0 files
            l0_files = [
                "PROJECT.md",
                "LEARNED.md",
                "PREFERENCES.md",
                "FACTS.md",
                "DECISIONS.md",
                "MEMORY_INDEX.md",
            ]

            for file_name in l0_files:
                file_path = self.md_store.get_memory_file_path(file_name)
                if file_path.exists():
                    export_data["l0_files"][file_name] = file_path.read_text(encoding="utf-8")

            # Export L1 files
            if include_l1:
                try:
                    l1_files = await self.sqlite_store.list_memory_files()
                    for file_info in l1_files:
                        entries = await self.sqlite_store.get_entries(file_info["name"])
                        export_data["l1_files"].append({
                            "name": file_info["name"],
                            "entries": entries,
                            "metadata": {
                                "size": file_info["size"],
                                "last_modified": file_info["last_modified"],
                            },
                        })
                except Exception as e:
                    logger.warning(f"Could not export L1 memory: {e}")

            return MemoryExportModel(**export_data)

        except Exception as e:
            logger.error(f"Failed to export memory data: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to export memory data: {str(e)}")

    async def import_memory_data(self, import_data: MemoryImportModel) -> Dict[str, Any]:
        """Import memory data from JSON format."""
        try:
            if import_data.validate_only:
                return await self._validate_import_data(import_data.source_file)

            # Parse import data
            if isinstance(import_data.source_file, str):
                # JSON string
                data = json.loads(import_data.source_file)
            else:
                # Uploaded file
                content = import_data.source_file.read()
                data = json.loads(content)

            # Validate data structure
            if not self._validate_export_structure(data):
                raise HTTPException(status_code=400, detail="Invalid export data structure")

            results = {
                "l0_files": {"imported": 0, "skipped": 0, "errors": []},
                "l1_files": {"imported": 0, "skipped": 0, "errors": []},
                "total_entries": 0,
            }

            # Import L0 files
            for file_name, content in data.get("l0_files", {}).items():
                try:
                    if import_data.merge_mode == "skip_existing" and self._l0_file_exists(file_name):
                        results["l0_files"]["skipped"] += 1
                        continue

                    # Validate content size
                    if len(content.encode('utf-8')) > self._get_l0_max_size(file_name):
                        results["l0_files"]["errors"].append(f"File {file_name} exceeds maximum size")
                        continue

                    # Import file
                    file_path = self.md_store.get_memory_file_path(file_name)
                    file_path.write_text(content, encoding="utf-8")
                    results["l0_files"]["imported"] += 1

                except Exception as e:
                    results["l0_files"]["errors"].append(f"Failed to import {file_name}: {str(e)}")

            # Import L1 files
            for file_info in data.get("l1_files", []):
                try:
                    file_name = file_info.get("name")
                    if not file_name:
                        continue

                    if import_data.merge_mode == "skip_existing" and await self._l1_file_exists(file_name):
                        results["l1_files"]["skipped"] += 1
                        continue

                    # Import entries
                    entries = file_info.get("entries", [])
                    for entry in entries:
                        await self.sqlite_store.create_entry(
                            file_name,
                            entry.get("content", ""),
                            entry.get("metadata", {})
                        )
                        results["total_entries"] += 1

                    results["l1_files"]["imported"] += 1

                except Exception as e:
                    results["l1_files"]["errors"].append(f"Failed to import L1 file {file_name}: {str(e)}")

            return results

        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to import memory data: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to import memory data: {str(e)}")

    async def import_from_file(self, file: UploadFile, merge_mode: str = "overwrite") -> Dict[str, Any]:
        """Import memory data from uploaded file."""
        try:
            # Read file content
            content = await file.read()
            if file.filename and not file.filename.endswith('.json'):
                raise HTTPException(status_code=400, detail="Only JSON files are supported")

            # Parse JSON
            data = json.loads(content)

            # Create import model
            import_model = MemoryImportModel(
                source_file=data,
                merge_mode=merge_mode,
                validate_only=False,
            )

            # Import data
            return await self.import_memory_data(import_model)

        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to import from file: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to import from file: {str(e)}")

    async def export_to_file(self, include_l1: bool = True) -> str:
        """Export memory data to JSON string."""
        try:
            export_data = await self.export_memory_data(include_l1)
            return json.dumps(export_data.model_dump(), indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Failed to export to file: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to export to file: {str(e)}")

    async def _validate_import_data(self, source_data: str) -> Dict[str, Any]:
        """Validate import data without actually importing."""
        try:
            if isinstance(source_data, str):
                data = json.loads(source_data)
            else:
                content = source_data.read()
                data = json.loads(content)

            validation_result = {
                "valid": True,
                "errors": [],
                "warnings": [],
                "summary": {
                    "l0_files": len(data.get("l0_files", {})),
                    "l1_files": len(data.get("l1_files", [])),
                    "total_entries": 0,
                },
            }

            # Validate L0 files
            for file_name, content in data.get("l0_files", {}).items():
                if len(content.encode('utf-8')) > self._get_l0_max_size(file_name):
                    validation_result["errors"].append(f"File {file_name} exceeds maximum size")

            # Validate L1 files
            for file_info in data.get("l1_files", []):
                entries = file_info.get("entries", [])
                validation_result["summary"]["total_entries"] += len(entries)

                # Check for required fields
                for entry in entries:
                    if not entry.get("content"):
                        validation_result["warnings"].append("Entry found with empty content")

            if validation_result["errors"]:
                validation_result["valid"] = False

            return validation_result

        except json.JSONDecodeError:
            return {"valid": False, "errors": ["Invalid JSON format"]}
        except Exception as e:
            return {"valid": False, "errors": [f"Validation failed: {str(e)}"]}

    def _validate_export_structure(self, data: Dict[str, Any]) -> bool:
        """Validate export data structure."""
        required_keys = {"timestamp", "version", "l0_files", "l1_files"}
        
        if not all(key in data for key in required_keys):
            return False

        if not isinstance(data["l0_files"], dict):
            return False

        if not isinstance(data["l1_files"], list):
            return False

        return True

    def _l0_file_exists(self, file_name: str) -> bool:
        """Check if L0 file exists."""
        file_path = self.md_store.get_memory_file_path(file_name)
        return file_path.exists()

    async def _l1_file_exists(self, file_name: str) -> bool:
        """Check if L1 file exists."""
        try:
            files = await self.sqlite_store.list_memory_files()
            return any(f["name"] == file_name for f in files)
        except Exception:
            return False

    def _get_l0_max_size(self, file_name: str) -> int:
        """Get maximum size for L0 file."""
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
_memory_import_export = None


def get_memory_import_export() -> MemoryImportExport:
    """Get the global memory import/export instance."""
    global _memory_import_export
    if _memory_import_export is None:
        _memory_import_export = MemoryImportExport()
    return _memory_import_export


@router.get("/memory/export")
async def export_memory(include_l1: bool = True):
    """Export all memory data."""
    memory_import_export = get_memory_import_export()
    return await memory_import_export.export_memory_data(include_l1)


@router.post("/memory/export/download")
async def download_export(include_l1: bool = True):
    """Export memory data and return as downloadable file."""
    memory_import_export = get_memory_import_export()
    json_content = await memory_import_export.export_to_file(include_l1)
    
    return {
        "content": json_content,
        "filename": f"memory_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        "content_type": "application/json",
    }


@router.post("/memory/import")
async def import_memory_data(import_data: MemoryImportModel):
    """Import memory data from JSON format."""
    memory_import_export = get_memory_import_export()
    return await memory_import_export.import_memory_data(import_data)


@router.post("/memory/import/upload")
async def upload_memory_file(file: UploadFile, merge_mode: str = "overwrite"):
    """Import memory data from uploaded file."""
    memory_import_export = get_memory_import_export()
    return await memory_import_export.import_from_file(file, merge_mode)


@router.post("/memory/import/validate")
async def validate_import_data(source_data: str):
    """Validate import data without importing."""
    memory_import_export = get_memory_import_export()
    return await memory_import_export._validate_import_data(source_data)