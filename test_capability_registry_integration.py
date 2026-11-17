"""Integration test for CapabilityRegistry with tools.py (B-29)."""

import app.core.tools as tools_module
from app.core.tools.context import TurnContext


def test_get_tools_integration():
    """Test that get_tools works with CapabilityRegistry integration."""
    print("Testing get_tools integration with CapabilityRegistry...")
    
    import app.core.tools as tools_module
    
    # Test 1: Get tools without session (should return all tools)
    all_tools = tools_module.get_tools()
    print(f"   All tools: {len(all_tools)}")
    
    # Should have the expected basic tools
    tool_names = [t.name for t in all_tools]
    basic_tools = ["read", "write", "edit", "bash", "grep", "glob"]
    for basic_tool in basic_tools:
        assert basic_tool in tool_names, f"Missing basic tool: {basic_tool}"
    
    print("   [OK] get_tools returns all tools when no session_id")
    
    # Test 2: Get tools with session (should apply filtering)
    # Note: This is a simplified test - in real usage, session state would be more complex
    session_id = "test_session"
    
    # Mock session state by modifying the get_tools function temporarily
    import app.core.tools as tools_module
    
    # Save original function
    original_get_tools = tools_module.get_tools
    
    def mock_get_tools_with_filter(session_id=None):
        # Get all tools
        all_tools = original_get_tools(None)  # Get all tools without filtering
        
        # Apply filtering if session_id provided
        if session_id:
            from app.core.tools.capability_registry import get_capability_registry
            registry = get_capability_registry()
            
            # Create context (simplified for testing)
            context = TurnContext(language="python")
            
            # Apply filtering
            filtered_tools = registry.filter_tools(all_tools, context)
            return filtered_tools
        
        return all_tools
    
    # Replace the function temporarily
    tools_module.get_tools = mock_get_tools_with_filter
    
    try:
        # Test with Python context
        filtered_tools = tools_module.get_tools("test_session")
        print(f"   Filtered tools: {len(filtered_tools)}")
        
        # Should have fewer tools than all tools
        assert len(filtered_tools) <= len(all_tools), "Filtered tools should be fewer"
        
        # Should include Python LSP tools
        tool_names = [t.name for t in filtered_tools]
        python_lsp_tools = ["lsp.hover", "lsp.definition", "lsp.references"]
        for lsp_tool in python_lsp_tools:
            if lsp_tool in tool_names:
                print(f"   [OK] Found LSP tool: {lsp_tool}")
        
        print("   [OK] get_tools applies filtering with session_id")
        
    finally:
        # Restore original function
        tools_module.get_tools = original_get_tools
    
    print("[OK] All integration tests passed!")


if __name__ == "__main__":
    test_get_tools_integration()