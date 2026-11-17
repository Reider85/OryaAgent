"""Simple test for retrieval orchestrator imports."""

def test_imports():
    """Test that all imports work correctly."""
    try:
        from app.core.retrieval.orchestrator import get_retrieval_orchestrator
        from app.core.retrieval.models import RetrievalStrategy
        from app.core.retrieval.heuristics import get_heuristics_engine
        from app.core.retrieval.strategies import get_available_strategies
        
        print("All imports successful")
        print(f"Available strategies: {get_available_strategies()}")
        print(f"Retrieval strategies count: {len(RetrievalStrategy)}")
        
        return True
        
    except Exception as e:
        print(f"Import failed: {e}")
        return False

if __name__ == "__main__":
    test_imports()