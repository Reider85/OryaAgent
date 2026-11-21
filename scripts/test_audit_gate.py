#!/usr/bin/env python3
"""
Test script for audit_gate.py functionality.
"""

import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from audit_gate import analyze_audit_results, get_severity_from_cvss


def test_severity_classification():
    """Test CVSS to severity classification."""
    assert get_severity_from_cvss(9.5) == "CRITICAL"
    assert get_severity_from_cvss(8.0) == "HIGH"
    assert get_severity_from_cvss(5.5) == "MEDIUM"
    assert get_severity_from_cvss(2.0) == "LOW"
    assert get_severity_from_cvss(None) == "UNKNOWN"
    print("SUCCESS: Severity classification tests passed")


def test_analyze_audit_results():
    """Test audit results analysis with mock data."""
    # Mock audit data with a high severity vulnerability
    mock_audit_data = {
        "results": {
            "requests": [
                {
                    "vulnerable": True,
                    "id": "CVE-2021-3177",
                    "title": "Authentication Bypass in requests",
                    "fix": {"version": "2.26.0"},
                }
            ]
        }
    }

    vulnerabilities = analyze_audit_results(mock_audit_data)

    assert len(vulnerabilities) == 1
    assert vulnerabilities[0]["package"] == "requests"
    assert vulnerabilities[0]["cve_id"] == "CVE-2021-3177"
    assert vulnerabilities[0]["severity"] == "HIGH"  # This would be mocked CVSS score

    print("SUCCESS: Audit results analysis tests passed")


def test_empty_audit_results():
    """Test handling of empty audit results."""
    empty_data = {"results": {}}
    vulnerabilities = analyze_audit_results(empty_data)
    assert len(vulnerabilities) == 0
    print("SUCCESS: Empty audit results test passed")


def test_non_vulnerable_packages():
    """Test handling of non-vulnerable packages."""
    mock_data = {
        "results": {
            "safe-package": [
                {
                    "vulnerable": False,
                    "id": "CVE-2021-0000",
                    "title": "Not actually vulnerable",
                    "fix": {"version": "1.0.0"},
                }
            ]
        }
    }

    vulnerabilities = analyze_audit_results(mock_data)
    assert len(vulnerabilities) == 0
    print("SUCCESS: Non-vulnerable packages test passed")


def main():
    """Run all tests."""
    print("Running audit_gate.py tests...")

    test_severity_classification()
    test_analyze_audit_results()
    test_empty_audit_results()
    test_non_vulnerable_packages()

    print("\nSUCCESS: All tests passed!")
    print("\nTo test with real data:")
    print("1. Run: uv run pip-audit --strict --output json > audit.json")
    print("2. Run: python scripts/audit_gate.py audit.json")


if __name__ == "__main__":
    main()
