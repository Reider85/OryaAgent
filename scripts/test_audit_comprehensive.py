#!/usr/bin/env python3
"""
Comprehensive test for audit_gate functionality with mocked NVD API.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

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


@patch('urllib.request.urlopen')
def test_low_vulnerabilities(mock_urlopen):
    """Test with low severity vulnerabilities - should approve."""
    # Mock NVD API response for low severity
    mock_response = type('MockResponse', (), {
        'read': lambda: json.dumps({
            "vulnerabilities": [{
                "cve": {
                    "metrics": {
                        "cvssMetricV31": [{
                            "cvssData": {
                                "baseScore": 3.5
                            }
                        }]
                    }
                }
            }]
        }).encode()
    })()
    mock_urlopen.return_value = mock_response
    
    # Mock audit data with low severity vulnerabilities
    mock_audit_data = {
        "results": {
            "requests": [
                {
                    "vulnerable": True,
                    "id": "CVE-2021-3177",
                    "title": "Low severity issue in requests",
                    "fix": {
                        "version": "2.26.0"
                    }
                }
            ]
        }
    }
    
    vulnerabilities = analyze_audit_results(mock_audit_data)
    
    print(f"Found {len(vulnerabilities)} vulnerabilities:")
    for vuln in vulnerabilities:
        print(f"  - {vuln['package']}: {vuln['cve_id']} (CVSS {vuln['cvss_score']}, {vuln['severity']})")
    
    # Should approve release since no high/critical vulnerabilities
    high_critical = [v for v in vulnerabilities if v["severity"] in ["CRITICAL", "HIGH"] and v["cvss_score"] is not None]
    if not high_critical:
        print("SUCCESS: RELEASE APPROVED - No high/critical vulnerabilities")
        return 0
    else:
        print("FAILURE: RELEASE BLOCKED - Unexpected high/critical vulnerabilities")
        return 1


@patch('urllib.request.urlopen')
def test_high_vulnerabilities(mock_urlopen):
    """Test with high severity vulnerabilities - should block."""
    # Mock NVD API response for high severity
    mock_response = type('MockResponse', (), {
        'read': lambda: json.dumps({
            "vulnerabilities": [{
                "cve": {
                    "metrics": {
                        "cvssMetricV31": [{
                            "cvssData": {
                                "baseScore": 8.5
                            }
                        }]
                    }
                }
            }]
        }).encode()
    })()
    mock_urlopen.return_value = mock_response
    
    # Mock audit data with high severity vulnerability
    mock_audit_data = {
        "results": {
            "openssl": [
                {
                    "vulnerable": True,
                    "id": "CVE-2021-3711",
                    "title": "Remote Code Execution in OpenSSL",
                    "fix": {
                        "version": "1.1.1k"
                    }
                }
            ]
        }
    }
    
    vulnerabilities = analyze_audit_results(mock_audit_data)
    
    print(f"Found {len(vulnerabilities)} vulnerabilities:")
    for vuln in vulnerabilities:
        print(f"  - {vuln['package']}: {vuln['cve_id']} (CVSS {vuln['cvss_score']}, {vuln['severity']})")
    
    # Should block release since high severity vulnerability found
    high_critical = [v for v in vulnerabilities if v["severity"] in ["CRITICAL", "HIGH"] and v["cvss_score"] is not None]
    if high_critical:
        print("SUCCESS: RELEASE BLOCKED - High/critical vulnerabilities found")
        return 1
    else:
        print("FAILURE: RELEASE APPROVED - Should have been blocked")
        return 0


@patch('urllib.request.urlopen')
def test_mixed_vulnerabilities(mock_urlopen):
    """Test with mixed severity vulnerabilities - should block due to high severity."""
    def mock_urlopen_side_effect(req):
        # Return different responses based on CVE ID
        if "CVE-2021-3711" in req.get_full_url():
            # High severity
            return type('MockResponse', (), {
                'read': lambda: json.dumps({
                    "vulnerabilities": [{
                        "cve": {
                            "metrics": {
                                "cvssMetricV31": [{
                                    "cvssData": {
                                        "baseScore": 8.5
                                    }
                                }]
                            }
                        }
                    }]
                }).encode()
            })()
        else:
            # Low severity
            return type('MockResponse', (), {
                'read': lambda: json.dumps({
                    "vulnerabilities": [{
                        "cve": {
                            "metrics": {
                                "cvssMetricV31": [{
                                    "cvssData": {
                                        "baseScore": 3.5
                                    }
                                }]
                            }
                        }
                    }]
                }).encode()
            })()
    
    mock_urlopen.side_effect = mock_urlopen_side_effect
    
    # Mock audit data with mixed severity vulnerabilities
    mock_audit_data = {
        "results": {
            "openssl": [
                {
                    "vulnerable": True,
                    "id": "CVE-2021-3711",
                    "title": "Remote Code Execution in OpenSSL",
                    "fix": {
                        "version": "1.1.1k"
                    }
                }
            ],
            "requests": [
                {
                    "vulnerable": True,
                    "id": "CVE-2021-3177",
                    "title": "Low severity issue in requests",
                    "fix": {
                        "version": "2.26.0"
                    }
                }
            ]
        }
    }
    
    vulnerabilities = analyze_audit_results(mock_audit_data)
    
    print(f"Found {len(vulnerabilities)} vulnerabilities:")
    for vuln in vulnerabilities:
        print(f"  - {vuln['package']}: {vuln['cve_id']} (CVSS {vuln['cvss_score']}, {vuln['severity']})")
    
    # Should block release due to high severity vulnerability
    high_critical = [v for v in vulnerabilities if v["severity"] in ["CRITICAL", "HIGH"] and v["cvss_score"] is not None]
    if high_critical:
        print("SUCCESS: RELEASE BLOCKED - High/critical vulnerabilities found")
        return 1
    else:
        print("FAILURE: RELEASE APPROVED - Should have been blocked")
        return 0


def main():
    """Run all tests."""
    print("Running comprehensive audit_gate tests...")
    
    test_severity_classification()
    
    print("\n=== Test 1: Low severity vulnerabilities (should approve) ===")
    result1 = test_low_vulnerabilities()
    
    print("\n=== Test 2: High severity vulnerabilities (should block) ===")
    result2 = test_high_vulnerabilities()
    
    print("\n=== Test 3: Mixed severity vulnerabilities (should block) ===")
    result3 = test_mixed_vulnerabilities()
    
    print(f"\n=== Results ===")
    print(f"Test 1 (low severity): {'PASS' if result1 == 0 else 'FAIL'}")
    print(f"Test 2 (high severity): {'PASS' if result2 == 1 else 'FAIL'}")
    print(f"Test 3 (mixed severity): {'PASS' if result3 == 1 else 'FAIL'}")
    
    if result1 == 0 and result2 == 1 and result3 == 1:
        print("\nSUCCESS: All tests passed!")
    else:
        print("\nFAILURE: Some tests failed!")


if __name__ == "__main__":
    main()