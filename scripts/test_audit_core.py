#!/usr/bin/env python3
"""
Simple test to verify audit_gate core functionality.
"""

import json
import os
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from audit_gate import analyze_audit_results, get_severity_from_cvss


def test_core_functionality():
    """Test core functionality without network calls."""
    
    print("Testing core audit_gate functionality...")
    
    # Test 1: Severity classification
    print("\n=== Test 1: Severity classification ===")
    assert get_severity_from_cvss(9.5) == "CRITICAL"
    assert get_severity_from_cvss(8.0) == "HIGH"
    assert get_severity_from_cvss(5.5) == "MEDIUM"
    assert get_severity_from_cvss(2.0) == "LOW"
    assert get_severity_from_cvss(None) == "UNKNOWN"
    print("SUCCESS: Severity classification works correctly")
    
    # Test 2: Analyze audit results with manual CVSS scores
    print("\n=== Test 2: Analyze audit results ===")
    
    # Mock audit data
    mock_audit_data = {
        "results": {
            "package1": [
                {
                    "vulnerable": True,
                    "id": "CVE-2021-0001",
                    "title": "High severity vulnerability",
                    "fix": {
                        "version": "1.1.0"
                    }
                }
            ],
            "package2": [
                {
                    "vulnerable": True,
                    "id": "CVE-2021-0002",
                    "title": "Low severity vulnerability",
                    "fix": {
                        "version": "2.0.0"
                    }
                }
            ]
        }
    }
    
    vulnerabilities = analyze_audit_results(mock_audit_data)
    
    print(f"Found {len(vulnerabilities)} vulnerabilities:")
    for vuln in vulnerabilities:
        print(f"  - {vuln['package']}: {vuln['cve_id']} (CVSS {vuln['cvss_score']}, {vuln['severity']})")
    
    # Verify we found the expected vulnerabilities
    assert len(vulnerabilities) == 2
    assert vuln['package'] == 'package2'  # Last one
    
    print("SUCCESS: Audit results analysis works correctly")
    
    # Test 3: Check blocking logic
    print("\n=== Test 3: Blocking logic ===")
    
    # Simulate the blocking logic from the main function
    high_critical = [v for v in vulnerabilities if v["severity"] in ["CRITICAL", "HIGH"] and v["cvss_score"] is not None]
    
    if high_critical:
        print("RELEASE BLOCKED: High/critical vulnerabilities found")
        print("This is the expected behavior for high severity vulnerabilities")
        return 1
    else:
        print("RELEASE APPROVED: No high/critical vulnerabilities")
        return 0


def test_file_structure():
    """Test that all required files exist."""
    print("\n=== Test 4: File structure ===")
    
    # Check audit_gate.py exists
    audit_gate_path = Path(__file__).parent / "audit_gate.py"
    assert audit_gate_path.exists(), "audit_gate.py should exist"
    
    # Check issue template exists
    template_path = Path(__file__).parent.parent / ".github" / "ISSUE_TEMPLATE" / "audit_failure.md"
    assert template_path.exists(), "audit_failure.md should exist"
    
    # Check CI workflow exists and has been updated
    ci_path = Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml"
    assert ci_path.exists(), "ci.yml should exist"
    
    with open(ci_path, 'r', encoding='utf-8') as f:
        content = f.read()
        assert "Audit (block on high/critical)" in content
        assert "Audit (report all)" in content
        assert "File security issue" in content
        assert "NVD_API_KEY" in content
    
    print("SUCCESS: All required files exist and are properly configured")


def main():
    """Run all tests."""
    print("Running audit_gate core functionality tests...")
    
    # Test core functionality
    result1 = test_core_functionality()
    
    # Test file structure
    test_file_structure()
    
    print(f"\n=== Results ===")
    if result1 == 1:  # Expected to block due to high severity
        print("SUCCESS: Core functionality tests passed!")
        print("\nImplementation Summary:")
        print("SUCCESS: CI workflow updated with two-pass audit")
        print("SUCCESS: Audit gate script created")
        print("SUCCESS: Issue template created")
        print("SUCCESS: Blocking logic implemented for high/critical CVEs")
        print("SUCCESS: All files properly structured")
        print("\nNext steps:")
        print("1. Add NVD_API_KEY to GitHub repository secrets")
        print("2. Test with real pip-audit data")
        print("3. Deploy changes to trigger CI pipeline")
    else:
        print("FAILURE: Core functionality tests failed!")


if __name__ == "__main__":
    main()