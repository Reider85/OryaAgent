"""BranchManager: merge branches (B-10) - merge tool-call sequences.

Provides functionality to merge branches back into the parent session,
combining tool-call sequences and preserving the best of both branches.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.branch_manager import BranchManager
from app.core.db import asyncpg
from app.core.memory.md_store import get_md_store
from app.core.observability.spans import emit_span
from app.core.session import SessionManager

logger = logging.getLogger(__name__)


class BranchMerger:
    """Manager for merging branches back into parent sessions."""

    def __init__(self):
        self.branch_manager = BranchManager()
        self.session_manager = SessionManager()
        self.md_store = get_md_store()

    @emit_span(name="branch.merge", attributes={"operation": "merge_branches"})
    async def merge_branches(
        self,
        parent_session_id: str,
        branch_session_id: str,
        merge_strategy: str = "auto",
        conflict_resolution: str = "parent_wins",
    ) -> Dict[str, Any]:
        """Merge a branch back into the parent session.

        Args:
            parent_session_id: ID of the parent session
            branch_session_id: ID of the branch to merge
            merge_strategy: How to merge turns ("auto", "manual", "preserve_branch")
            conflict_resolution: How to handle conflicts ("parent_wins", "branch_wins", "manual")

        Returns:
            Merge result with statistics and conflicts
        """
        try:
            # Validate inputs
            parent_session = await self.session_manager.get_session(parent_session_id)
            if not parent_session:
                raise ValueError(f"Parent session not found: {parent_session_id}")

            branch_session = await self.session_manager.get_session(branch_session_id)
            if not branch_session:
                raise ValueError(f"Branch session not found: {branch_session_id}")

            if branch_session["parent_session_id"] != parent_session_id:
                raise ValueError(
                    f"Branch {branch_session_id} is not a child of {parent_session_id}"
                )

            # Get turns from both sessions
            parent_turns = await self.session_manager.get_session_turns(
                parent_session_id
            )
            branch_turns = await self.session_manager.get_session_turns(
                branch_session_id
            )

            # Find the fork point
            fork_point = await self._find_fork_point(parent_turns, branch_turns)
            if not fork_point:
                raise ValueError("Could not find fork point between sessions")

            # Analyze differences
            differences = await self._analyze_differences(
                parent_turns, branch_turns, fork_point["parent_turn_id"]
            )

            # Apply merge strategy
            if merge_strategy == "auto":
                merge_result = await self._auto_merge(
                    parent_session_id,
                    branch_session_id,
                    fork_point,
                    differences,
                    conflict_resolution,
                )
            elif merge_strategy == "preserve_branch":
                merge_result = await self._preserve_branch_merge(
                    parent_session_id,
                    branch_session_id,
                    fork_point,
                    differences,
                )
            else:
                raise ValueError(f"Unsupported merge strategy: {merge_strategy}")

            # Merge memory files
            await self._merge_memory_files(parent_session_id, branch_session_id)

            # Update metadata
            await self._update_merge_metadata(
                parent_session_id, branch_session_id, merge_result
            )

            logger.info(
                f"Merged branch {branch_session_id} into parent {parent_session_id}"
            )
            return merge_result

        except Exception as e:
            logger.error(f"Failed to merge branches: {e}")
            raise ValueError(f"Failed to merge branches: {str(e)}")

    async def _find_fork_point(
        self, parent_turns: List[Dict], branch_turns: List[Dict]
    ) -> Optional[Dict[str, Any]]:
        """Find the fork point between parent and branch turns."""
        try:
            # Get the parent turn ID from branch metadata
            if branch_turns:
                branch_metadata = branch_turns[0].get("metadata", {})
                parent_turn_id = branch_metadata.get("original_turn_id")
                if parent_turn_id:
                    return {
                        "parent_turn_id": parent_turn_id,
                        "parent_turn_number": next(
                            (
                                t["turn_number"]
                                for t in parent_turns
                                if t["id"] == parent_turn_id
                            ),
                            None,
                        ),
                    }
            return None

        except Exception as e:
            logger.error(f"Failed to find fork point: {e}")
            return None

    async def _analyze_differences(
        self,
        parent_turns: List[Dict],
        branch_turns: List[Dict],
        fork_point: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyze differences between parent and branch after fork point."""
        try:
            parent_fork_index = next(
                (
                    i
                    for i, t in enumerate(parent_turns)
                    if t["id"] == fork_point["parent_turn_id"]
                ),
                len(parent_turns),
            )

            branch_fork_index = 0  # Branch starts from fork point

            parent_new_turns = parent_turns[parent_fork_index:]
            branch_new_turns = branch_turns[branch_fork_index:]

            differences = {
                "parent_new_turns": len(parent_new_turns),
                "branch_new_turns": len(branch_new_turns),
                "conflicts": [],
                "unique_parent": [],
                "unique_branch": [],
            }

            # Analyze each turn
            for i, (parent_turn, branch_turn) in enumerate(
                zip(parent_new_turns, branch_new_turns)
            ):
                if parent_turn["messages"] != branch_turn["messages"]:
                    differences["conflicts"].append(
                        {
                            "turn_number": parent_turn["turn_number"],
                            "parent_messages": parent_turn["messages"],
                            "branch_messages": branch_turn["messages"],
                        }
                    )

            # Find unique turns
            if len(parent_new_turns) > len(branch_new_turns):
                differences["unique_parent"] = parent_new_turns[len(branch_new_turns) :]
            elif len(branch_new_turns) > len(parent_new_turns):
                differences["unique_branch"] = branch_new_turns[len(parent_new_turns) :]

            return differences

        except Exception as e:
            logger.error(f"Failed to analyze differences: {e}")
            return {"conflicts": [], "unique_parent": [], "unique_branch": []}

    async def _auto_merge(
        self,
        parent_session_id: str,
        branch_session_id: str,
        fork_point: Dict[str, Any],
        differences: Dict[str, Any],
        conflict_resolution: str,
    ) -> Dict[str, Any]:
        """Perform automatic merge of branches."""
        try:
            merge_result = {
                "strategy": "auto",
                "conflicts": differences["conflicts"],
                "merged_turns": 0,
                "skipped_turns": 0,
                "conflicts_resolved": 0,
            }

            # Get all branch turns after fork point
            branch_turns = await self.session_manager.get_session_turns(
                branch_session_id
            )
            branch_fork_index = 0

            # Merge turns
            for branch_turn in branch_turns[branch_fork_index:]:
                # Check for conflicts
                has_conflict = any(
                    c["turn_number"] == branch_turn["turn_number"]
                    for c in differences["conflicts"]
                )

                if has_conflict:
                    # Apply conflict resolution
                    if conflict_resolution == "parent_wins":
                        merge_result["skipped_turns"] += 1
                        continue
                    elif conflict_resolution == "branch_wins":
                        await self._add_turn_to_session(parent_session_id, branch_turn)
                        merge_result["merged_turns"] += 1
                        merge_result["conflicts_resolved"] += 1
                    else:
                        # Manual resolution - keep both for now
                        await self._add_turn_to_session(parent_session_id, branch_turn)
                        merge_result["merged_turns"] += 1
                        merge_result["conflicts_resolved"] += 1
                else:
                    # No conflict, merge the turn
                    await self._add_turn_to_session(parent_session_id, branch_turn)
                    merge_result["merged_turns"] += 1

            return merge_result

        except Exception as e:
            logger.error(f"Failed to auto merge: {e}")
            raise ValueError(f"Failed to auto merge: {str(e)}")

    async def _preserve_branch_merge(
        self,
        parent_session_id: str,
        branch_session_id: str,
        fork_point: Dict[str, Any],
        differences: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Preserve branch turns and append to parent."""
        try:
            merge_result = {
                "strategy": "preserve_branch",
                "conflicts": differences["conflicts"],
                "merged_turns": 0,
                "skipped_turns": 0,
                "conflicts_resolved": 0,
            }

            # Get all branch turns
            branch_turns = await self.session_manager.get_session_turns(
                branch_session_id
            )

            # Append branch turns to parent
            for branch_turn in branch_turns:
                # Create new turn with adjusted turn number
                new_turn = {
                    "id": str(uuid.uuid4()),
                    "session_id": parent_session_id,
                    "turn_number": branch_turn["turn_number"],
                    "messages": branch_turn["messages"],
                    "tool_calls": branch_turn["tool_calls"],
                    "created_at": datetime.utcnow(),
                    "metadata": {
                        "merged_from": branch_session_id,
                        "original_turn_id": branch_turn["id"],
                        "merge_type": "preserve_branch",
                    },
                }
                await self.session_manager.create_turn(new_turn)
                merge_result["merged_turns"] += 1

            return merge_result

        except Exception as e:
            logger.error(f"Failed to preserve branch merge: {e}")
            raise ValueError(f"Failed to preserve branch merge: {str(e)}")

    async def _add_turn_to_session(self, session_id: str, turn: Dict[str, Any]) -> None:
        """Add a turn to a session."""
        try:
            new_turn = {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "turn_number": turn["turn_number"],
                "messages": turn["messages"],
                "tool_calls": turn["tool_calls"],
                "created_at": datetime.utcnow(),
                "metadata": {
                    "merged_from": turn["session_id"],
                    "original_turn_id": turn["id"],
                },
            }
            await self.session_manager.create_turn(new_turn)

        except Exception as e:
            logger.error(f"Failed to add turn to session: {e}")
            raise ValueError(f"Failed to add turn to session: {str(e)}")

    async def _merge_memory_files(
        self, parent_session_id: str, branch_session_id: str
    ) -> None:
        """Merge memory files from branch to parent."""
        try:
            parent_memory_dir = self.md_store.get_session_memory_dir(parent_session_id)
            branch_memory_dir = self.md_store.get_session_memory_dir(branch_session_id)

            if not branch_memory_dir.exists():
                return

            # Create parent memory directory if it doesn't exist
            parent_memory_dir.mkdir(parents=True, exist_ok=True)

            # Merge memory files
            memory_files = [
                "PROJECT.md",
                "LEARNED.md",
                "PREFERENCES.md",
                "FACTS.md",
                "DECISIONS.md",
            ]

            for file_name in memory_files:
                source_file = branch_memory_dir / file_name
                if source_file.exists():
                    destination_file = parent_memory_dir / file_name

                    # Append branch content to parent (with separator)
                    parent_content = (
                        destination_file.read_text(encoding="utf-8")
                        if destination_file.exists()
                        else ""
                    )
                    branch_content = source_file.read_text(encoding="utf-8")

                    merged_content = (
                        parent_content + f"\n\n--- Branch Content ---\n{branch_content}"
                    )
                    destination_file.write_text(merged_content, encoding="utf-8")

        except Exception as e:
            logger.error(f"Failed to merge memory files: {e}")
            raise ValueError(f"Failed to merge memory files: {str(e)}")

    async def _update_merge_metadata(
        self,
        parent_session_id: str,
        branch_session_id: str,
        merge_result: Dict[str, Any],
    ) -> None:
        """Update metadata after merge."""
        try:
            # Update parent session metadata
            update_query = """
                UPDATE sessions
                SET metadata = jsonb_set(metadata, '{last_merged}', $1),
                    updated_at = $2
                WHERE id = $3
            """
            async with asyncpg.get_pool().acquire() as conn:
                await conn.execute(
                    update_query,
                    {
                        "branch_id": branch_session_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "result": merge_result,
                    },
                    datetime.utcnow(),
                    parent_session_id,
                )

        except Exception as e:
            logger.error(f"Failed to update merge metadata: {e}")
            # Don't raise this as it's not critical

    async def list_merge_history(self, session_id: str) -> List[Dict[str, Any]]:
        """List merge history for a session."""
        try:
            query = """
                SELECT metadata
                FROM sessions
                WHERE id = $1
                AND metadata ? 'last_merged'
                ORDER BY updated_at DESC
            """
            async with asyncpg.get_pool().acquire() as conn:
                records = await conn.fetch(query, session_id)

            return [record["metadata"] for record in records]

        except Exception as e:
            logger.error(f"Failed to list merge history: {e}")
            return []


# Global instance
_branch_merger = None


def get_branch_merger() -> BranchMerger:
    """Get the global branch merger instance."""
    global _branch_merger
    if _branch_merger is None:
        _branch_merger = BranchMerger()
    return _branch_merger
