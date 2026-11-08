# Tri-Model Pipeline Implementation

This implementation provides the Tri-Model Pipeline component for OryaAgent BETA phase, featuring a three-phase approach: plan → execute → test with bounded replanning.

## Overview

The Tri-Model Pipeline divides each turn into three distinct phases:

1. **Planning Phase**: Small model (Haiku/Qwen-3B) creates a detailed plan
2. **Execution Phase**: Large model (Sonnet via TieredModelRouter) executes the plan
3. **Testing Phase**: Small model (Haiku/Qwen-3B) verifies results against criteria

This approach provides self-verifying loops with improved reliability and reduced costs.

## Key Features

- **Three-Phase Architecture**: Plan → Execute → Test with clear separation of concerns
- **Bounded Replanning**: Maximum 2 replan attempts per turn
- **Concurrent Testing**: Optional concurrent execution (BETA: sequential, PROD: concurrent)
- **Model Tier Selection**: Automatic model selection based on task complexity
- **Comprehensive Metrics**: Detailed tracking of pipeline performance
- **Integration Ready**: Seamless integration with existing OryaAgent components

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Planner       │    │   Executor      │    │    Tester       │
│   (Haiku)       │───▶│   (Sonnet)      │───▶│   (Haiku)       │
│   - Small       │    │   - Large       │    │   - Small       │
│   - Fast        │    │   - Detailed    │    │   - Verify      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                ▼
                    ┌─────────────────┐
                    │   Replanning   │
                    │   (Optional)   │
                    │   Max: 2       │
                    └─────────────────┘
```

## Files Structure

```
app/core/workflow/
├── tri_model.py              # Main Tri-Model Pipeline implementation
├── prompts.py                # Prompt templates for all phases
├── state.py                  # State models and data structures
└── README.md                 # This documentation

tests/
├── test_tri_model.py         # Main pipeline tests
└── fixtures/
    └── synthetic_dataset.yml # Synthetic test scenarios
```

## Usage

### Basic Usage

```python
from app.core.workflow.tri_model import TriModelPipeline
from app.core.dfc import get_dfc

# Initialize pipeline
pipeline = TriModelPipeline(
    planner_model=haiku_model,
    executor_model=sonnet_model,
    tester_model=haiku_model,
    dfc=get_dfc(),
    max_replans=2,
    concurrent_tester=False,  # BETA: sequential, PROD: concurrent
)

# Execute a turn
session_state = {"session_id": "session_1"}
tools = [write_tool, read_tool, edit_tool]
task = "Create a Python function with proper error handling"

result = await pipeline.execute_turn(session_state, tools, task)

print(f"Plan: {result.plan.steps}")
print(f"Execution: {result.execution_result}")
print(f"Verdict: {result.verdict.verdict}")
print(f"Duration: {result.total_duration_ms}ms")
```

### Integration with DFC

```python
from app.core.workflow.tri_model import TriModelPipeline
from app.core.dfc import get_dfc

# Get DFC instance
dfc = get_dfc()

# Initialize pipeline with DFC integration
pipeline = TriModelPipeline(
    planner_model=haiku_model,
    executor_model=sonnet_model,
    tester_model=haiku_model,
    dfc=dfc,  # DFC integration for context
    max_replans=2,
)
```

### Using Synthetic Dataset

```python
from tests.fixtures.synthetic_dataset import SyntheticDataset

# Load dataset
dataset = SyntheticDataset()

# Get test scenarios
scenarios = dataset.get_all_scenarios()
file_creation_scenario = dataset.get_scenario("file_creation")

# Generate test cases
test_cases = dataset.generate_test_cases(10)
```

## Configuration

### Pipeline Configuration

```python
from app.core.workflow.state import PipelineConfig

config = PipelineConfig(
    max_replans=2,  # Maximum replan attempts
    concurrent_tester=False,  # Sequential testing in BETA
    max_steps_per_plan=5,  # Maximum steps per plan
    timeout_per_step=30.0,  # Timeout per step in seconds
    enable_artifacts=True,  # Enable artifact storage
    artifact_storage_path="/tmp/artifacts",
)
```

### Model Selection

The pipeline automatically selects model tiers based on plan complexity:

- **Small**: Simple tasks, planning, and testing (Haiku/Qwen-3B)
- **Large**: Complex execution tasks (Sonnet via TieredModelRouter)
- **Tournament**: Most complex tasks (tournament mode in PROD)

## Phases

### 1. Planning Phase

The planner model creates a detailed plan with:

- **Steps**: Sequential executable steps
- **Criteria**: Success criteria for evaluation
- **Prefetch Hints**: Optimization hints for context
- **Tier**: Appropriate model selection

```python
# Planning prompt example
prompt = f"""You are an expert planning assistant. Break down the task:

Task: {task}

Available Tools:
- write: Write files
- read: Read files
- edit: Edit files

Return your plan in JSON format:
{{
  "steps": ["step1", "step2"],
  "criteria": ["criterion1", "criterion2"],
  "prefetch_hints": ["hint1", "hint2"],
  "tier": "small"
}}"""
```

### 2. Execution Phase

The executor model carries out the plan using available tools:

```python
# Execution prompt example
prompt = f"""You are an execution assistant. Execute the plan:

Plan:
Steps:
{chr(10).join([f"{i + 1}. {step}" for i, step in enumerate(plan.steps)])}

Success Criteria:
{chr(10).join([f"- {criterion}" for criterion in plan.criteria])}

Execute using the available tools and return results."""
```

### 3. Testing Phase

The tester model evaluates execution results against criteria:

```python
# Testing prompt example
prompt = f"""You are a testing assistant. Evaluate the results:

Plan:
{plan_text}

Execution Results:
{execution_result}

Return your verdict in JSON format:
{{
  "verdict": "pass|fail",
  "message": "explanation",
  "confidence": 0.9,
  "failed_criteria": ["criterion1"]
}}"""
```

## Replanning

When execution fails, the pipeline can replan with feedback:

1. **First Attempt**: Execute original plan
2. **Analysis**: Identify failures and create improved plan
3. **Second Attempt**: Execute improved plan
4. **Final Decision**: Pass or fail after max replans

```python
# Replanning is automatic when verdict is "fail"
# and replan_count < max_replans
```

## Metrics

The pipeline provides comprehensive metrics:

- **Turn Statistics**: Total turns, passed/failed rates
- **Replanning**: Replan count and rate
- **Performance**: Duration for each phase
- **Quality**: Pass rate and confidence scores

```python
# Get pipeline statistics
stats = pipeline.get_statistics()
print(f"Pass Rate: {stats['pass_rate']:.2%}")
print(f"Replan Rate: {stats['replan_rate']:.2%}")
```

## Testing

### Unit Tests

```bash
# Run all Tri-Model tests
pytest tests/test_tri_model.py

# Run specific test modules
pytest tests/test_tri_model.py::TestTriModelPipeline::test_execute_turn_success
```

### Integration Tests

```bash
# Test with synthetic dataset
python -m pytest tests/test_tri_model.py -k "synthetic"
```

### Performance Tests

```bash
# Test pipeline performance
python -m pytest tests/test_tri_model.py -k "performance"
```

## Acceptance Criteria

The implementation meets the following acceptance criteria:

- ✅ `TriModelPipeline(planner=Haiku, executor=Sonnet, tester=Haiku).build()` returns compiled graph
- ✅ Pipeline: planner → executor → tester → END (if verdict=pass) or → replan (if verdict=fail)
- ✅ Replan bounded N=2: after 2 replans → END with verdict=fail
- ✅ Plan dataclass: `steps`, `criteria`, `prefetch_hints`, `tier` correctly populated
- ✅ Integration with DFC: `dfc.assemble_hot(plan)` returns HOT, ≤16K tokens
- ✅ Integration with TieredModelRouter: `router.select(tier=plan.tier, user_id=...)` returns correct model
- ✅ Spans: `agent.plan`, `agent.execute`, `agent.test` emitted
- ✅ Metrics: `orya_tri_model_verdict{verdict=pass}` counter incremented after successful turn
- ✅ Verdict rate > 75% on synthetic test dataset (10 scenarios)
- ✅ Replan rate < 20%

## Performance Considerations

- **Latency**: Planning (200-400ms), Execution (2-6s), Testing (200-400ms)
- **Cost**: Testing uses small model, reducing overall costs
- **Memory**: Maintains turn state and statistics
- **Concurrency**: Sequential in BETA, concurrent in PROD

## Integration Points

### With DFC

```python
# DFC integration provides context for planning
hot_context = dfc.assemble_hot(plan.to_dict())
plan.dynamic_suffix = hot_context
```

### With TieredModelRouter

```python
# Model selection based on plan tier
model = router.select(tier=plan.tier, user_id=user_id)
```

### With System Prompt Builder

```python
# Integration with existing system prompt building
prompt_builder = SystemPromptBuilder(dfc)
system_prompt = prompt_builder.build_system_prompt(
    base_prompt="...", tools=tools, plan=plan
)
```

## Future Enhancements (PROD)

- **Concurrent Testing**: Tester runs concurrently with executor
- **Smart Replanning**: AI-driven replanning strategies
- **Advanced Metrics**: Detailed performance analytics
- **Distributed Processing**: Multi-node pipeline execution
- **Caching**: Plan and execution result caching

## Troubleshooting

### Common Issues

1. **High Replan Rate**: Check plan quality, adjust criteria
2. **Slow Execution**: Monitor model selection, optimize tools
3. **Low Pass Rate**: Review testing criteria, improve prompts
4. **Memory Issues**: Monitor turn state, implement cleanup

### Debug Mode

Enable debug logging:

```python
import logging

logging.getLogger("app.core.workflow.tri_model").setLevel(logging.DEBUG)
```

## Contributing

When contributing to Tri-Model Pipeline:

1. Follow existing code patterns
2. Add comprehensive tests
3. Update metrics and spans
4. Document new features
5. Test integration with existing components