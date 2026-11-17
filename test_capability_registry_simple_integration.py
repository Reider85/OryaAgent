"""Simple integration test for CapabilityRegistry (B-29)."""

from app.core.tools.capability_registry import get_capability_registry
from app.core.tools.context import TurnContext


class MockTool:
    """Mock tool for testing."""
    
    def __init__(self, name: str):
        self.name = name


def test_integration():
    """Test CapabilityRegistry integration."""
    print("Testing CapabilityRegistry integration...")
    
    # Create mock tools similar to real tools
    all_tools = [
        MockTool("read"),
        MockTool("write"),
        MockTool("edit"),
        MockTool("bash"),
        MockTool("grep"),
        MockTool("glob"),
        MockTool("lsp.hover"),
        MockTool("lsp.definition"),
        MockTool("lsp.references"),
        MockTool("lsp.rename"),
        MockTool("lsp.symbol_search"),
        MockTool("lsp.diagnostics"),
        MockTool("lsp.code_action"),
        MockTool("oriahs_search"),
        MockTool("oriahs_index"),
        MockTool("memory.search"),
        MockTool("ukb.lookup"),
        MockTool("retrieval_orchestrate"),
    ]
    
    # Get registry
    registry = get_capability_registry()
    
    print(f"   Total tools available: {len(all_tools)}")
    
    # Test 1: No filtering (basic scenario)
    context = TurnContext()
    filtered = registry.filter_tools(all_tools, context)
    print(f"   No context: {len(filtered)} tools")
    
    # Test 2: Python context
    context = TurnContext(language="python", file_path="src/main.py")
    filtered = registry.filter_tools(all_tools, context)
    print(f"   Python context: {len(filtered)} tools")
    
    # Test 3: Rename intent
    context = TurnContext(language="python", intent="rename")
    filtered = registry.filter_tools(all_tools, context)
    print(f"   Rename intent: {len(filtered)} tools")
    
    # Test 4: Memory intent
    context = TurnContext(
        last_message="Помнишь, мы обсуждали authentication?",
        referential_marker=True
    )
    filtered = registry.filter_tools(all_tools, context)
    print(f"   Memory intent: {len(filtered)} tools")
    
    # Check statistics
    stats = registry.get_statistics()
    print(f"   Statistics: {stats}")
    
    print("[OK] Integration test completed successfully!")


if __name__ == "__main__":
    test_integration()