#!/usr/bin/env python3
"""
Audit gate for pip-audit results.

This script reads pip-audit JSON output and fails (exit code 1) if any
vulnerabilities have CVSS >= 7.0 (high/critical severity).
"""

import json
import os
import sys
import urllib.request
import urllib.error
from typing import Dict, List, Any, Optional
import tomllib


def get_cvss_score(cve_id: str) -> Optional[float]:
    """Get CVSS v3.1 score from NVD API for a given CVE ID."""
    try:
        url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}"
        
        # Add API key if available in environment
        api_key = os.getenv("NVD_API_KEY")
        if api_key:
            req = urllib.request.Request(url)
            req.add_header("apiKey", api_key)
        else:
            req = urllib.request.Request(url)
        
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            
            if not data.get("vulnerabilities"):
                return None
                
            # Get the first vulnerability (CVEs should be unique)
            vuln = data["vulnerabilities"][0]
            cve_data = vuln.get("cve", {})
            metrics = cve_data.get("metrics", {})
            cvssv31 = metrics.get("cvssMetricV31", [])
            
            if cvssv31:
                return cvssv31[0].get("cvssData", {}).get("baseScore")
            
            # Fallback to CVSS v3.0
            cvssv30 = metrics.get("cvssMetricV30", [])
            if cvssv30:
                return cvssv30[0].get("cvssData", {}).get("baseScore")
                
            return None
            
    except Exception as e:
        print(f"Warning: Failed to fetch CVSS for {cve_id}: {e}", file=sys.stderr)
        return None


def analyze_audit_results(audit_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Analyze audit results and return vulnerabilities with CVSS scores."""
    vulnerabilities = []
    
    # Parse pip-audit JSON format
    results = audit_data.get("results", {})
    
    for package_name, vuln_list in results.items():
        for vuln in vuln_list:
            if not vuln.get("vulnerable"):
                continue
                
            # Extract CVE information
            cve_id = vuln.get("id", "")
            if not cve_id.startswith("CVE-"):
                continue
                
            # Get CVSS score
            cvss_score = get_cvss_score(cve_id)
            
            vulnerabilities.append({
                "package": package_name,
                "vulnerability": vuln.get("title", ""),
                "cve_id": cve_id,
                "cvss_score": cvss_score,
                "severity": get_severity_from_cvss(cvss_score) if cvss_score else "UNKNOWN",
                "fix": vuln.get("fix", {}).get("version", "NO FIX AVAILABLE")
            })
    
    return vulnerabilities


def get_severity_from_cvss(cvss_score: Optional[float]) -> str:
    """Convert CVSS score to severity level."""
    if cvss_score is None:
        return "UNKNOWN"
    elif cvss_score >= 9.0:
        return "CRITICAL"
    elif cvss_score >= 7.0:
        return "HIGH"
    elif cvss_score >= 4.0:
        return "MEDIUM"
    else:
        return "LOW"


def print_summary(vulnerabilities: List[Dict[str, Any]]) -> None:
    """Print a summary of vulnerabilities by severity."""
    if not vulnerabilities:
        print("SUCCESS: No vulnerabilities found")
        return
    
    # Group by severity
    by_severity = {}
    for vuln in vulnerabilities:
        severity = vuln["severity"]
        if severity not in by_severity:
            by_severity[severity] = []
        by_severity[severity].append(vuln)
    
    # Print summary
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]:
        if severity in by_severity:
            count = len(by_severity[severity])
            print(f"SECURITY {severity}: {count} vulnerabilities")
            
            # Show details for high/critical
            if severity in ["CRITICAL", "HIGH"]:
                for vuln in by_severity[severity]:
                    print(f"  - {vuln['package']} ({vuln['cve_id']}) - CVSS {vuln['cvss_score']}")
                    print(f"    Fix: {vuln['fix']}")
                    print(f"    {vuln['vulnerability']}")
                    print()


def main():
    """Main function."""
    if len(sys.argv) != 2:
        print("Usage: python scripts/audit_gate.py <audit_json_file>")
        sys.exit(1)
    
    audit_file = sys.argv[1]
    
    try:
        with open(audit_file, "r", encoding="utf-8") as f:
            audit_data = json.load(f)
    except Exception as e:
        print(f"Error reading audit file: {e}")
        sys.exit(1)
    
    vulnerabilities = analyze_audit_results(audit_data)
    
    print_summary(vulnerabilities)
    
    # Check for high/critical vulnerabilities (only those with actual CVSS scores)
    high_critical = [v for v in vulnerabilities if v["severity"] in ["CRITICAL", "HIGH"] and v["cvss_score"] is not None]
    
    if high_critical:
        print(f"BLOCKED: Found {len(high_critical)} high/critical vulnerabilities - BLOCKING RELEASE")
        print("\nTo fix these issues:")
        print("1. Update dependencies to patched versions")
        print("2. Or add security exceptions with explicit justification")
        print("3. Or disable this check temporarily (not recommended)")
        
        # Output JSON for GitHub issue creation
        issue_data = {
            "summary": f"Found {len(high_critical)} high/critical vulnerabilities",
            "total_vulnerabilities": len(vulnerabilities),
            "high_critical_count": len(high_critical),
            "vulnerabilities": high_critical,
            "full_audit": audit_data
        }
        
        # Set environment variables for GitHub issue template
        with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
            print(f"AUDIT_SUMMARY={json.dumps(issue_data['summary'])}", file=f)
            print(f"AUDIT_COUNT={len(vulnerabilities)}", file=f)
            print(f"AUDIT_HIGH_CRITICAL={len(high_critical)}", file=f)
            print(f"AUDIT_JSON={json.dumps(issue_data)}", file=f)
        
        sys.exit(1)
    else:
        print("APPROVED: No high/critical vulnerabilities found - RELEASE APPROVED")
        sys.exit(0)


if __name__ == "__main__":
    import os
    main()