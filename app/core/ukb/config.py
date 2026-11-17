"""UKB (Unified Knowledge Bus) configuration settings."""

from __future__ import annotations


class UKBConfig:
    """Configuration for UKB (Unified Knowledge Bus)."""

    def __init__(
        self,
        cache_ttl_seconds: int = 300,
        max_cache_size: int = 1000,
        max_concurrent_lookups: int = 10,
        default_top_k: int = 5,
        enabled_namespaces: list[str] = None,
        routing_rules: dict[str, str] = None,
        performance_thresholds: dict[str, int] = None,
        enable_debug_logging: bool = False,
        log_cache_operations: bool = True,
        use_mock_implementations: bool = True,
        lsp_integration_enabled: bool = True,
        memory_integration_enabled: bool = True,
        code_integration_enabled: bool = False,
        kb_integration_enabled: bool = False,
    ):
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_cache_size = max_cache_size
        self.max_concurrent_lookups = max_concurrent_lookups
        self.default_top_k = default_top_k
        self.enabled_namespaces = enabled_namespaces or ["lsp", "memory"]
        self.routing_rules = routing_rules or {
            "lsp.def": "lsp",
            "lsp.hover": "lsp",
            "lsp.refs": "lsp",
            "lsp.symbol_search": "lsp",
            "lsp.rename": "lsp",
            "lsp.diagnostics": "lsp",
            "lsp.codeAction": "lsp",
            "memory.semantic": "memory",
            "memory.lexical": "memory",
        }
        self.performance_thresholds = performance_thresholds or {
            "single_namespace_lookup": 500,
            "multi_namespace_lookup": 800,
            "cache_hit": 10,
        }
        self.enable_debug_logging = enable_debug_logging
        self.log_cache_operations = log_cache_operations
        self.use_mock_implementations = use_mock_implementations
        self.lsp_integration_enabled = lsp_integration_enabled
        self.memory_integration_enabled = memory_integration_enabled
        self.code_integration_enabled = code_integration_enabled
        self.kb_integration_enabled = kb_integration_enabled

    @classmethod
    def get_beta_config(cls) -> UKBConfig:
        """Get BETA-specific configuration."""
        config = cls()
        config.enabled_namespaces = ["lsp", "memory"]
        config.use_mock_implementations = True
        config.code_integration_enabled = False
        config.kb_integration_enabled = False
        return config

    def is_namespace_enabled(self, namespace: str) -> bool:
        """Check if a namespace is enabled."""
        return namespace in self.enabled_namespaces

    def get_routing_rule(self, capability: str) -> str:
        """Get routing rule for a capability."""
        return self.routing_rules.get(capability, "default")
