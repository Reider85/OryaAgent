"""File watcher for LSP integration with textDocument/didChange events."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.core.lsp.bus import get_lsp_bus
from app.core.tools._validators import validate_path

logger = logging.getLogger(__name__)


class FileChangeEvent:
    """Represents a file change event."""
    
    def __init__(self, file_path: Path, change_type: str, content: str = ""):
        self.file_path = file_path
        self.change_type = change_type  # "create", "modify", "delete"
        self.content = content
        self.timestamp = asyncio.get_event_loop().time()


class LSPFileWatcher:
    """File watcher for LSP integration with textDocument/didChange events."""
    
    def __init__(
        self,
        workspace: str = ".",
        debounce_interval: float = 0.1,
        max_file_size: int = 1024 * 1024,  # 1MB
    ):
        self.workspace_path = Path(workspace).resolve()
        self.debounce_interval = debounce_interval
        self.max_file_size = max_file_size
        
        # Track watched files
        self.watched_files: Set[Path] = set()
        self.file_events: Dict[Path, FileChangeEvent] = {}
        
        # Track LSP servers
        self.lsp_servers: Dict[str, Any] = {}
        
        # Control
        self.is_running = False
        self._watch_task: Optional[asyncio.Task] = None
        self._debounce_tasks: Dict[Path, asyncio.Task] = {}
        
        # File system observer (mock implementation)
        self._observed_paths: Set[Path] = set()
    
    async def start(self) -> None:
        """Start the file watcher."""
        if self.is_running:
            return
        
        self.is_running = True
        logger.info(f"Starting LSP file watcher for workspace: {self.workspace_path}")
        
        # Start watch task
        self._watch_task = asyncio.create_task(self._watch_loop())
        
        # Start watching workspace
        await self._observe_path(self.workspace_path)
        
        logger.info("LSP file watcher started")
    
    async def stop(self) -> None:
        """Stop the file watcher."""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Cancel watch task
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
        
        # Cancel debounce tasks
        for task in self._debounce_tasks.values():
            task.cancel()
        self._debounce_tasks.clear()
        
        # Stop observing paths
        self._observed_paths.clear()
        
        # Close LSP servers
        for server in self.lsp_servers.values():
            await server.stop()
        self.lsp_servers.clear()
        
        logger.info("LSP file watcher stopped")
    
    async def _watch_loop(self) -> None:
        """Main watch loop."""
        while self.is_running:
            try:
                # Process file events
                await self._process_file_events()
                
                # Sleep briefly
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in watch loop: {e}")
                await asyncio.sleep(1)  # Wait before retry
    
    async def _process_file_events(self) -> None:
        """Process pending file events."""
        # Process debounce tasks
        completed_tasks = []
        for file_path, task in self._debounce_tasks.items():
            if task.done():
                completed_tasks.append(file_path)
        
        # Process completed debounce tasks
        for file_path in completed_tasks:
            task = self._debounce_tasks.pop(file_path, None)
            if task and not task.cancelled():
                try:
                    await task
                except Exception as e:
                    logger.error(f"Error processing debounce task for {file_path}: {e}")
        
        # Process file events
        for file_path, event in self.file_events.items():
            if file_path not in self._debounce_tasks:
                await self._handle_file_event(event)
        
        # Clear processed events
        self.file_events.clear()
    
    async def _handle_file_event(self, event: FileChangeEvent) -> None:
        """Handle a file change event."""
        try:
            file_path = event.file_path
            language = self._detect_language(file_path)
            
            if not language:
                return
            
            # Get or create LSP server
            if language not in self.lsp_servers:
                lsp_bus = get_lsp_bus()
                server = await lsp_bus.ensure_server(language, self.workspace_path)
                self.lsp_servers[language] = server
            
            server = self.lsp_servers[language]
            
            # Handle different change types
            if event.change_type == "create":
                await server.did_open(file_path, event.content)
            elif event.change_type == "modify":
                # Send incremental change
                content_changes = [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": len(event.content.split('\n')), "character": 0}
                    },
                    "text": event.content
                }]
                await server.did_change(file_path, content_changes)
            elif event.change_type == "delete":
                await server.did_close(file_path)
            
            logger.debug(f"Processed {event.change_type} event for {file_path}")
            
        except Exception as e:
            logger.error(f"Error handling file event for {event.file_path}: {e}")
    
    def _detect_language(self, file_path: Path) -> Optional[str]:
        """Detect language from file extension."""
        lsp_bus = get_lsp_bus()
        return lsp_bus.detect_language(file_path)
    
    async def _observe_path(self, path: Path) -> None:
        """Observe a path for file changes."""
        if path in self._observed_paths:
            return
        
        self._observed_paths.add(path)
        logger.debug(f"Observing path: {path}")
        
        # In a real implementation, this would use a file system watcher
        # For now, we'll simulate with periodic checks
    
    async def add_file(self, file_path: str, content: str = "") -> None:
        """Add a file to watch."""
        file_path = validate_path(file_path)
        
        if file_path not in self.watched_files:
            self.watched_files.add(file_path)
            logger.debug(f"Added file to watch: {file_path}")
            
            # Send initial didOpen event
            event = FileChangeEvent(file_path, "create", content)
            await self._handle_file_event(event)
    
    async def modify_file(self, file_path: str, content: str) -> None:
        """Modify a file content."""
        file_path = validate_path(file_path)
        
        if file_path in self.watched_files:
            # Debounce rapid changes
            if file_path in self._debounce_tasks:
                self._debounce_tasks[file_path].cancel()
            
            # Create debounce task
            task = asyncio.create_task(self._debounced_file_change(file_path, content))
            self._debounce_tasks[file_path] = task
    
    async def delete_file(self, file_path: str) -> None:
        """Delete a file from watch."""
        file_path = validate_path(file_path)
        
        if file_path in self.watched_files:
            self.watched_files.remove(file_path)
            
            # Send didClose event
            event = FileChangeEvent(file_path, "delete")
            await self._handle_file_event(event)
            
            logger.debug(f"Removed file from watch: {file_path}")
    
    async def _debounced_file_change(self, file_path: Path, content: str) -> None:
        """Debounce file changes."""
        await asyncio.sleep(self.debounce_interval)
        
        # Create change event
        event = FileChangeEvent(file_path, "modify", content)
        self.file_events[file_path] = event
    
    async def refresh_file(self, file_path: str) -> None:
        """Refresh a file content."""
        file_path = validate_path(file_path)
        
        if file_path in self.watched_files:
            # Read current content
            try:
                content = file_path.read_text(encoding='utf-8')
                event = FileChangeEvent(file_path, "modify", content)
                await self._handle_file_event(event)
            except Exception as e:
                logger.error(f"Error refreshing file {file_path}: {e}")
    
    async def refresh_all(self) -> None:
        """Refresh all watched files."""
        for file_path in self.watched_files:
            await self.refresh_file(file_path)
    
    def get_watched_files(self) -> List[str]:
        """Get list of watched files."""
        return [str(f) for f in self.watched_files]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get watcher statistics."""
        return {
            "is_running": self.is_running,
            "watched_files_count": len(self.watched_files),
            "debounce_tasks_count": len(self._debounce_tasks),
            "lsp_servers_count": len(self.lsp_servers),
            "observed_paths_count": len(self._observed_paths),
        }


# Global file watcher instance
_file_watcher: Optional[LSPFileWatcher] = None


def get_file_watcher() -> LSPFileWatcher:
    """Get global file watcher instance."""
    global _file_watcher
    if _file_watcher is None:
        _file_watcher = LSPFileWatcher()
    return _file_watcher


def initialize_file_watcher(workspace: str = ".") -> LSPFileWatcher:
    """Initialize global file watcher."""
    global _file_watcher
    _file_watcher = LSPFileWatcher(workspace=workspace)
    return _file_watcher