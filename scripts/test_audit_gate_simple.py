#!/usr/bin/env python3
"""
Simple test script for audit_gate.py functionality without network calls.
"""

import json
import os
import tempfile
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from audit_gate import get_severity_from_cvss


def test_severity_classification():
    """Test CVSS to severity classification."""
    assert get_severity_from_cvss(9.5) == "CRITICAL"
    assert get_severity_from_cvss(8.0) == "HIGH"
    assert get_severity_from_cvss(5.5) == "MEDIUM"
    assert get_severity_from_cvss(2.0) == "LOW"
    assert get_severity_from_cvss(None) == "UNKNOWN"
    print("SUCCESS: Severity classification tests passed")


def test_audit_gate_script_exists():
    """Test that the audit_gate.py script exists and is importable."""
    audit_gate_path = Path(__file__).parent / "audit_gate.py"
    assert audit_gate_path.exists(), "audit_gate.py should exist"
    
    # Test basic import
    import audit_gate
    assert hasattr(audit_gate, 'get_severity_from_cvss')
    assert hasattr(audit_gate, 'analyze_audit_results')
    print("SUCCESS: audit_gate.py script is importable")


def test_issue_template_exists():
    """Test that the issue template exists."""
    template_path = Path(__file__).parent.parent / ".github" / "ISSUE_TEMPLATE" / "audit_failure.md"
    assert template_path.exists(), "audit_failure.md should exist"
    
    with open(template_path, 'r', encoding='utf-8') as f:
        content = f.read()
        assert "Security Alert Detected" in content
        assert "{{ env.AUDIT_SUMMARY }}" in content
        assert "{{ env.AUDIT_COUNT }}" in content
    print("SUCCESS: Issue template exists and has required placeholders")


def test_ci_workflow_updated():
    """Test that the CI workflow has been updated."""
    ci_path = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
    assert ci_path.exists(), "ci.yml should exist"
    
    with open(ci_path, 'r', encoding='utf-8') as f:
        content = f.read()
        assert "Audit (block on high/critical)" in content
        assert "Audit (report all)" in content
        assert "File security issue" in content
        assert "NVD_API_KEY" in content
    print("SUCCESS: CI workflow has been updated with audit gate")


def main():
    """Run all tests."""
    print("Running audit_gate.py tests...")
    
    test_severity_classification()
    test_audit_gate_script_exists()
    test_issue_template_exists()
    test_ci_workflow_updated()
    
    print("\nSUCCESS: All tests passed!")
    print("\nNext steps:")
    print("1. Add NVD_API_KEY to GitHub repository secrets")
    print("2. Test with real data: uv run pip-audit --strict --output json > audit.json")
    print("3. Run: python scripts/audit_gate.py audit.json")


if __name__ == "__main__":
    main()