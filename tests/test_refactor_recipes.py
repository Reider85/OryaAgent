"""Test refactor-recipes functionality for B-30 lsp_code_action integration."""

from app.core.lsp.refactor_recipes import (
    LanguageRefactorRecipes,
    RefactorRecipe,
    clear_refactor_recipes_cache,
    get_refactor_recipes_for_language,
)


class TestRefactorRecipe:
    """Test cases for RefactorRecipe class."""

    def test_recipe_matches_simple_pattern(self):
        """Test basic pattern matching."""
        recipe = RefactorRecipe(
            lsp_action_patterns=["Extract Method"],
            refactor_action="extract_method",
            description="Extract selected code into a new method",
        )

        lsp_action = {"title": "Extract Method", "kind": "refactor"}
        assert recipe.matches(lsp_action) is True

        lsp_action = {"title": "Something Else", "kind": "refactor"}
        assert recipe.matches(lsp_action) is False

    def test_recipe_matches_case_insensitive(self):
        """Test case-insensitive pattern matching."""
        recipe = RefactorRecipe(
            lsp_action_patterns=["extract method"], refactor_action="extract_method"
        )

        lsp_action = {"title": "Extract Method", "kind": "refactor"}
        assert recipe.matches(lsp_action) is True

        lsp_action = {"title": "EXTRACT METHOD", "kind": "refactor"}
        assert recipe.matches(lsp_action) is True

    def test_recipe_with_conditions(self):
        """Test recipe matching with conditions."""
        recipe = RefactorRecipe(
            lsp_action_patterns=["Fix"],
            refactor_action="fix_quickfix",
            conditions={"kind": "quickfix"},
        )

        lsp_action = {"title": "Fix this", "kind": "quickfix"}
        assert recipe.matches(lsp_action) is True

        lsp_action = {"title": "Fix this", "kind": "refactor"}
        assert recipe.matches(lsp_action) is False

    def test_recipe_with_file_extension_condition(self):
        """Test recipe matching with file extension conditions."""
        recipe = RefactorRecipe(
            lsp_action_patterns=["Fix accessibility"],
            refactor_action="fix_a11y_violation",
            conditions={"file_extensions": [".tsx", ".jsx"]},
        )

        lsp_action = {
            "title": "Fix accessibility issue",
            "kind": "quickfix",
            "document": {"uri": "file:///path/to/component.tsx"},
        }
        assert recipe.matches(lsp_action) is True

        lsp_action = {
            "title": "Fix accessibility issue",
            "kind": "quickfix",
            "document": {"uri": "file:///path/to/script.js"},
        }
        assert recipe.matches(lsp_action) is False

    def test_recipe_priority_ordering(self):
        """Test that higher priority recipes are preferred."""
        recipe1 = RefactorRecipe(
            lsp_action_patterns=["Fix"], refactor_action="fix_general", priority=1
        )

        recipe2 = RefactorRecipe(
            lsp_action_patterns=["Fix"], refactor_action="fix_specific", priority=10
        )

        # Both match the same LSP action, but recipe2 has higher priority
        lsp_action = {"title": "Fix this", "kind": "quickfix"}

        assert recipe1.matches(lsp_action) is True
        assert recipe2.matches(lsp_action) is True

        # When sorted by priority, recipe2 should come first
        recipes = [recipe1, recipe2]
        sorted_recipes = sorted(recipes, key=lambda r: r.priority, reverse=True)

        assert sorted_recipes[0] == recipe2
        assert sorted_recipes[1] == recipe1


class TestLanguageRefactorRecipes:
    """Test cases for LanguageRefactorRecipes class."""

    def test_java_recipes_loaded(self):
        """Test that Java recipes are properly loaded."""
        recipes = LanguageRefactorRecipes("java")

        assert len(recipes.recipes) > 0

        # Check for specific Java refactor actions
        refactor_actions = recipes.get_available_refactor_actions()
        assert "extract_method" in refactor_actions
        assert "convert_to_record" in refactor_actions
        assert "generate_hashCode_equals" in refactor_actions
        assert "add_missing_interface_methods" in refactor_actions

    def test_rust_recipes_loaded(self):
        """Test that Rust recipes are properly loaded."""
        recipes = LanguageRefactorRecipes("rust")

        assert len(recipes.recipes) > 0

        # Check for specific Rust refactor actions
        refactor_actions = recipes.get_available_refactor_actions()
        assert "extract_function" in refactor_actions
        assert "convert_to_async" in refactor_actions
        assert "generate_impl_block" in refactor_actions
        assert "fix_clippy_lint" in refactor_actions

    def test_go_recipes_loaded(self):
        """Test that Go recipes are properly loaded."""
        recipes = LanguageRefactorRecipes("go")

        assert len(recipes.recipes) > 0

        # Check for specific Go refactor actions
        refactor_actions = recipes.get_available_refactor_actions()
        assert "extract_function" in refactor_actions
        assert "convert_to_interface" in refactor_actions
        assert "implement_missing_methods" in refactor_actions
        assert "fix_struct_tag" in refactor_actions

    def test_javascript_recipes_loaded(self):
        """Test that JavaScript recipes are properly loaded."""
        recipes = LanguageRefactorRecipes("javascript")

        assert len(recipes.recipes) > 0

        # Check for specific JavaScript refactor actions
        refactor_actions = recipes.get_available_refactor_actions()
        assert "extract_to_function" in refactor_actions
        assert "convert_to_arrow_function" in refactor_actions
        assert "add_missing_return_type" in refactor_actions
        assert "fix_eslint_rule" in refactor_actions

    def test_frontend_recipes_loaded(self):
        """Test that Frontend recipes are properly loaded."""
        recipes = LanguageRefactorRecipes("frontend")

        assert len(recipes.recipes) > 0

        # Check for specific Frontend refactor actions
        refactor_actions = recipes.get_available_refactor_actions()
        assert "extract_to_component" in refactor_actions
        assert "extract_to_function" in refactor_actions
        assert "convert_to_arrow_function" in refactor_actions
        assert "fix_a11y_violation" in refactor_actions

    def test_unknown_language_recipes(self):
        """Test behavior with unknown language."""
        recipes = LanguageRefactorRecipes("unknown")

        # Should not crash but should have no recipes
        assert len(recipes.recipes) == 0

    def test_map_lsp_actions(self):
        """Test mapping LSP actions to refactor actions."""
        recipes = LanguageRefactorRecipes("java")

        lsp_actions = [
            {"title": "Extract Method", "kind": "refactor"},
            {"title": "Organize Imports", "kind": "source.organizeImports"},
            {"title": "Something Else", "kind": "refactor"},
        ]

        mapped_actions = recipes.map_lsp_actions(lsp_actions)

        # Should have 2 mapped actions (Extract Method and Organize Imports)
        assert len(mapped_actions) == 2

        # Check that the mapping is correct
        extract_action = next(
            (
                action
                for action in mapped_actions
                if action["refactor_action"] == "extract_method"
            ),
            None,
        )
        assert extract_action is not None
        assert extract_action["title"] == "Extract Method"
        assert extract_action["language"] == "java"

    def test_map_lsp_actions_priority(self):
        """Test that priority affects mapping when multiple recipes match."""
        recipes = LanguageRefactorRecipes("java")

        # Create an LSP action that could match multiple recipes
        lsp_actions = [{"title": "Fix this", "kind": "quickfix"}]

        mapped_actions = recipes.map_lsp_actions(lsp_actions)

        # Should have one mapped action
        assert len(mapped_actions) == 1

        # Should be the highest priority recipe that matches
        action = mapped_actions[0]
        assert action["refactor_action"] == "fix_quickfix"


class TestGlobalFunctions:
    """Test cases for global utility functions."""

    def test_get_refactor_recipes_for_language(self):
        """Test getting refactor recipes for a language."""
        # Clear cache first
        clear_refactor_recipes_cache()

        # Get recipes for Java
        recipes = get_refactor_recipes_for_language("java")

        assert isinstance(recipes, LanguageRefactorRecipes)
        assert recipes.language == "java"
        assert len(recipes.recipes) > 0

        # Should be cached
        recipes2 = get_refactor_recipes_for_language("java")
        assert recipes is recipes2

    def test_clear_refactor_recipes_cache(self):
        """Test clearing the refactor recipes cache."""
        # Get recipes to populate cache
        get_refactor_recipes_for_language("java")
        assert len(get_refactor_recipes_for_language("java").recipes) > 0

        # Clear cache
        clear_refactor_recipes_cache()

        # Now should create new instance
        recipes = get_refactor_recipes_for_language("java")
        assert len(recipes.recipes) > 0  # Still has recipes, just new instance

    def test_cache_behavior(self):
        """Test that caching works correctly."""
        clear_refactor_recipes_cache()

        # Get recipes twice - should return same instance
        recipes1 = get_refactor_recipes_for_language("rust")
        recipes2 = get_refactor_recipes_for_language("rust")

        assert recipes1 is recipes2

        # Clear cache and get again - should be different instance
        clear_refactor_recipes_cache()
        recipes3 = get_refactor_recipes_for_language("rust")

        assert recipes1 is not recipes3
        assert recipes3.language == "rust"
