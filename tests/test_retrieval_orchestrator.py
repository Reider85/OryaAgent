"""Enhanced tests for RetrievalOrchestrator with 7 strategies."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml

from app.core.retrieval.heuristics import get_heuristics_engine
from app.core.retrieval.models import (
    RetrievalStrategy,
    RetrievedChunk,
    StrategyDecision,
)
from app.core.retrieval.orchestrator import (
    RetrievalOrchestrator,
    get_retrieval_orchestrator,
    initialize_retrieval_orchestrator,
)
from app.core.retrieval.strategies import get_available_strategies, get_strategy


class TestRetrievalOrchestrator:
    """Test enhanced RetrievalOrchestrator functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.orchestrator = initialize_retrieval_orchestrator()

    def test_decision_returns_one_of_7_strategies(self):
        """Test that decide() returns one of the 7 expected strategies."""
        session_state = {
            "turn_count": 0,
            "last_message": "test message",
            "previous_messages": [],
        }

        decision = self.orchestrator.decide(session_state)

        assert decision.strategy in RetrievalStrategy
        assert decision.strategy.value in get_available_strategies()

    def test_execute_none_strategy_returns_empty_list(self):
        """Test that execute('none') returns empty list."""
        session_state = {
            "turn_count": 1,
            "last_message": "test message",
            "previous_messages": [],
        }

        results = asyncio.run(
            self.orchestrator.execute(RetrievalStrategy.NONE, session_state)
        )

        assert results == []

    def test_execute_standard_strategy_returns_results(self):
        """Test that execute('standard') returns results."""
        session_state = {
            "turn_count": 0,
            "last_message": "test message",
            "previous_messages": [],
        }

        results = asyncio.run(
            self.orchestrator.execute(RetrievalStrategy.STANDARD, session_state)
        )

        assert isinstance(results, list)
        # Results may be empty in mock environment, but should be list

    def test_execute_explicit_recall_returns_top_10(self):
        """Test that execute('explicit_recall') returns up to 10 results."""
        session_state = {
            "turn_count": 5,
            "last_message": "Помнишь, мы обсуждали authentication?",
            "previous_messages": ["Let's build authentication"],
        }

        results = asyncio.run(
            self.orchestrator.execute(
                RetrievalStrategy.EXPLICIT_RECALL, session_state, top_k=10
            )
        )

        assert isinstance(results, list)
        assert len(results) <= 10

    def test_orchestration_full_flow(self):
        """Test full orchestration flow."""
        session_state = {
            "turn_count": 0,
            "last_message": "Help me understand this codebase",
            "previous_messages": [],
        }

        results = asyncio.run(self.orchestrator.orchestrate(session_state))

        assert isinstance(results, list)
        # Verify that a decision was made
        decision = self.orchestrator.decide(session_state)
        assert decision.strategy in RetrievalStrategy

    def test_strategy_usage_stats(self):
        """Test strategy usage statistics."""
        stats = self.orchestrator.get_strategy_usage_stats()

        assert isinstance(stats, dict)
        assert len(stats) == 7  # All 7 strategies
        assert all(count == 0 for count in stats.values())  # Initially zero

    def test_cache_stats(self):
        """Test cache statistics."""
        stats = self.orchestrator.get_cache_stats()

        assert isinstance(stats, dict)
        assert "cache_size" in stats
        assert "cache_keys" in stats

    def test_health_check(self):
        """Test health check functionality."""
        health = asyncio.run(self.orchestrator.health_check())

        assert isinstance(health, dict)
        assert "status" in health
        assert health["status"] in ["healthy", "unhealthy"]

    def test_decision_accuracy_synthetic_dataset(self):
        """Test decision accuracy on synthetic dataset."""
        # Load synthetic dataset
        dataset_path = Path(__file__).parent / "fixtures" / "retrieval_scenarios.yml"

        with open(dataset_path, encoding="utf-8") as f:
            dataset = yaml.safe_load(f)

        correct_decisions = 0
        total_scenarios = len(dataset["scenarios"])

        for scenario in dataset["scenarios"]:
            session_state = scenario["session_state"]
            expected_strategy = RetrievalStrategy(scenario["expected_strategy"])

            decision = self.orchestrator.decide(session_state)

            if decision.strategy == expected_strategy:
                correct_decisions += 1

        accuracy = correct_decisions / total_scenarios
        print(
            f"Decision accuracy: {accuracy:.2f} ({correct_decisions}/{total_scenarios})"
        )

        # Assert accuracy > 75% for the dataset
        assert accuracy >= 0.75, f"Accuracy {accuracy:.2f} < 0.75"


class TestRetrievalModels:
    """Test retrieval data models."""

    def test_retrieval_strategy_enum(self):
        """Test RetrievalStrategy enum."""
        assert len(RetrievalStrategy) == 7
        assert RetrievalStrategy.NONE.value == "none"
        assert RetrievalStrategy.STANDARD.value == "standard"
        assert RetrievalStrategy.EXPLICIT_RECALL.value == "explicit_recall"
        assert RetrievalStrategy.CODE_LOOKUP.value == "code_lookup"

    def test_strategy_decision(self):
        """Test StrategyDecision dataclass."""
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

    def test_retrieved_chunk(self):
        """Test RetrievedChunk dataclass."""
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


class TestHeuristicsEngine:
    """Test heuristics engine."""

    def setup_method(self):
        """Set up test fixtures."""
        self.heuristics = get_heuristics_engine()

    def test_first_turn_heuristic(self):
        """Test first turn heuristic."""
        # First turn
        session_state = {
            "turn_count": 0,
            "last_message": "Help me",
            "previous_messages": [],
        }

        result = self.heuristics.first_turn_heuristic(session_state)

        assert result.strategy == RetrievalStrategy.STANDARD
        assert result.matched
        assert result.confidence > 0.0

        # Not first turn
        session_state["turn_count"] = 5
        result = self.heuristics.first_turn_heuristic(session_state)

        assert result.strategy == RetrievalStrategy.NONE
        assert not result.matched

    def test_referential_marker_heuristic(self):
        """Test referential markers heuristic."""
        # Has referential markers
        session_state = {
            "turn_count": 3,
            "last_message": "Помнишь, мы обсуждали authentication?",
            "previous_messages": [],
        }

        result = self.heuristics.referential_marker_heuristic(session_state)

        assert result.strategy == RetrievalStrategy.EXPLICIT_RECALL
        assert result.matched

        # No referential markers
        session_state["last_message"] = "Hello world"
        result = self.heuristics.referential_marker_heuristic(session_state)

        assert result.strategy == RetrievalStrategy.NONE
        assert not result.matched

    def test_code_intent_heuristic(self):
        """Test code intent heuristic."""
        # Has code intent
        session_state = {
            "turn_count": 2,
            "last_message": "Find the definition of UserService.create",
            "previous_messages": [],
        }

        result = self.heuristics.code_intent_heuristic(session_state)

        assert result.strategy == RetrievalStrategy.CODE_LOOKUP
        assert result.matched

        # Has file extension
        session_state["last_message"] = "Show me utils.py"
        result = self.heuristics.code_intent_heuristic(session_state)

        assert result.strategy == RetrievalStrategy.CODE_LOOKUP
        assert result.matched

    def test_memory_intent_heuristic(self):
        """Test memory intent heuristic."""
        # Has memory intent (patterns are Russian keywords)
        session_state = {
            "turn_count": 5,
            "last_message": "Вспомни, что мы решили про кэширование?",
            "previous_messages": [],
        }

        result = self.heuristics.memory_intent_heuristic(session_state)

        assert result.strategy == RetrievalStrategy.EXPLICIT_RECALL
        assert result.matched

        # No memory intent
        session_state["last_message"] = "Hello world"
        result = self.heuristics.memory_intent_heuristic(session_state)

        assert result.strategy == RetrievalStrategy.NONE
        assert not result.matched

    def test_make_decision(self):
        """Test strategy decision making."""
        session_state = {
            "turn_count": 0,
            "last_message": "Help me understand this codebase",
            "previous_messages": [],
        }

        decision = self.heuristics.make_decision(session_state)

        assert isinstance(decision, StrategyDecision)
        assert decision.strategy in RetrievalStrategy
        assert decision.confidence >= 0.0
        assert isinstance(decision.reasoning, str)
        assert isinstance(decision.heuristics_matched, list)


class TestStrategies:
    """Test individual strategies."""

    def test_available_strategies(self):
        """Test available strategies."""
        strategies = get_available_strategies()

        assert len(strategies) == 7
        assert "none" in strategies
        assert "standard" in strategies
        assert "explicit_recall" in strategies
        assert "code_lookup" in strategies

    def test_strategy_creation(self):
        """Test strategy creation."""
        strategy = get_strategy("standard")

        assert strategy is not None
        assert strategy.name == "standard"
        assert hasattr(strategy, "retrieve")
        assert hasattr(strategy, "should_use")

    def test_none_strategy(self):
        """Test none strategy."""
        strategy = get_strategy("none")

        # should_use should return False (never selected automatically)
        session_state = {"turn_count": 0, "last_message": "test"}
        assert not strategy.should_use(session_state)

        # retrieve should return empty list
        results = asyncio.run(strategy.retrieve(session_state))
        assert results == []

    def test_standard_strategy(self):
        """Test standard strategy."""
        strategy = get_strategy("standard")

        # should_use should return True (default fallback)
        session_state = {"turn_count": 0, "last_message": "test"}
        assert strategy.should_use(session_state)

        # retrieve should return results (may be empty in mock)
        results = asyncio.run(strategy.retrieve(session_state))
        assert isinstance(results, list)


class TestIntegration:
    """Test integration with other components."""

    def test_global_orchestrator_instance(self):
        """Test global orchestrator instance."""
        orchestrator1 = get_retrieval_orchestrator()
        orchestrator2 = get_retrieval_orchestrator()

        assert orchestrator1 is orchestrator2  # Same instance

    def test_initialization(self):
        """Test initialization function."""
        orchestrator = initialize_retrieval_orchestrator()

        assert orchestrator is not None
        assert isinstance(orchestrator, RetrievalOrchestrator)

    @patch("app.core.retrieval.orchestrator.get_dfc_integration")
    def test_dfc_integration_call(self, mock_dfc_integration):
        """Test DFC integration is called during promotion."""
        mock_dfc_integration.return_value.promote_tool_result = AsyncMock()

        orchestrator = initialize_retrieval_orchestrator()

        session_state = {
            "turn_count": 0,
            "last_message": "test",
            "previous_messages": [],
        }

        # Mock UKB router to return results
        with patch.object(
            orchestrator.strategies["standard"], "retrieve"
        ) as mock_retrieve:
            mock_retrieve.return_value = [RetrievedChunk("test content", "test", 0.8)]

            results = asyncio.run(
                orchestrator.execute(RetrievalStrategy.STANDARD, session_state)
            )

            # Verify DFC integration was called
            mock_dfc_integration.return_value.promote_tool_result.assert_called_once()
            assert len(results) == 1
