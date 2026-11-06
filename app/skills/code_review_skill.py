"""Code review skill implementation.

This skill provides comprehensive code analysis by combining multiple tools
to identify issues, suggest improvements, and enforce best practices.
"""

import logging
from typing import Any

from app.core.skills import Skill
from app.core.tools import get_tools

logger = logging.getLogger(__name__)


class CodeReviewSkill:
    """Code review skill that combines multiple tools for comprehensive analysis."""

    def __init__(self):
        self.skill = Skill(
            name="code-review",
            config={
                "name": "code-review",
                "description": "Comprehensive code review skill that analyzes code quality, identifies issues, and suggests improvements",
                "version": "1.0.0",
                "author": "OryaAgent Team",
                "category": "development",
                "tags": ["code-quality", "review", "static-analysis", "linting"],
                "tools": [
                    "read",
                    "grep",
                    "lsp_diagnostics",
                    "lsp_symbol_search",
                    "lsp_definition",
                    "lsp_references",
                ],
                "hooks": ["auto-format", "auto-lint"],
                "dependencies": [],
                "metadata": {
                    "languages": [
                        "python",
                        "javascript",
                        "typescript",
                        "java",
                        "rust",
                        "go",
                    ],
                    "complexity_threshold": 10,
                    "max_file_size": 1000000,
                    "review_types": [
                        "security",
                        "performance",
                        "readability",
                        "best-practices",
                    ],
                    "supported_patterns": [
                        "**/*.py",
                        "**/*.js",
                        "**/*.ts",
                        "**/*.java",
                        "**/*.rs",
                        "**/*.go",
                    ],
                },
            },
        )

    async def review_file(
        self, file_path: str, review_types: list[str] | None = None
    ) -> dict[str, Any]:
        """Perform a comprehensive review of a single file."""
        if review_types is None:
            review_types = ["security", "performance", "readability", "best-practices"]

        results = {
            "file_path": file_path,
            "review_types": review_types,
            "issues": [],
            "suggestions": [],
            "metrics": {},
            "overall_score": 0,
        }

        try:
            # Read the file content
            read_tool = None
            for tool in get_tools():
                if tool.name == "read":
                    read_tool = tool
                    break

            if not read_tool:
                raise ValueError("Read tool not available")

            # Read file content
            content = await read_tool.ainvoke({"path": file_path})
            results["file_size"] = len(content)

            # Get diagnostics from LSP
            diagnostics = await self._get_diagnostics(file_path)
            results["issues"].extend(diagnostics)

            # Analyze code patterns
            pattern_analysis = await self._analyze_patterns(content, file_path)
            results["metrics"].update(pattern_analysis)

            # Generate suggestions based on review types
            for review_type in review_types:
                suggestions = await self._generate_suggestions(
                    content, file_path, review_type
                )
                results["suggestions"].extend(suggestions)

            # Calculate overall score
            results["overall_score"] = self._calculate_score(results)

        except Exception as e:
            logger.error(f"Error reviewing file {file_path}: {e}")
            results["error"] = str(e)

        return results

    async def _get_diagnostics(self, file_path: str) -> list[dict[str, Any]]:
        """Get diagnostic information from LSP."""
        diagnostics = []

        try:
            # Get diagnostics tool
            lsp_diagnostics = None
            for tool in get_tools():
                if tool.name == "lsp_diagnostics":
                    lsp_diagnostics = tool
                    break

            if lsp_diagnostics:
                lsp_result = await lsp_diagnostics.ainvoke({"file": file_path})
                if isinstance(lsp_result, str):
                    # Parse the diagnostics result
                    diagnostics = self._parse_diagnostics(lsp_result)
                elif isinstance(lsp_result, list):
                    diagnostics = lsp_result

        except Exception as e:
            logger.error(f"Error getting diagnostics for {file_path}: {e}")

        return diagnostics

    def _parse_diagnostics(self, diagnostic_text: str) -> list[dict[str, Any]]:
        """Parse diagnostic text into structured format."""
        diagnostics = []

        # This is a simplified parser - in a real implementation,
        # this would parse actual LSP diagnostic output
        lines = diagnostic_text.split("\n")

        for line in lines:
            if "error" in line.lower() or "warning" in line.lower():
                diagnostics.append(
                    {
                        "type": "error" if "error" in line.lower() else "warning",
                        "message": line.strip(),
                        "line": 1,  # Default line
                        "severity": "high" if "error" in line.lower() else "medium",
                    }
                )

        return diagnostics

    async def _analyze_patterns(self, content: str, file_path: str) -> dict[str, Any]:
        """Analyze code patterns and complexity."""
        patterns = {
            "line_count": len(content.split("\n")),
            "complexity_score": 0,
            "function_count": 0,
            "class_count": 0,
            "comment_ratio": 0.0,
        }

        try:
            # Count functions and classes using grep
            grep_tool = None
            for tool in get_tools():
                if tool.name == "grep":
                    grep_tool = tool
                    break

            if grep_tool:
                # Count function definitions
                func_result = await grep_tool.ainvoke(
                    {"pattern": r"def\s+\w+", "path": file_path}
                )
                if func_result:
                    patterns["function_count"] = (
                        len(func_result.split("\n")) - 1
                    )  # Subtract empty line

                # Count class definitions
                class_result = await grep_tool.ainvoke(
                    {"pattern": r"class\s+\w+", "path": file_path}
                )
                if class_result:
                    patterns["class_count"] = len(class_result.split("\n")) - 1

        except Exception as e:
            logger.error(f"Error analyzing patterns in {file_path}: {e}")

        return patterns

    async def _generate_suggestions(
        self, content: str, file_path: str, review_type: str
    ) -> list[dict[str, Any]]:
        """Generate suggestions based on review type."""
        suggestions = []

        if review_type == "security":
            suggestions = await self._generate_security_suggestions(content, file_path)
        elif review_type == "performance":
            suggestions = await self._generate_performance_suggestions(
                content, file_path
            )
        elif review_type == "readability":
            suggestions = await self._generate_readability_suggestions(
                content, file_path
            )
        elif review_type == "best-practices":
            suggestions = await self._generate_best_practice_suggestions(
                content, file_path
            )

        return suggestions

    async def _generate_security_suggestions(
        self, content: str, file_path: str
    ) -> list[dict[str, Any]]:
        """Generate security-focused suggestions."""
        suggestions = []

        # Check for hardcoded secrets
        if "password" in content.lower() or "secret" in content.lower():
            suggestions.append(
                {
                    "type": "security",
                    "severity": "high",
                    "message": "Potential hardcoded secret detected. Consider using environment variables.",
                    "suggestion": "Move sensitive data to environment variables or secure configuration.",
                }
            )

        # Check for SQL injection patterns
        if "execute(" in content and "SELECT" in content:
            suggestions.append(
                {
                    "type": "security",
                    "severity": "high",
                    "message": "Potential SQL injection vulnerability detected.",
                    "suggestion": "Use parameterized queries or ORM instead of raw SQL.",
                }
            )

        return suggestions

    async def _generate_performance_suggestions(
        self, content: str, file_path: str
    ) -> list[dict[str, Any]]:
        """Generate performance-focused suggestions."""
        suggestions = []

        # Check for inefficient loops
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "for " in line and "in range(" in line:
                # Look for nested loops
                for j in range(i + 1, min(i + 10, len(lines))):
                    if "for " in lines[j]:
                        suggestions.append(
                            {
                                "type": "performance",
                                "severity": "medium",
                                "message": f"Nested loop detected at line {i + 1}",
                                "suggestion": "Consider optimizing nested loops or using list comprehensions.",
                            }
                        )
                        break

        return suggestions

    async def _generate_readability_suggestions(
        self, content: str, file_path: str
    ) -> list[dict[str, Any]]:
        """Generate readability-focused suggestions."""
        suggestions = []

        # Check for long lines
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if len(line) > 80:
                suggestions.append(
                    {
                        "type": "readability",
                        "severity": "low",
                        "message": f"Line {i + 1} is too long ({len(line)} characters)",
                        "suggestion": "Break long lines into multiple lines for better readability.",
                    }
                )

        # Check for missing docstrings
        if "def " in content and '"""' not in content and "'''" not in content:
            suggestions.append(
                {
                    "type": "readability",
                    "severity": "medium",
                    "message": "Functions may benefit from docstrings",
                    "suggestion": "Add docstrings to document function purpose, parameters, and return values.",
                }
            )

        return suggestions

    async def _generate_best_practice_suggestions(
        self, content: str, file_path: str
    ) -> list[dict[str, Any]]:
        """Generate best practice suggestions."""
        suggestions = []

        # Check for TODO comments
        if "TODO" in content:
            suggestions.append(
                {
                    "type": "best-practices",
                    "severity": "low",
                    "message": "TODO comments found in code",
                    "suggestion": "Address TODO items or convert them to GitHub issues for tracking.",
                }
            )

        # Check for import organization
        lines = content.split("\n")
        import_lines = [
            i for i, line in enumerate(lines) if line.strip().startswith("import")
        ]
        if import_lines and len(import_lines) > 1:
            # Check if imports are grouped
            first_non_import = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if i > import_lines[0]
                    and not line.strip().startswith(("import", "#"))
                ),
                len(lines),
            )
            if (
                first_non_import > import_lines[-1] + 2
            ):  # More than one blank line between imports and code
                suggestions.append(
                    {
                        "type": "best-practices",
                        "severity": "low",
                        "message": "Imports should be grouped together",
                        "suggestion": "Organize imports at the top of the file with appropriate spacing.",
                    }
                )

        return suggestions

    def _calculate_score(self, review_results: dict[str, Any]) -> int:
        """Calculate an overall code quality score (0-100)."""
        score = 100

        # Deduct points for issues
        for issue in review_results.get("issues", []):
            if issue.get("severity") == "high":
                score -= 10
            elif issue.get("severity") == "medium":
                score -= 5
            elif issue.get("severity") == "low":
                score -= 2

        # Deduct points for suggestions
        for suggestion in review_results.get("suggestions", []):
            if suggestion.get("severity") == "high":
                score -= 5
            elif suggestion.get("severity") == "medium":
                score -= 3
            elif suggestion.get("severity") == "low":
                score -= 1

        # Ensure score is within bounds
        return max(0, min(100, score))

    async def generate_report(self, review_results: list[dict[str, Any]]) -> str:
        """Generate a human-readable report from review results."""
        if not review_results:
            return "No files to review."

        report = ["# Code Review Report\n"]
        report.append(f"Reviewed {len(review_results)} files\n")

        total_score = 0
        total_issues = 0
        total_suggestions = 0

        for result in review_results:
            file_path = result.get("file_path", "unknown")
            score = result.get("overall_score", 0)
            issues = result.get("issues", [])
            suggestions = result.get("suggestions", [])

            total_score += score
            total_issues += len(issues)
            total_suggestions += len(suggestions)

            report.append(f"\n## {file_path}")
            report.append(f"**Quality Score: {score}/100**")

            if issues:
                report.append("\n### Issues Found:")
                for issue in issues:
                    severity_icon = (
                        "🔴"
                        if issue.get("severity") == "high"
                        else "🟡"
                        if issue.get("severity") == "medium"
                        else "🟢"
                    )
                    report.append(
                        f"- {severity_icon} {issue.get('message', 'No message')}"
                    )

            if suggestions:
                report.append("\n### Suggestions:")
                for suggestion in suggestions:
                    severity_icon = (
                        "🔴"
                        if suggestion.get("severity") == "high"
                        else "🟡"
                        if suggestion.get("severity") == "medium"
                        else "🟢"
                    )
                    report.append(
                        f"- {severity_icon} {suggestion.get('message', 'No message')}"
                    )

        # Summary
        avg_score = total_score // len(review_results) if review_results else 0
        report.append("\n## Summary")
        report.append(f"- **Files Reviewed:** {len(review_results)}")
        report.append(f"- **Average Quality Score:** {avg_score}/100")
        report.append(f"- **Total Issues:** {total_issues}")
        report.append(f"- **Total Suggestions:** {total_suggestions}")

        if avg_score >= 80:
            report.append("\n🎉 **Great job!** Your code quality is excellent.")
        elif avg_score >= 60:
            report.append(
                "\n✅ **Good work!** Your code quality is acceptable with room for improvement."
            )
        else:
            report.append(
                "\n⚠️ **Needs attention.** Consider addressing the issues and suggestions to improve code quality."
            )

        return "\n".join(report)


# Global instance
_code_review_skill = None


def get_code_review_skill() -> CodeReviewSkill:
    """Get the global code review skill instance."""
    global _code_review_skill
    if _code_review_skill is None:
        _code_review_skill = CodeReviewSkill()
    return _code_review_skill
