"""Per-language refactor-recipes for B-30 lsp_code_action functionality.

This module provides language-specific mappings between LSP code actions and
refactor actions defined in skill bundles. It enhances the lsp_code_action tool
to return language-aware refactoring suggestions.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RefactorRecipe:
    """A recipe for mapping LSP code actions to refactor actions."""

    def __init__(
        self,
        lsp_action_patterns: list[str],
        refactor_action: str,
        description: str = "",
        priority: int = 0,
        conditions: dict[str, Any] | None = None,
    ):
        """Initialize a refactor recipe.

        Args:
            lsp_action_patterns: List of LSP action title patterns to match
            refactor_action: The refactor action to map to
            description: Human-readable description of the recipe
            priority: Priority for recipe matching (higher = more specific)
            conditions: Additional conditions for applying the recipe
        """
        self.lsp_action_patterns = lsp_action_patterns
        self.refactor_action = refactor_action
        self.description = description
        self.priority = priority
        self.conditions = conditions or {}

    def matches(self, lsp_action: dict[str, Any]) -> bool:
        """Check if this recipe matches an LSP action.

        Args:
            lsp_action: LSP action to check

        Returns:
            True if recipe matches, False otherwise
        """
        title = lsp_action.get("title", "").lower()

        # Check title patterns
        for pattern in self.lsp_action_patterns:
            if pattern.lower() in title:
                # Check additional conditions if specified
                if self.conditions:
                    for key, value in self.conditions.items():
                        if key == "kind" and lsp_action.get(key) != value:
                            return False
                        elif key == "file_extensions" and "document" in lsp_action:
                            # Check if file extension matches
                            doc_uri = lsp_action.get("document", {}).get("uri", "")
                            if not any(ext in doc_uri for ext in value):
                                return False
                return True

        return False


class LanguageRefactorRecipes:
    """Per-language refactor recipes for B-30."""

    def __init__(self, language: str):
        """Initialize recipes for a specific language.

        Args:
            language: Language identifier (java, rust, go, javascript, frontend)
        """
        self.language = language
        self.recipes: list[RefactorRecipe] = []
        self._load_recipes()

    def _load_recipes(self) -> None:
        """Load language-specific refactor recipes."""
        if self.language == "java":
            self._load_java_recipes()
        elif self.language == "rust":
            self._load_rust_recipes()
        elif self.language == "go":
            self._load_go_recipes()
        elif self.language == "javascript":
            self._load_javascript_recipes()
        elif self.language == "frontend":
            self._load_frontend_recipes()
        else:
            logger.warning(f"No refactor recipes defined for language: {self.language}")

    def _load_java_recipes(self) -> None:
        """Load Java-specific refactor recipes."""
        self.recipes = [
            RefactorRecipe(
                lsp_action_patterns=["Extract Method"],
                refactor_action="extract_method",
                description="Extract selected code into a new method",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Convert to Record"],
                refactor_action="convert_to_record",
                description="Convert class to Java record",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Generate hashCode() and equals()"],
                refactor_action="generate_hashCode_equals",
                description="Generate hashCode and equals methods",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Add unimplemented methods"],
                refactor_action="add_missing_interface_methods",
                description="Add missing interface methods to class",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Organize Imports"],
                refactor_action="organize_imports",
                description="Organize import statements",
                priority=5,
                conditions={"kind": "source.organizeImports"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Fix this"],
                refactor_action="fix_quickfix",
                description="Apply quick fix suggestions",
                priority=1,
                conditions={"kind": "quickfix"},
            ),
        ]

    def _load_rust_recipes(self) -> None:
        """Load Rust-specific refactor recipes."""
        self.recipes = [
            RefactorRecipe(
                lsp_action_patterns=["Extract to function"],
                refactor_action="extract_function",
                description="Extract selected code into a new function",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Convert to async function"],
                refactor_action="convert_to_async",
                description="Convert function to async",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Generate impl block"],
                refactor_action="generate_impl_block",
                description="Generate implementation block for trait",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Fix"],
                refactor_action="fix_clippy_lint",
                description="Fix Clippy lint suggestions",
                priority=5,
                conditions={"kind": "quickfix"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Format"],
                refactor_action="format_code",
                description="Format code using rustfmt",
                priority=1,
                conditions={"kind": "source"},
            ),
        ]

    def _load_go_recipes(self) -> None:
        """Load Go-specific refactor recipes."""
        self.recipes = [
            RefactorRecipe(
                lsp_action_patterns=["Extract to function"],
                refactor_action="extract_function",
                description="Extract selected code into a new function",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Extract to method"],
                refactor_action="extract_function",
                description="Extract selected code into a new method",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Implement interface"],
                refactor_action="implement_missing_methods",
                description="Implement missing interface methods",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Convert to interface"],
                refactor_action="convert_to_interface",
                description="Convert struct to interface",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Fix struct tag"],
                refactor_action="fix_struct_tag",
                description="Fix struct field tags",
                priority=5,
                conditions={"kind": "quickfix"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Format"],
                refactor_action="format_code",
                description="Format code using gofmt",
                priority=1,
                conditions={"kind": "source"},
            ),
        ]

    def _load_javascript_recipes(self) -> None:
        """Load JavaScript-specific refactor recipes."""
        self.recipes = [
            RefactorRecipe(
                lsp_action_patterns=["Extract to function"],
                refactor_action="extract_to_function",
                description="Extract selected code into a new function",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Convert to arrow function"],
                refactor_action="convert_to_arrow_function",
                description="Convert function to arrow function",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Add return type"],
                refactor_action="add_missing_return_type",
                description="Add missing return type annotation",
                priority=5,
                conditions={"kind": "quickfix"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Fix"],
                refactor_action="fix_eslint_rule",
                description="Fix ESLint rule violations",
                priority=5,
                conditions={"kind": "quickfix"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Organize Imports"],
                refactor_action="organize_imports",
                description="Organize import statements",
                priority=1,
                conditions={"kind": "source.organizeImports"},
            ),
        ]

    def _load_frontend_recipes(self) -> None:
        """Load Frontend-specific refactor recipes."""
        self.recipes = [
            RefactorRecipe(
                lsp_action_patterns=["Extract to component"],
                refactor_action="extract_to_component",
                description="Extract selected code into a new React component",
                priority=10,
                conditions={"kind": "refactor", "file_extensions": [".tsx", ".jsx"]},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Extract to function"],
                refactor_action="extract_to_function",
                description="Extract selected code into a new function",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Convert to arrow function"],
                refactor_action="convert_to_arrow_function",
                description="Convert function to arrow function",
                priority=10,
                conditions={"kind": "refactor"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Add return type"],
                refactor_action="add_missing_return_type",
                description="Add missing return type annotation",
                priority=5,
                conditions={"kind": "quickfix"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Fix"],
                refactor_action="fix_eslint_rule",
                description="Fix ESLint rule violations",
                priority=5,
                conditions={"kind": "quickfix"},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Fix accessibility issue"],
                refactor_action="fix_a11y_violation",
                description="Fix accessibility violations",
                priority=8,
                conditions={"kind": "quickfix", "file_extensions": [".tsx", ".jsx"]},
            ),
            RefactorRecipe(
                lsp_action_patterns=["Organize Imports"],
                refactor_action="organize_imports",
                description="Organize import statements",
                priority=1,
                conditions={"kind": "source.organizeImports"},
            ),
        ]

    def map_lsp_actions(
        self, lsp_actions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Map LSP code actions to refactor actions.

        Args:
            lsp_actions: List of LSP code actions

        Returns:
            List of mapped refactor actions with metadata
        """
        mapped_actions = []

        # Sort recipes by priority (highest first)
        sorted_recipes = sorted(self.recipes, key=lambda r: r.priority, reverse=True)

        for lsp_action in lsp_actions:
            for recipe in sorted_recipes:
                if recipe.matches(lsp_action):
                    mapped_action = {
                        "refactor_action": recipe.refactor_action,
                        "title": lsp_action.get("title", recipe.refactor_action),
                        "description": recipe.description,
                        "lsp_action": lsp_action,
                        "language": self.language,
                        "priority": recipe.priority,
                    }
                    mapped_actions.append(mapped_action)
                    break  # Use the first matching recipe

        return mapped_actions

    def get_available_refactor_actions(self) -> list[str]:
        """Get list of available refactor actions for this language.

        Returns:
            List of refactor action names
        """
        return list({recipe.refactor_action for recipe in self.recipes})


# Global cache for language refactor recipes
_refactor_recipes_cache: dict[str, LanguageRefactorRecipes] = {}


def get_refactor_recipes_for_language(language: str) -> LanguageRefactorRecipes:
    """Get refactor recipes for a specific language.

    Args:
        language: Language identifier

    Returns:
        LanguageRefactorRecipes instance
    """
    if language not in _refactor_recipes_cache:
        _refactor_recipes_cache[language] = LanguageRefactorRecipes(language)

    return _refactor_recipes_cache[language]


def clear_refactor_recipes_cache() -> None:
    """Clear the refactor recipes cache."""
    global _refactor_recipes_cache
    _refactor_recipes_cache.clear()
