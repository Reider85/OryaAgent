name: Security Audit Failure
description: Automatically created when pip-audit detects high/critical vulnerabilities
title: "[SECURITY] Vulnerability Alert: {{ env.AUDIT_SUMMARY }}"
labels: ["security", "dependencies", "automated"]
assignees: ["Reider85"]

---

## Security Alert Detected

{{ env.AUDIT_SUMMARY }}

### Vulnerability Summary
- **Total vulnerabilities found**: {{ env.AUDIT_COUNT }}
- **High/Critical vulnerabilities**: {{ env.AUDIT_HIGH_CRITICAL }}
- **Audit triggered by**: CI pipeline security check

### High/Critical Vulnerabilities

{{#each env.AUDIT_JSON.vulnerabilities}}
{{#if (eq this.severity "CRITICAL")}}
### 🚨 CRITICAL: {{this.package}} ({{this.cve_id}})
- **CVSS Score**: {{this.cvss_score}}
- **Fix Version**: {{this.fix}}
- **Description**: {{this.vulnerability}}

**Action Required**: Update to patched version immediately or provide security justification.

{{/if}}
{{#if (eq this.severity "HIGH")}}
### ⚠️ HIGH: {{this.package}} ({{this.cve_id}})
- **CVSS Score**: {{this.cvss_score}}
- **Fix Version**: {{this.fix}}
- **Description**: {{this.vulnerability}}

**Action Required**: Update to patched version or provide security justification.

{{/if}}
{{/each}}

### Next Steps

1. **Update Dependencies**: Run `uv pip install --upgrade <package>` for each vulnerable package
2. **Review Changes**: Test the updated dependencies in your environment
3. **Commit Fix**: Create a PR with dependency updates
4. **Security Review**: For critical issues, involve security team review

### Additional Information

- **Full Audit Data**: See the attached JSON data for complete vulnerability details
- **NVD Database**: Visit [NVD CVE Database](https://nvd.nist.gov/vuln/search) for more information
- **CVSS Scoring**: [CVSS v3.1 Calculator](https://www.first.org/cvss/calculator/3.1)

### Pipeline Information

- **Workflow**: `.github/workflows/ci.yml`
- **Job**: `audit`
- **Trigger**: Automatic on every CI run

---

**Note**: This issue was automatically created by the CI security audit system. Please address high/critical vulnerabilities before merging any changes to main branch.