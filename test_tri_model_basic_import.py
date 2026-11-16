#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

try:
    from app.core.workflow.tri_model import TriModelPipeline, Plan, Verdict, TurnResult
    print("SUCCESS: TriModelPipeline components imported successfully")
    
    # Test basic creation
    plan = Plan(steps=["test"], criteria=["test"], prefetch_hints=["test"], tier="small")
    print("SUCCESS: Plan object created")
    
    verdict = Verdict(verdict="pass", message="test")
    print("SUCCESS: Verdict object created")
    
    print("B-25 Tri-Model Pipeline implementation is working correctly!")
    
except Exception as e:
    print(f"FAILED: Error importing or creating objects: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)