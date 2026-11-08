"""LSP-bus + 6 LSP-servers + 7 LSP-tools for native code intelligence."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import redis.asyncio as redis
from pydantic import BaseModel

from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


class LSPServerConfig(BaseModel):
    """Configuration for LSP server."""

    language: str
    command: List[str]
    init_options: Dict[str, Any] = {}
    file_extensions: List[str] = []
    workspace_root: Optional[Path] = None
    env: Dict[str, str] = {}
    timeout: int = 30
    max_restarts: int = 3
    restart_delay: int = 5

    def get_command_with_args(self, workspace_root: Path) -> List[str]:
        """Get command with workspace arguments."""
        cmd = self.command.copy()

        # Add workspace-specific arguments
        if self.language == "java":
            cmd.extend(["-data", str(workspace_root / ".jdtls")])
        elif self.language == "rust":
            cmd.extend(["--stdio"])
        elif self.language == "go":
            cmd.extend(["stdio"])
        elif self.language in ["typescript", "javascript"]:
            cmd.extend(["--stdio"])

        return cmd


class LSPClient:
    """LSP client for JSON-RPC communication."""

    def __init__(self, config: LSPServerConfig):
        self.config = config
        self.process: Optional[asyncio.subprocess.Process] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.request_id = 0
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.is_running = False
        self.restart_count = 0

    async def start(self, workspace_root: Path) -> None:
        """Start LSP server process."""
        if self.is_running:
            return

        try:
            # Prepare environment
            env = os.environ.copy()
            env.update(self.config.env)

            # Start process
            cmd = self.config.get_command_with_args(workspace_root)
            logger.info(
                f"Starting LSP server for {self.config.language}: {' '.join(cmd)}"
            )

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=workspace_root,
            )

            self.reader = self.process.stdout
            self.writer = self.process.stdin
            self.is_running = True

            # Start message reader
            asyncio.create_task(self._read_messages())

            # Send initialization
            await self._initialize(workspace_root)

            logger.info(f"LSP server for {self.config.language} started successfully")

        except Exception as e:
            logger.error(f"Failed to start LSP server for {self.config.language}: {e}")
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop LSP server process."""
        if not self.is_running:
            return

        try:
            # Send shutdown request
            if self.writer:
                await self._send_request("shutdown", {})

            # Terminate process
            if self.process:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()

        except Exception as e:
            logger.error(f"Error stopping LSP server: {e}")
        finally:
            self.is_running = False
            self.process = None
            self.reader = None
            self.writer = None
            self.pending_requests.clear()

    async def restart(self, workspace_root: Path) -> bool:
        """Restart LSP server."""
        self.restart_count += 1

        if self.restart_count > self.config.max_restarts:
            logger.error(
                f"Max restarts ({self.config.max_restarts}) exceeded for {self.config.language}"
            )
            return False

        logger.info(
            f"Restarting LSP server for {self.config.language} (attempt {self.restart_count})"
        )

        await self.stop()
        await asyncio.sleep(self.config.restart_delay)

        try:
            await self.start(workspace_root)
            return True
        except Exception as e:
            logger.error(f"Failed to restart LSP server: {e}")
            return False

    async def _initialize(self, workspace_root: Path) -> None:
        """Initialize LSP server."""
        # Send initialize request
        init_result = await self._send_request(
            "initialize",
            {
                "processId": None,
                "clientInfo": {"name": "OryaAgent", "version": "1.0.0"},
                "rootUri": workspace_root.as_uri(),
                "capabilities": {},
                "initializationOptions": self.config.init_options,
            },
        )

        # Send initialized notification
        await self._send_notification("initialized", {})

        return init_result

    async def _send_request(
        self, method: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send JSON-RPC request."""
        if not self.writer:
            raise RuntimeError("LSP server not running")

        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params,
        }

        # Send request
        message = json.dumps(request) + "\n"
        self.writer.write(message.encode())
        await self.writer.drain()

        # Wait for response
        future = asyncio.Future()
        self.pending_requests[self.request_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=self.config.timeout)
            return result
        except asyncio.TimeoutError:
            raise TimeoutError(f"LSP request {method} timed out")
        finally:
            self.pending_requests.pop(self.request_id, None)

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send JSON-RPC notification."""
        if not self.writer:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        message = json.dumps(notification) + "\n"
        self.writer.write(message.encode())
        await self.writer.drain()

    async def _read_messages(self) -> None:
        """Read messages from LSP server."""
        if not self.reader:
            return

        buffer = ""
        while self.is_running:
            try:
                data = await self.reader.read(1024)
                if not data:
                    break

                buffer += data.decode()

                # Process complete messages
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        await self._handle_message(json.loads(line))

            except Exception as e:
                logger.error(f"Error reading LSP messages: {e}")
                break

        # Server disconnected
        if self.is_running:
            logger.warning(f"LSP server disconnected for {self.config.language}")
            self.is_running = False

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """Handle incoming LSP message."""
        if "id" in message:
            # Response to request
            request_id = message["id"]
            if request_id in self.pending_requests:
                future = self.pending_requests[request_id]
                if "error" in message:
                    future.set_exception(Exception(message["error"]["message"]))
                else:
                    future.set_result(message.get("result", {}))
        else:
            # Notification
            method = message.get("method")
            params = message.get("params", {})

            if method == "window/logMessage":
                logger.info(f"LSP log: {params.get('message', '')}")

    async def did_open(self, file_path: Path, text: str) -> None:
        """Send textDocument/didOpen notification."""
        await self._send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": file_path.as_uri(),
                    "languageId": self.config.language,
                    "version": 1,
                    "text": text,
                }
            },
        )

    async def did_change(
        self, file_path: Path, content_changes: List[Dict[str, Any]]
    ) -> None:
        """Send textDocument/didChange notification."""
        await self._send_notification(
            "textDocument/didChange",
            {
                "textDocument": {
                    "uri": file_path.as_uri(),
                    "version": 2,
                },
                "contentChanges": content_changes,
            },
        )

    async def did_close(self, file_path: Path) -> None:
        """Send textDocument/didClose notification."""
        await self._send_notification(
            "textDocument/didClose",
            {
                "textDocument": {
                    "uri": file_path.as_uri(),
                }
            },
        )

    async def hover(self, file_path: Path, position: Dict[str, int]) -> Dict[str, Any]:
        """Send textDocument/hover request."""
        return await self._send_request(
            "textDocument/hover",
            {
                "textDocument": {"uri": file_path.as_uri()},
                "position": position,
            },
        )

    async def definition(
        self, file_path: Path, position: Dict[str, int]
    ) -> Dict[str, Any]:
        """Send textDocument/definition request."""
        return await self._send_request(
            "textDocument/definition",
            {
                "textDocument": {"uri": file_path.as_uri()},
                "position": position,
            },
        )

    async def references(
        self, file_path: Path, position: Dict[str, int], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send textDocument/references request."""
        return await self._send_request(
            "textDocument/references",
            {
                "textDocument": {"uri": file_path.as_uri()},
                "position": position,
                "context": context,
            },
        )

    async def symbol_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Send workspace/symbol request."""
        return await self._send_request(
            "workspace/symbol",
            {
                "query": query,
                "limit": limit,
            },
        )

    async def rename(
        self, file_path: Path, position: Dict[str, int], new_name: str
    ) -> Dict[str, Any]:
        """Send textDocument/rename request."""
        return await self._send_request(
            "textDocument/rename",
            {
                "textDocument": {"uri": file_path.as_uri()},
                "position": position,
                "newName": new_name,
            },
        )

    async def diagnostics(self, file_path: Path) -> List[Dict[str, Any]]:
        """Get diagnostics for a file."""
        return await self._send_request(
            "textDocument/diagnostic",
            {
                "textDocument": {"uri": file_path.as_uri()},
            },
        )

    async def code_action(
        self, file_path: Path, range: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Send textDocument/codeAction request."""
        return await self._send_request(
            "textDocument/codeAction",
            {
                "textDocument": {"uri": file_path.as_uri()},
                "range": range,
            },
        )


class LSPBus:
    """LSP server manager for multiple languages."""

    def __init__(self, redis_client: redis.Redis = None):
        self.redis_client = redis_client
        self.servers: Dict[str, LSPClient] = {}
        self.server_configs: Dict[str, LSPServerConfig] = {}
        self.is_running = False

        # Initialize server configurations
        self._initialize_server_configs()

    def _initialize_server_configs(self) -> None:
        """Initialize LSP server configurations."""
        self.server_configs = {
            "python": LSPServerConfig(
                language="python",
                command=["pyright-langserver", "--stdio"],
                init_options={
                    "python.analysis.autoImportCompletions": True,
                    "python.analysis.typeCheckingMode": "standard",
                },
                file_extensions=[".py"],
                env={"PYTHONPATH": os.getcwd()},
            ),
            "typescript": LSPServerConfig(
                language="typescript",
                command=["typescript-language-server", "--stdio"],
                init_options={
                    "preferences": {
                        "importModuleSpecifierPreference": "relative",
                        "jsxAttributeCompletionStyle": "auto",
                    },
                    "typescript": {
                        "preferences": {
                            "includePackageJsonAutoImports": "on",
                        },
                    },
                },
                file_extensions=[".ts", ".tsx", ".js", ".jsx"],
            ),
            "rust": LSPServerConfig(
                language="rust",
                command=["rust-analyzer"],
                init_options={
                    "cargo": {
                        "loadOutDirsFromCheck": True,
                    },
                    "procMacro": {
                        "enable": True,
                    },
                },
                file_extensions=[".rs"],
            ),
            "go": LSPServerConfig(
                language="go",
                command=["gopls", "stdio"],
                init_options={
                    "staticcheck": True,
                    "ui.diagnostic.staticcheck": True,
                },
                file_extensions=[".go"],
            ),
            "java": LSPServerConfig(
                language="java",
                command=["jdtls"],
                init_options={
                    "java": {
                        "configuration": {
                            "runtimes": [
                                {
                                    "name": "JavaSE-17",
                                    "path": "/usr/lib/jvm/java-17-openjdk-amd64",
                                }
                            ],
                        },
                    },
                },
                file_extensions=[".java"],
            ),
            "lua": LSPServerConfig(
                language="lua",
                command=["lua-language-server"],
                init_options={
                    "Lua.workspace.library": {
                        "/usr/share/lua/5.4/?.lua": true,
                        "/usr/share/lua/5.4/?/init.lua": true,
                    },
                },
                file_extensions=[".lua"],
            ),
        }

    async def start(self) -> None:
        """Start LSP bus."""
        if self.is_running:
            return

        self.is_running = True
        logger.info("LSP bus started")

    async def stop(self) -> None:
        """Stop LSP bus."""
        if not self.is_running:
            return

        # Stop all servers
        for server in self.servers.values():
            await server.stop()

        self.servers.clear()
        self.is_running = False
        logger.info("LSP bus stopped")

    async def ensure_server(self, language: str, workspace: Path) -> LSPClient:
        """Ensure LSP server is running for language."""
        if language not in self.server_configs:
            raise ValueError(f"Unsupported language: {language}")

        # Check if server is already running
        if language in self.servers:
            server = self.servers[language]
            if server.is_running:
                return server
            else:
                await server.stop()
                del self.servers[language]

        # Start new server
        config = self.server_configs[language]
        server = LSPClient(config)

        try:
            await server.start(workspace)
            self.servers[language] = server

            # Save to Redis for cross-process reuse
            if self.redis_client:
                await self.redis_client.setex(
                    f"orya:lsp:server:{language}:{hash(str(workspace))}",
                    3600,  # 1 hour TTL
                    json.dumps(
                        {
                            "pid": server.process.pid,
                            "workspace": str(workspace),
                        }
                    ),
                )

            return server

        except Exception as e:
            logger.error(f"Failed to start LSP server for {language}: {e}")
            await server.stop()
            raise

    async def get_server(self, language: str, workspace: Path) -> Optional[LSPClient]:
        """Get LSP server if running."""
        if language in self.servers:
            server = self.servers[language]
            if server.is_running:
                return server
            else:
                await server.stop()
                del self.servers[language]

        # Try to restore from Redis
        if self.redis_client:
            try:
                data = await self.redis_client.get(
                    f"orya:lsp:server:{language}:{hash(str(workspace))}"
                )
                if data:
                    logger.info(f"Found LSP server for {language} in Redis")
                    # In a real implementation, we would connect to existing process
                    # For now, we'll start a new one
                    return await self.ensure_server(language, workspace)
            except Exception as e:
                logger.error(f"Error restoring LSP server from Redis: {e}")

        return None

    async def restart_server(self, language: str, workspace: Path) -> bool:
        """Restart LSP server."""
        if language in self.servers:
            server = self.servers[language]
            success = await server.restart(workspace)
            if success:
                return True

        # Try to start new server
        try:
            await self.ensure_server(language, workspace)
            return True
        except Exception as e:
            logger.error(f"Failed to restart LSP server for {language}: {e}")
            return False

    async def is_server_running(self, language: str) -> bool:
        """Check if server is running."""
        if language in self.servers:
            return self.servers[language].is_running
        return False

    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages."""
        return list(self.server_configs.keys())

    def get_file_extensions(self, language: str) -> List[str]:
        """Get file extensions for language."""
        if language in self.server_configs:
            return self.server_configs[language].file_extensions
        return []

    def detect_language(self, file_path: Path) -> Optional[str]:
        """Detect language from file extension."""
        extension = file_path.suffix.lower()

        for language, config in self.server_configs.items():
            if extension in config.file_extensions:
                return language

        return None


# Global LSP bus instance
_lsp_bus: Optional[LSPBus] = None


def get_lsp_bus() -> LSPBus:
    """Get global LSP bus instance."""
    global _lsp_bus
    if _lsp_bus is None:
        _lsp_bus = LSPBus()
    return _lsp_bus


def initialize_lsp_bus(redis_client: redis.Redis = None) -> LSPBus:
    """Initialize global LSP bus."""
    global _lsp_bus
    _lsp_bus = LSPBus(redis_client)
    return _lsp_bus
