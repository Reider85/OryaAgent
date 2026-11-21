#!/usr/bin/env python3
"""
Test script to simulate NVD API responses for testing.
"""

import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from audit_gate import analyze_audit_results


def test_with_mock_nvd_data():
    """Test with simulated NVD API responses."""

    # Mock audit data with low severity vulnerabilities
    mock_audit_data = {
        "results": {
            "requests": [
                {
                    "vulnerable": True,
                    "id": "CVE-2021-3177",
                    "title": "Low severity issue in requests",
                    "fix": {"version": "2.26.0"},
                }
            ],
            "flask": [
                {
                    "vulnerable": True,
                    "id": "CVE-2020-25717",
                    "title": "Medium severity issue in Flask",
                    "fix": {"version": "2.0.1"},
                }
            ],
        }
    }

    vulnerabilities = analyze_audit_results(mock_audit_data)

    print(f"Found {len(vulnerabilities)} vulnerabilities:")
    for vuln in vulnerabilities:
        print(
            f"  - {vuln['package']}: {vuln['cve_id']} (CVSS {vuln['cvss_score']}, {vuln['severity']})"
        )

    # Test that the script would approve if no high/critical vulnerabilities
    high_critical = [
        v
        for v in vulnerabilities
        if v["severity"] in ["CRITICAL", "HIGH"] and v["cvss_score"] is not None
    ]
    if high_critical:
        print("RELEASE BLOCKED: High/critical vulnerabilities found")
        return 1
    else:
        print("RELEASE APPROVED: No high/critical vulnerabilities")
        return 0


def test_with_critical_vulnerability():
    """Test with a critical vulnerability."""

    mock_audit_data = {
        "results": {
            "openssl": [
                {
                    "vulnerable": True,
                    "id": "CVE-2021-3711",
                    "title": "Remote Code Execution in OpenSSL",
                    "fix": {"version": "1.1.1k"},
                }
            ]
        }
    }

    vulnerabilities = analyze_audit_results(mock_audit_data)

    print(f"Found {len(vulnerabilities)} vulnerabilities:")
    for vuln in vulnerabilities:
        print(
            f"  - {vuln['package']}: {vuln['cve_id']} (CVSS {vuln['cvss_score']}, {vuln['severity']})"
        )

    # Test that the script would block with critical vulnerabilities
    high_critical = [
        v
        for v in vulnerabilities
        if v["severity"] in ["CRITICAL", "HIGH"] and v["cvss_score"] is not None
    ]
    if high_critical:
        print("RELEASE BLOCKED: High/critical vulnerabilities found")
        return 1
    else:
        print("RELEASE APPROVED: No high/critical vulnerabilities")
        return 0


if __name__ == "__main__":
    print("Testing audit gate with mock data...")

    print("\n=== Test 1: Normal vulnerabilities ===")
    result1 = test_with_mock_nvd_data()

    print("\n=== Test 2: Critical vulnerability ===")
    result2 = test_with_critical_vulnerability()

    print("\n=== Results ===")
    print(f"Test 1 (normal): {'PASS' if result1 == 0 else 'FAIL'}")
    print(f"Test 2 (critical): {'PASS' if result2 == 1 else 'FAIL'}")

    if result1 == 0 and result2 == 1:
        print("\nSUCCESS: All tests passed!")
    else:
        print("\nFAILURE: Some tests failed!")
