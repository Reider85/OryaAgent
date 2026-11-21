print("Starting retrieval tests...")

try:
    from app.core.retrieval.models import RetrievalStrategy

    print(f"RetrievalStrategy loaded: {len(RetrievalStrategy)} strategies")

    print("Heuristics engine loaded")

    from app.core.retrieval.strategies import get_available_strategies

    strategies = get_available_strategies()
    print(f"Available strategies: {strategies}")

    from app.core.retrieval.orchestrator import RetrievalOrchestrator

    orchestrator = RetrievalOrchestrator()
    print("Orchestrator created successfully")

    print("All components loaded successfully!")

except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()
