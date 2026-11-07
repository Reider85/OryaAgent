"""State models for Tri-Model Pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from app.core.dfc.models import Plan as DFCPlan  # Avoid name collision


@dataclass
class Plan:
    """Plan dataclass for Tri-Model Pipeline."""
    steps: List[str]
    criteria: List[str]
    prefetch_hints: List[str]
    tier: str  # small|large|tournament
    cacheable_prefix: str = ""
    dynamic_suffix: str = ""
    session_id: Optional[str] = None
    created_at: Optional[float] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "steps": self.steps,
            "criteria": self.criteria,
            "prefetch_hints": self.prefetch_hints,
            "tier": self.tier,
            "cacheable_prefix": self.cacheable_prefix,
            "dynamic_suffix": self.dynamic_suffix,
            "session_id": self.session_id,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        """Create from dictionary."""
        return cls(
            steps=data.get("steps", []),
            criteria=data.get("criteria", []),
            prefetch_hints=data.get("prefetch_hints", []),
            tier=data.get("tier", "small"),
            cacheable_prefix=data.get("cacheable_prefix", ""),
            dynamic_suffix=data.get("dynamic_suffix", ""),
            session_id=data.get("session_id"),
            created_at=data.get("created_at"),
        )


@dataclass
class Verdict:
    """Test verdict for Tri-Model Pipeline."""
    verdict: str  # pass|fail|replan
    message: str = ""
    confidence: float = 1.0
    failed_criteria: List[str] = field(default_factory=list)
    execution_diff: Optional[str] = None
    test_duration_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "verdict": self.verdict,
            "message": self.message,
            "confidence": self.confidence,
            "failed_criteria": self.failed_criteria,
            "execution_diff": self.execution_diff,
            "test_duration_ms": self.test_duration_ms,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Verdict":
        """Create from dictionary."""
        return cls(
            verdict=data.get("verdict", "pass"),
            message=data.get("message", ""),
            confidence=data.get("confidence", 1.0),
            failed_criteria=data.get("failed_criteria", []),
            execution_diff=data.get("execution_diff"),
            test_duration_ms=data.get("test_duration_ms", 0.0),
        )


@dataclass
class TurnState:
    """State for a single turn in Tri-Model Pipeline."""
    session_id: str
    turn_id: str
    task: str
    plan: Optional[Plan] = None
    execution_result: Optional[Dict[str, Any]] = None
    verdict: Optional[Verdict] = None
    replan_count: int = 0
    current_step: int = 0
    tools_used: List[str] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "task": self.task,
            "plan": self.plan.to_dict() if self.plan else None,
            "execution_result": self.execution_result,
            "verdict": self.verdict.to_dict() if self.verdict else None,
            "replan_count": self.replan_count,
            "current_step": self.current_step,
            "tools_used": self.tools_used,
            "artifacts": self.artifacts,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TurnState":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            turn_id=data["turn_id"],
            task=data["task"],
            plan=Plan.from_dict(data["plan"]) if data.get("plan") else None,
            execution_result=data.get("execution_result"),
            verdict=Verdict.from_dict(data["verdict"]) if data.get("verdict") else None,
            replan_count=data.get("replan_count", 0),
            current_step=data.get("current_step", 0),
            tools_used=data.get("tools_used", []),
            artifacts=data.get("artifacts", {}),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )
    
    def update(self, **kwargs) -> None:
        """Update state fields."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = time.time()


@dataclass
class PipelineState:
    """State for the entire Tri-Model Pipeline."""
    session_id: str
    turns: List[TurnState] = field(default_factory=list)
    current_turn: Optional[TurnState] = None
 statistics: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "turns": [turn.to_dict() for turn in self.turns],
            "current_turn": self.current_turn.to_dict() if self.current_turn else None,
            "statistics": self.statistics,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineState":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            turns=[TurnState.from_dict(turn_data) for turn_data in data.get("turns", [])],
            current_turn=TurnState.from_dict(data["current_turn"]) if data.get("current_turn") else None,
            statistics=data.get("statistics", {}),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )
    
    def add_turn(self, turn: TurnState) -> None:
        """Add a turn to the pipeline state."""
        self.turns.append(turn)
        self.current_turn = turn
        self.updated_at = time.time()
    
    def update_statistics(self, key: str, value: Any) -> None:
        """Update statistics."""
        self.statistics[key] = value
        self.updated_at = time.time()


@dataclass
class ExecutionResult:
    """Result of execution step."""
    success: bool
    message: str
    tools_used: List[str]
    output: str
    artifacts: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "message": self.message,
            "tools_used": self.tools_used,
            "output": self.output,
            "artifacts": self.artifacts,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionResult":
        """Create from dictionary."""
        return cls(
            success=data.get("success", True),
            message=data.get("message", ""),
            tools_used=data.get("tools_used", []),
            output=data.get("output", ""),
            artifacts=data.get("artifacts", {}),
            duration_ms=data.get("duration_ms", 0.0),
            error=data.get("error"),
        )


@dataclass
class TestResult:
    """Result of testing step."""
    passed: bool
    message: str
    confidence: float
    failed_criteria: List[str]
    execution_diff: Optional[str] = None
    duration_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "passed": self.passed,
            "message": self.message,
            "confidence": self.confidence,
            "failed_criteria": self.failed_criteria,
            "execution_diff": self.execution_diff,
            "duration_ms": self.duration_ms,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestResult":
        """Create from dictionary."""
        return cls(
            passed=data.get("passed", True),
            message=data.get("message", ""),
            confidence=data.get("confidence", 1.0),
            failed_criteria=data.get("failed_criteria", []),
            execution_diff=data.get("execution_diff"),
            duration_ms=data.get("duration_ms", 0.0),
        )


@dataclass
class PipelineConfig:
    """Configuration for Tri-Model Pipeline."""
    max_replans: int = 2
    concurrent_tester: bool = False  # False in BETA, True in PROD
    max_steps_per_plan: int = 5
    timeout_per_step: float = 30.0  # seconds
    enable_artifacts: bool = True
    artifact_storage_path: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineConfig":
        """Create from dictionary."""
        return cls(
            max_replans=data.get("max_replans", 2),
            concurrent_tester=data.get("concurrent_tester", False),
            max_steps_per_plan=data.get("max_steps_per_plan", 5),
            timeout_per_step=data.get("timeout_per_step", 30.0),
            enable_artifacts=data.get("enable_artifacts", True),
            artifact_storage_path=data.get("artifact_storage_path"),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "max_replans": self.max_replans,
            "concurrent_tester": self.concurrent_tester,
            "max_steps_per_plan": self.max_steps_per_plan,
            "timeout_per_step": self.timeout_per_step,
            "enable_artifacts": self.enable_artifacts,
            "artifact_storage_path": self.artifact_storage_path,
        }