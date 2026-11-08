#!/usr/bin/env python3
"""Test script for B-18 to B-21 components.

This script tests the new UI components and SQLiteStore functionality.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.sqlite_store import get_sqlite_store
from app.core.skills import get_skill_registry
from app.core.hooks_audit import get_hook_executions, get_hook_statistics


async def test_sqlite_store():
    """Test SQLiteStore functionality."""
    print("Testing SQLiteStore...")

    store = get_sqlite_store()

    # Test adding a hook execution
    hook_execution = {
        "id": "test_hook_001",
        "session_id": "test_session_001",
        "tool_name": "write",
        "hook_name": "auto_format",
        "hook_type": "post",
        "success": True,
        "message": "Auto-format completed successfully",
        "duration_ms": 150.5,
        "timestamp": "2024-01-01T12:00:00Z",
        "metadata": {"test": True},
    }

    await store.add_hook_execution(hook_execution)
    print("✓ Hook execution added")

    # Test retrieving hook executions
    executions = await store.get_hook_executions()
    print(f"✓ Retrieved {len(executions)} hook executions")

    # Test adding skill metadata
    skill_data = {
        "name": "test_skill",
        "description": "Test skill for SQLiteStore",
        "version": "1.0.0",
        "author": "Test Author",
        "category": "test",
        "tags": ["test", "example"],
        "tools": ["read", "write"],
        "hooks": ["pre_hook", "post_hook"],
        "dependencies": [],
        "metadata": {"test": True},
        "is_active": True,
        "activated_at": "2024-01-01T12:00:00Z",
        "validation_status": "valid",
    }

    await store.add_skill_metadata(skill_data)
    print("✓ Skill metadata added")

    # Test retrieving skills metadata
    skills = await store.get_skills_metadata()
    print(f"✓ Retrieved {len(skills)} skills")

    # Test statistics
    stats = await store.get_hooks_statistics(7)
    print(f"✓ Hook statistics: {stats['total_executions']} executions")

    skill_stats = await store.get_skills_statistics()
    print(f"✓ Skill statistics: {skill_stats['total_skills']} skills")

    print("SQLiteStore tests passed!\n")


async def test_skills_ui():
    """Test Skills UI functionality."""
    print("Testing Skills UI...")

    from app.ui.skills_ui import get_skills_ui

    skills_ui = get_skills_ui()

    # Test listing skills
    skills_data = await skills_ui.list_skills()
    print(f"✓ Listed {len(skills_data.get('skills', []))} skills")

    # Test getting skill categories
    categories = skills_data.get("categories", [])
    print(f"✓ Found categories: {categories}")

    # Test getting skill tags
    tags = skills_data.get("tags", [])
    print(f"✓ Found tags: {tags}")

    # Test getting skill statistics
    stats = await skills_ui.get_skill_statistics()
    print(f"✓ Skill statistics: {stats['total_skills']} total skills")

    print("Skills UI tests passed!\n")


async def test_hooks_ui():
    """Test Hooks UI functionality."""
    print("Testing Hooks UI...")

    from app.ui.hooks_ui import get_hooks_ui

    hooks_ui = get_hooks_ui()

    # Test getting hook registry info
    registry_info = await hooks_ui.get_hook_registry_info()
    print(
        f"✓ Hook registry info: {registry_info['total_pre_hooks']} pre hooks, {registry_info['total_post_hooks']} post hooks"
    )

    # Test getting hook statistics
    stats = await hooks_ui.get_hook_statistics(7)
    print(f"✓ Hook statistics: {stats['total_executions']} executions")

    print("Hooks UI tests passed!\n")


async def test_branch_manager_ui():
    """Test BranchManager UI functionality."""
    print("Testing BranchManager UI...")

    from app.ui.branch_manager_ui import get_branch_manager_ui

    branch_ui = get_branch_manager_ui()

    # Test getting branch statistics
    stats = await branch_ui.get_branch_statistics()
    print(f"✓ Branch statistics: {stats.get('total_branches', 0)} total branches")

    # Test getting merge strategies
    strategies = await branch_ui.get_merge_strategies()
    print(f"✓ Merge strategies: {len(strategies)} strategies available")

    print("BranchManager UI tests passed!\n")


async def main():
    """Run all tests."""
    print("Running B-18 to B-21 component tests...\n")

    try:
        await test_sqlite_store()
        await test_skills_ui()
        await test_hooks_ui()
        await test_branch_manager_ui()

        print("✅ All tests passed!")
        return 0

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
