"""Simple test for retrieval orchestrator functionality."""


def test_retrieval_strategy_enum():
    """Test RetrievalStrategy enum."""
    from app.core.retrieval.models import RetrievalStrategy

    assert len(RetrievalStrategy) == 7
    assert RetrievalStrategy.NONE.value == "none"
    assert RetrievalStrategy.STANDARD.value == "standard"
    assert RetrievalStrategy.EXPLICIT_RECALL.value == "explicit_recall"
    assert RetrievalStrategy.CODE_LOOKUP.value == "code_lookup"
    print("RetrievalStrategy enum test passed")


def test_strategy_decision():
    """Test StrategyDecision dataclass."""
    from app.core.retrieval.models import RetrievalStrategy, StrategyDecision

    decision = StrategyDecision(
        strategy=RetrievalStrategy.STANDARD,
        confidence=0.8,
        reasoning="Test reasoning",
        heuristics_matched=["first_turn"],
        context={"turn_count": 0},
    )

    assert decision.strategy == RetrievalStrategy.STANDARD
    assert decision.confidence == 0.8
    assert decision.reasoning == "Test reasoning"
    assert "first_turn" in decision.heuristics_matched
    assert decision.context["turn_count"] == 0

    # Test serialization
    decision_dict = decision.to_dict()
    assert decision_dict["strategy"] == "standard"
    assert decision_dict["confidence"] == 0.8
    print("StrategyDecision test passed")


def test_retrieved_chunk():
    """Test RetrievedChunk dataclass."""
    from app.core.retrieval.models import RetrievedChunk

    chunk = RetrievedChunk(
        content="Test content", source="test", score=0.8, metadata={"test": "value"}
    )

    assert chunk.content == "Test content"
    assert chunk.source == "test"
    assert chunk.score == 0.8
    assert chunk.metadata["test"] == "value"
    assert chunk.chunk_id is not None
    assert not chunk.promoted_to_dfc

    # Test promotion
    chunk.promote_to_dfc("test_key")
    assert chunk.promoted_to_dfc
    assert chunk.metadata["promoted_key"] == "test_key"

    # Test serialization
    chunk_dict = chunk.to_dict()
    assert chunk_dict["content"] == "Test content"
    assert chunk_dict["source"] == "test"
    assert chunk_dict["promoted_to_dfc"]
    print("RetrievedChunk test passed")


def test_heuristics_engine():
    """Test heuristics engine."""
    from app.core.retrieval.heuristics import get_heuristics_engine
    from app.core.retrieval.models import RetrievalStrategy

    heuristics = get_heuristics_engine()

    # Test first turn heuristic
    session_state = {
        "turn_count": 0,
        "last_message": "Help me",
        "previous_messages": [],
    }

    result = heuristics.first_turn_heuristic(session_state)
    assert result.strategy == RetrievalStrategy.STANDARD
    assert result.matched
    assert result.confidence > 0.0

    # Test referential markers heuristic
    session_state["turn_count"] = 3
    session_state["last_message"] = "Помнишь, мы обсуждали authentication?"

    result = heuristics.referential_marker_heuristic(session_state)
    assert result.strategy == RetrievalStrategy.EXPLICIT_RECALL
    assert result.matched

    print("Heuristics engine test passed")


def test_strategies():
    """Test individual strategies."""
    from app.core.retrieval.strategies import get_available_strategies, get_strategy

    strategies = get_available_strategies()
    assert len(strategies) == 7
    assert "none" in strategies
    assert "standard" in strategies
    assert "explicit_recall" in strategies
    assert "code_lookup" in strategies

    # Test strategy creation
    strategy = get_strategy("standard")
    assert strategy is not None
    assert strategy.name == "standard"
    assert hasattr(strategy, "retrieve")
    assert hasattr(strategy, "should_use")

    print("Strategies test passed")


def test_orchestrator_basic():
    """Test basic orchestrator functionality."""
    from app.core.retrieval.orchestrator import RetrievalOrchestrator
    from app.core.retrieval.strategies import get_available_strategies

    # Create orchestrator without DFC dependency
    orchestrator = RetrievalOrchestrator()

    # Test decision returns one of 7 strategies
    session_state = {
        "turn_count": 0,
        "last_message": "test message",
        "previous_messages": [],
    }

    decision = orchestrator.decide(session_state)
    assert decision.strategy in decision.__class__.__annotations__.get("strategy", [])
    assert decision.strategy.value in get_available_strategies()

    print("Orchestrator basic test passed")


if __name__ == "__main__":
    test_retrieval_strategy_enum()
    test_strategy_decision()
    test_retrieved_chunk()
    test_heuristics_engine()
    test_strategies()
    test_orchestrator_basic()
    print("All tests passed!")
