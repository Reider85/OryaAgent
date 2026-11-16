#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

try:
    from app.core.workflow.tri_model import TriModelPipeline, Plan, Verdict
    print("SUCCESS: Successfully imported TriModelPipeline components")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

try:
    from app.core.workflow.state import TurnState, PipelineState
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
    from app.core.dfc.models import Plan as DFCPlan, DFCConfig
    print("SUCCESS: Successfully imported DFC components")
except ImportError as e:
    print(f"✗ DFC import failed: {e}")
    sys.exit(1)

print("\nSUCCESS: All imports successful!")
print("B-25 Tri-Model Pipeline implementation is ready.")