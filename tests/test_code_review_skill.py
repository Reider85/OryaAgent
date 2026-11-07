"""Test suite for the code review skill."""

from unittest.mock import AsyncMock, patch

from app.skills.code_review_skill import CodeReviewSkill, get_code_review_skill


class TestCodeReviewSkill:
    """Test cases for the CodeReviewSkill class."""

    def setup_method(self):
        """Set up test environment."""
        self.skill = CodeReviewSkill()

    def test_skill_initialization(self):
        """Test skill initialization."""
        assert self.skill.skill.name == "code-review"
        assert "code-quality" in self.skill.skill.tags
        assert "review" in self.skill.skill.tags
        assert "static-analysis" in self.skill.skill.tags
        assert "linting" in self.skill.skill.tags

    @patch("app.skills.code_review_skill.get_tools")
    async def test_review_file_basic(self, mock_get_tools):
        """Test basic file review functionality."""
        # Mock read tool
        mock_read = AsyncMock()
        mock_read.name = "read"
        mock_read.ainvoke.return_value = (
            "# Test file content\ndef test_function():\n    pass\n"
        )

        mock_get_tools.return_value = [mock_read]

        result = await self.skill.review_file("test.py")

        assert result["file_path"] == "test.py"
        assert "file_size" in result
        assert "issues" in result
        assert "suggestions" in result
        assert "metrics" in result
        assert "overall_score" in result
        assert result["overall_score"] >= 0

    @patch("app.skills.code_review_skill.get_tools")
    async def test_review_file_with_diagnostics(self, mock_get_tools):
        """Test file review with LSP diagnostics."""
        # Mock read tool
        mock_read = AsyncMock()
        mock_read.name = "read"
        mock_read.ainvoke.return_value = (
            "# Test file content\ndef test_function():\n    pass\n"
        )

        # Mock diagnostics tool
        mock_diagnostics = AsyncMock()
        mock_diagnostics.name = "lsp_diagnostics"
        mock_diagnostics.ainvoke.return_value = [
            {"type": "error", "message": "Syntax error", "line": 1, "severity": "high"}
        ]

        mock_get_tools.return_value = [mock_read, mock_diagnostics]

        result = await self.skill.review_file("test.py")

        assert len(result["issues"]) > 0
        assert any(issue["type"] == "error" for issue in result["issues"])

    @patch("app.skills.code_review_skill.get_tools")
    async def test_review_file_security_suggestions(self, mock_get_tools):
        """Test security-focused review."""
        # Mock read tool with content that should trigger security suggestions
        mock_read = AsyncMock()
        mock_read.name = "read"
        mock_read.ainvoke.return_value = (
            "password = 'secret123'\nexecute('SELECT * FROM users')\n"
        )

        mock_get_tools.return_value = [mock_read]

        result = await self.skill.review_file("test.py", review_types=["security"])

        security_suggestions = [
            s for s in result["suggestions"] if s["type"] == "security"
        ]
        assert (
            len(security_suggestions) >= 2
        )  # Should detect password and SQL injection

    @patch("app.skills.code_review_skill.get_tools")
    async def test_review_file_performance_suggestions(self, mock_get_tools):
        """Test performance-focused review."""
        # Mock read tool with nested loops
        mock_read = AsyncMock()
        mock_read.name = "read"
        mock_read.ainvoke.return_value = """
for i in range(100):
    for j in range(100):
        pass
"""

        mock_get_tools.return_value = [mock_read]

        result = await self.skill.review_file("test.py", review_types=["performance"])

        performance_suggestions = [
            s for s in result["suggestions"] if s["type"] == "performance"
        ]
        assert len(performance_suggestions) > 0

    @patch("app.skills.code_review_skill.get_tools")
    async def test_review_file_readability_suggestions(self, mock_get_tools):
        """Test readability-focused review."""
        # Mock read tool with long lines and missing docstrings
        mock_read = AsyncMock()
        mock_read.name = "read"
        mock_read.ainvoke.return_value = """
def very_long_function_name_that_exceeds_eighty_characters_but_is_still_valid():
    pass
"""

        mock_get_tools.return_value = [mock_read]

        result = await self.skill.review_file("test.py", review_types=["readability"])

        readability_suggestions = [
            s for s in result["suggestions"] if s["type"] == "readability"
        ]
        assert len(readability_suggestions) > 0

    @patch("app.skills.code_review_skill.get_tools")
    async def test_review_file_best_practice_suggestions(self, mock_get_tools):
        """Test best practice-focused review."""
        # Mock read tool with TODO comments and poor import organization
        mock_read = AsyncMock()
        mock_read.name = "read"
        mock_read.ainvoke.return_value = """
import os
import sys

# TODO: Refactor this function
def test_function():
    pass

import json
"""

        mock_get_tools.return_value = [mock_read]

        result = await self.skill.review_file(
            "test.py", review_types=["best-practices"]
        )

        best_practice_suggestions = [
            s for s in result["suggestions"] if s["type"] == "best-practices"
        ]
        assert len(best_practice_suggestions) > 0

    def test_calculate_score(self):
        """Test score calculation."""
        # Test perfect score
        result = {"issues": [], "suggestions": []}
        score = self.skill._calculate_score(result)
        assert score == 100

        # Test with high severity issues
        result = {
            "issues": [{"severity": "high"}, {"severity": "high"}],
            "suggestions": [],
        }
        score = self.skill._calculate_score(result)
        assert score == 80  # 100 - 20 (2 * 10 points)

        # Test with medium severity issues
        result = {
            "issues": [{"severity": "medium"}, {"severity": "medium"}],
            "suggestions": [],
        }
        score = self.skill._calculate_score(result)
        assert score == 90  # 100 - 10 (2 * 5 points)

        # Test with low severity issues
        result = {
            "issues": [{"severity": "low"}, {"severity": "low"}],
            "suggestions": [],
        }
        score = self.skill._calculate_score(result)
        assert score == 96  # 100 - 4 (2 * 2 points)

        # Test score bounds
        result = {
            "issues": [{"severity": "high"} for _ in range(20)],  # 200 points deduction
            "suggestions": [],
        }
        score = self.skill._calculate_score(result)
        assert score == 0  # Cannot go below 0

    async def test_generate_report(self):
        """Test report generation."""
        review_results = [
            {
                "file_path": "test1.py",
                "overall_score": 85,
                "issues": [
                    {"severity": "medium", "message": "Medium severity issue"},
                    {"severity": "low", "message": "Low severity issue"},
                ],
                "suggestions": [
                    {"severity": "low", "message": "Improvement suggestion"}
                ],
            },
            {
                "file_path": "test2.py",
                "overall_score": 60,
                "issues": [{"severity": "high", "message": "High severity issue"}],
                "suggestions": [
                    {"severity": "medium", "message": "Important suggestion"}
                ],
            },
        ]

        report = await self.skill.generate_report(review_results)

        assert "# Code Review Report" in report
        assert "test1.py" in report
        assert "test2.py" in report
        assert "Quality Score: 85/100" in report
        assert "Quality Score: 60/100" in report
        assert "Average Quality Score:** 72/100" in report
        assert "Total Issues:** 3" in report
        assert "Total Suggestions:** 2" in report

    def test_global_skill_instance(self):
        """Test global skill instance."""
        skill1 = get_code_review_skill()
        skill2 = get_code_review_skill()

        assert skill1 is skill2  # Should be the same instance

    @patch("app.skills.code_review_skill.get_tools")
    async def test_review_file_error_handling(self, mock_get_tools):
        """Test error handling in file review."""
        # Mock read tool that raises an exception
        mock_read = AsyncMock()
        mock_read.name = "read"
        mock_read.ainvoke.side_effect = Exception("File not found")

        mock_get_tools.return_value = [mock_read]

        result = await self.skill.review_file("nonexistent.py")

        assert "error" in result
        assert result["overall_score"] == 0  # Should handle errors gracefully
