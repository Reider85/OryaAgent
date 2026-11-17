"""LSP-native implementation for OryaAgent BETA.

This module provides Language Server Protocol (LSP) integration for native
code intelligence with sub-ms latency and 100-500 tokens per operation.

Components:
- LSPBus: Per-language LSP-server manager
- LSPClient: JSON-RPC client for LSP communication  
- LSPFileWatcher: Real-time file change detection
- 7 LSP tools: hover, definition, references, symbol_search, rename, diagnostics, code_action
"""

from .bus import (
    LSPBus,
    LSPServerConfig, 
    LSPClient,
    get_lsp_bus,
    initialize_lsp_bus,
)
from .watcher import (
    LSPFileWatcher,
    get_file_watcher,
    initialize_file_watcher,
)
try:
    from app.tools.lsp import (
        lsp_hover,
        lsp_definition,
        lsp_references,
        lsp_symbol_search,
        lsp_rename,
        lsp_diagnostics,
        lsp_code_action,
        LSPToolException,
    )
except ImportError:
    # Handle circular import during testing
    lsp_hover = None
    lsp_definition = None
    lsp_references = None
    lsp_symbol_search = None
    lsp_rename = None
    lsp_diagnostics = None
    lsp_code_action = None
    LSPToolException = Exception

__all__ = [
    # Core LSP components
    "LSPBus",
    "LSPServerConfig", 
    "LSPClient",
    "get_lsp_bus",
    "initialize_lsp_bus",
    
    # File watcher
    "LSPFileWatcher",
    "get_file_watcher",
    "initialize_file_watcher",
    
    # LSP tools
    "lsp_hover",
    "lsp_definition", 
    "lsp_references",
    "lsp_symbol_search",
    "lsp_rename",
    "lsp_diagnostics",
    "lsp_code_action",
    "LSPToolException",
]