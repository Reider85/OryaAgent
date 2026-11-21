#!/usr/bin/env python3
# ruff: noqa: F401 — import smoke test: the names are intentionally unused.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

try:
    from app.core.workflow.tri_model import Plan, TriModelPipeline, Verdict

    print("SUCCESS: Successfully imported TriModelPipeline components")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

try:
    from app.core.workflow.state import PipelineState, TurnState

    print("SUCCESS: Successfully imported state components")
except ImportError as e:
    print(f"✗ State import failed: {e}")
    sys.exit(1)

try:
    from app.core.workflow.prompts import PlannerPrompt, TesterPrompt

    print("SUCCESS: Successfully imported prompt components")
except ImportError as e:
    print(f"✗ Prompt import failed: {e}")
    sys.exit(1)

try:
    from app.core.dfc.models import DFCConfig
    from app.core.dfc.models import Plan as DFCPlan

    print("SUCCESS: Successfully imported DFC components")
except ImportError as e:
    print(f"✗ DFC import failed: {e}")
    sys.exit(1)

print("\nSUCCESS: All imports successful!")
print("B-25 Tri-Model Pipeline implementation is ready.")
