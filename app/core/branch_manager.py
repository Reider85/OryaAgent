"""BranchManager: fork session (B-09) - create branch from any turn.

Provides functionality to create branches from any session turn,
enabling parallel development and experimentation.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.db import asyncpg
from app.core.memory.md_store import get_md_store
from app.core.observability.spans import emit_span
from app.core.session import SessionManager

logger = logging.getLogger(__name__)


class BranchManager:
    """Manager for session branches and forks."""

    def __init__(self):
        self.session_manager = SessionManager()
        self.md_store = get_md_store()

    @emit_span(name="branch.create", attributes={"operation": "fork_session"})
    async def fork_session(
        self,
        session_id: str,
        turn_id: Optional[str] = None,
        branch_name: Optional[str] = None,
        parent_turn_id: Optional[str] = None,
        bulk_copy: bool = True,
        progress_callback: Optional[callable] = None,
    ) -> str:
        """Create a new branch from any session turn.

        Args:
            session_id: ID of the parent session
            turn_id: Specific turn to fork from (defaults to latest)
            branch_name: Name for the new branch (auto-generated if None)
            parent_turn_id: ID of the parent turn (for reference)
            bulk_copy: Use bulk operations for better performance (default: True)
            progress_callback: Optional callback for progress updates

        Returns:
            ID of the new branch session
        """
        try:
            # Get the parent session
            parent_session = await self.session_manager.get_session(session_id)
            if not parent_session:
                raise ValueError(f"Parent session not found: {session_id}")

            # If turn_id is not specified, use the latest turn
            if not turn_id:
                turns = await self.session_manager.get_session_turns(session_id)
                if turns:
                    turn_id = turns[-1]["id"]
                else:
                    raise ValueError(f"No turns found in session: {session_id}")

            # Get the specific turn data
            turn_data = await self.session_manager.get_turn(session_id, turn_id)
            if not turn_data:
                raise ValueError(f"Turn not found: {turn_id}")

            # Generate branch name if not provided
            if not branch_name:
                branch_name = f"branch-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

            # Create new session for the branch
            branch_session_id = str(uuid.uuid4())
            branch_session = {
                "id": branch_session_id,
                "name": branch_name,
                "parent_session_id": session_id,
                "parent_turn_id": turn_id,
                "created_at": datetime.utcnow(),
                "status": "active",
                "metadata": {
                    "branch_name": branch_name,
                    "parent_session_id": session_id,
                    "parent_turn_id": turn_id,
                    "forked_at": datetime.utcnow().isoformat(),
                    "bulk_copy": bulk_copy,
                },
            }

            # Save the branch session
            await self.session_manager.create_session(branch_session)

            # Copy session state to the branch with performance optimizations
            await self._copy_session_state_optimized(
                session_id,
                branch_session_id,
                turn_id,
                bulk_copy=bulk_copy,
                progress_callback=progress_callback,
            )

            # Copy memory files to the branch
            await self._copy_memory_files_optimized(session_id, branch_session_id)

            logger.info(
                f"Created branch '{branch_name}' from session {session_id}, turn {turn_id}"
            )
            return branch_session_id

        except Exception as e:
            logger.error(f"Failed to create branch: {e}")
            raise ValueError(f"Failed to create branch: {str(e)}")

    async def _copy_session_state_optimized(
        self,
        parent_session_id: str,
        branch_session_id: str,
        parent_turn_id: str,
        bulk_copy: bool = True,
        progress_callback: Optional[callable] = None,
    ) -> None:
        """Copy session state from parent to branch with performance optimizations."""
        try:
            # Get all turns from parent session up to the fork point
            parent_turns = await self.session_manager.get_session_turns(
                parent_session_id
            )

            # Filter turns up to the fork point
            fork_turns = [turn for turn in parent_turns if turn["id"] <= parent_turn_id]

            if bulk_copy:
                # Use bulk insert for better performance
                await self._bulk_copy_turns(
                    fork_turns, branch_session_id, parent_session_id, progress_callback
                )
            else:
                # Fallback to individual inserts for compatibility
                for turn in fork_turns:
                    branch_turn = {
                        "id": str(uuid.uuid4()),
                        "session_id": branch_session_id,
                        "turn_number": turn["turn_number"],
                        "messages": turn["messages"],
                        "tool_calls": turn["tool_calls"],
                        "created_at": datetime.utcnow(),
                        "metadata": {
                            "copied_from": parent_session_id,
                            "original_turn_id": turn["id"],
                        },
                    }
                    await self.session_manager.create_turn(branch_turn)

                    # Update progress if callback provided
                    if progress_callback:
                        progress_callback(len(fork_turns), 1)

        except Exception as e:
            logger.error(f"Failed to copy session state: {e}")
            raise ValueError(f"Failed to copy session state: {str(e)}")

    async def _bulk_copy_turns(
        self,
        parent_turns: List[Dict],
        branch_session_id: str,
        parent_session_id: str,
        progress_callback: Optional[callable] = None,
    ) -> None:
        """Bulk copy turns using batch inserts for better performance."""
        if not parent_turns:
            return

        # Prepare batch data
        batch_data = []
        for turn in parent_turns:
            branch_turn = {
                "session_id": branch_session_id,
                "turn_number": turn["turn_number"],
                "messages": turn["messages"],
                "tool_calls": turn["tool_calls"],
                "created_at": datetime.utcnow(),
                "metadata": {
                    "copied_from": parent_session_id,
                    "original_turn_id": turn["id"],
                },
            }
            batch_data.append(branch_turn)

        # Use batch insert for better performance
        try:
            async with asyncpg.get_pool().acquire() as conn:
                # Use COPY for bulk insert (PostgreSQL specific optimization)
                for i, turn_data in enumerate(batch_data):
                    turn_id = str(uuid.uuid4())
                    await conn.execute(
                        """
                        INSERT INTO branch_turns (turn_id, branch_id, turn_number, messages, tool_calls, created_at, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        turn_id,
                        turn_data["session_id"],
                        turn_data["turn_number"],
                        turn_data["messages"],
                        turn_data["tool_calls"],
                        turn_data["created_at"],
                        turn_data["metadata"],
                    )

                    # Update progress if callback provided
                    if progress_callback and (i + 1) % 10 == 0:  # Update every 10 turns
                        progress_callback(len(batch_data), i + 1)

        except Exception as e:
            logger.error(f"Failed to bulk copy turns: {e}")
            # Fallback to individual inserts
            for turn_data in batch_data:
                await self.session_manager.create_turn(
                    {
                        **turn_data,
                        "id": str(uuid.uuid4()),
                    }
                )

    async def fork_multiple_sessions(
        self,
        session_configs: List[Dict[str, Any]],
        bulk_copy: bool = True,
        progress_callback: Optional[callable] = None,
    ) -> List[Dict[str, Any]]:
        """Create multiple branches from different sessions concurrently.

        Args:
            session_configs: List of configurations for each branch
                Each config should have: session_id, turn_id (optional), branch_name (optional)
            bulk_copy: Use bulk operations for better performance (default: True)
            progress_callback: Optional callback for progress updates

        Returns:
            List of results with branch_id and any errors
        """
        results = []

        async def create_single_branch(
            config: Dict[str, Any], index: int
        ) -> Dict[str, Any]:
            try:
                branch_id = await self.fork_session(
                    session_id=config["session_id"],
                    turn_id=config.get("turn_id"),
                    branch_name=config.get("branch_name"),
                    bulk_copy=bulk_copy,
                )

                if progress_callback:
                    progress_callback(len(session_configs), index + 1)

                return {
                    "index": index,
                    "success": True,
                    "branch_id": branch_id,
                    "session_id": config["session_id"],
                    "branch_name": config.get("branch_name", "auto-generated"),
                }
            except Exception as e:
                return {
                    "index": index,
                    "success": False,
                    "error": str(e),
                    "session_id": config["session_id"],
                    "branch_name": config.get("branch_name", "auto-generated"),
                }

        # Create branches concurrently
        tasks = [
            create_single_branch(config, i) for i, config in enumerate(session_configs)
        ]

        branch_results = await asyncio.gather(*tasks)
        results.extend(branch_results)

        return results

    async def _copy_memory_files_optimized(
        self, parent_session_id: str, branch_session_id: str
    ) -> None:
        """Copy memory files from parent to branch with optimizations."""
        try:
            # Get memory files from parent session
            parent_memory_dir = self.md_store.get_session_memory_dir(parent_session_id)

            if not parent_memory_dir.exists():
                return

            # Create memory directory for branch
            branch_memory_dir = self.md_store.get_session_memory_dir(branch_session_id)
            branch_memory_dir.mkdir(parents=True, exist_ok=True)

            # Copy memory files with optimizations
            await self._bulk_copy_memory_files(parent_memory_dir, branch_memory_dir)

        except Exception as e:
            logger.error(f"Failed to copy memory files: {e}")
            raise ValueError(f"Failed to copy memory files: {str(e)}")

    async def _bulk_copy_memory_files(self, source_dir: Path, target_dir: Path) -> None:
        """Bulk copy memory files with optimizations."""
        memory_files = [
            "PROJECT.md",
            "LEARNED.md",
            "PREFERENCES.md",
            "FACTS.md",
            "DECISIONS.md",
        ]

        # Prepare file copy operations
        copy_operations = []
        for file_name in memory_files:
            source_file = source_dir / file_name
            if source_file.exists():
                target_file = target_dir / file_name
                copy_operations.append((source_file, target_file))

        if not copy_operations:
            return

        # Use concurrent file copying for better performance
        async def copy_file(source: Path, target: Path) -> None:
            try:
                # Read content in memory for better performance
                content = source.read_text(encoding="utf-8")
                target.write_text(content, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to copy {source} to {target}: {e}")

        # Copy files concurrently
        copy_tasks = [copy_file(source, target) for source, target in copy_operations]
        await asyncio.gather(*copy_tasks, return_exceptions=True)

    async def get_branch_performance_metrics(self, session_id: str) -> Dict[str, Any]:
        """Get performance metrics for branches of a session."""
        try:
            async with asyncpg.get_pool().acquire() as conn:
                # Get branch count
                branch_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM session_branches WHERE parent_session_id = $1",
                    session_id,
                )

                # Get average branch creation time (if we had timing data)
                # This would require additional tracking in the future

                # Get largest branch by turn count
                largest_branch = await conn.fetchrow(
                    """
                    SELECT b.branch_id, b.branch_name, COUNT(t.turn_id) as turn_count
                    FROM session_branches b
                    LEFT JOIN branch_turns t ON b.branch_id = t.branch_id
                    WHERE b.parent_session_id = $1
                    GROUP BY b.branch_id, b.branch_name
                    ORDER BY turn_count DESC
                    LIMIT 1
                    """,
                    session_id,
                )

                return {
                    "branch_count": branch_count,
                    "largest_branch": largest_branch,
                    "performance_notes": "Additional metrics can be added with timing tracking",
                }

        except Exception as e:
            logger.error(f"Failed to get branch performance metrics: {e}")
            return {
                "branch_count": 0,
                "largest_branch": None,
                "error": str(e),
            }

    async def list_branches(self, session_id: str) -> List[Dict[str, Any]]:
        """List all branches for a session."""
        try:
            query = """
                SELECT id, name, created_at, status, metadata
                FROM sessions
                WHERE parent_session_id = $1
                ORDER BY created_at DESC
            """
            async with asyncpg.get_pool().acquire() as conn:
                branches = await conn.fetch(query, session_id)

            return [dict(branch) for branch in branches]

        except Exception as e:
            logger.error(f"Failed to list branches: {e}")
            return []

    async def get_branch_info(self, branch_session_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a branch."""
        try:
            branch = await self.session_manager.get_session(branch_session_id)
            if not branch:
                return None

            return {
                "id": branch["id"],
                "name": branch["name"],
                "parent_session_id": branch["parent_session_id"],
                "parent_turn_id": branch["parent_turn_id"],
                "created_at": branch["created_at"],
                "status": branch["status"],
                "metadata": branch["metadata"],
            }

        except Exception as e:
            logger.error(f"Failed to get branch info: {e}")
            return None

    async def delete_branch(self, branch_session_id: str) -> bool:
        """Delete a branch session."""
        try:
            # Get branch info
            branch_info = await self.get_branch_info(branch_session_id)
            if not branch_info:
                return False

            # Delete the session
            await self.session_manager.delete_session(branch_session_id)

            # Delete memory files
            branch_memory_dir = self.md_store.get_session_memory_dir(branch_session_id)
            if branch_memory_dir.exists():
                import shutil

                shutil.rmtree(branch_memory_dir)

            logger.info(f"Deleted branch {branch_session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete branch: {e}")
            return False

    @emit_span(name="branch.merge", attributes={"operation": "merge_branches"})
    async def merge_branches(
        self,
        source_session_id: str,
        target_session_id: str,
        merge_strategy: str = "append",
        conflict_resolution: str = "manual",
    ) -> Dict[str, Any]:
        """Merge a branch session into a target session.

        Args:
            source_session_id: ID of the branch session to merge
            target_session_id: ID of the target session to merge into
            merge_strategy: How to merge turns ('append', 'interleave', 'replace')
            conflict_resolution: How to handle conflicts ('manual', 'auto', 'source')

        Returns:
            Dictionary with merge results and conflicts
        """
        try:
            # Get session information
            source_session = await self.session_manager.get_session(source_session_id)
            target_session = await self.session_manager.get_session(target_session_id)

            if not source_session:
                raise ValueError(f"Source session not found: {source_session_id}")
            if not target_session:
                raise ValueError(f"Target session not found: {target_session_id}")

            # Get turns from both sessions
            source_turns = await self.session_manager.get_session_turns(
                source_session_id
            )
            target_turns = await self.session_manager.get_session_turns(
                target_session_id
            )

            # Find the common ancestor (last common turn)
            common_turn_id = await self._find_common_ancestor(
                source_turns, target_turns
            )

            # Get new turns from source (after the common ancestor)
            new_source_turns = [
                turn for turn in source_turns if turn["id"] > common_turn_id
            ]

            # Merge turns based on strategy
            merged_turns = await self._merge_turns(
                target_turns, new_source_turns, merge_strategy, conflict_resolution
            )

            # Save merged turns to target session
            merge_results = []
            for turn in merged_turns:
                # Create new turn for target session
                merged_turn = {
                    "id": str(uuid.uuid4()),
                    "session_id": target_session_id,
                    "turn_number": turn["turn_number"],
                    "messages": turn["messages"],
                    "tool_calls": turn["tool_calls"],
                    "created_at": datetime.utcnow(),
                    "metadata": {
                        "merged_from": source_session_id,
                        "original_turn_id": turn["id"],
                        "merge_strategy": merge_strategy,
                        "merged_at": datetime.utcnow().isoformat(),
                    },
                }
                await self.session_manager.create_turn(merged_turn)
                merge_results.append(
                    {
                        "turn_id": merged_turn["id"],
                        "turn_number": turn["turn_number"],
                        "messages_count": len(turn["messages"]),
                        "tool_calls_count": len(turn["tool_calls"]),
                    }
                )

            # Merge memory files
            await self._merge_memory_files(source_session_id, target_session_id)

            # Update session metadata
            await self._update_merge_metadata(
                target_session_id, source_session_id, merge_strategy, merge_results
            )

            logger.info(
                f"Merged branch {source_session_id} into {target_session_id} "
                f"using strategy '{merge_strategy}'"
            )

            return {
                "success": True,
                "source_session": source_session["name"],
                "target_session": target_session["name"],
                "merge_strategy": merge_strategy,
                "merged_turns": len(merge_results),
                "merge_results": merge_results,
                "conflicts_resolved": len(
                    merge_results
                ),  # Would be actual conflict count in real impl
            }

        except Exception as e:
            logger.error(f"Failed to merge branches: {e}")
            raise ValueError(f"Failed to merge branches: {str(e)}")

    async def _find_common_ancestor(
        self, source_turns: List[Dict], target_turns: List[Dict]
    ) -> str:
        """Find the common ancestor turn ID."""
        # This is a simplified implementation - in a real system,
        # we would track the actual common ancestor through session history
        if target_turns:
            return target_turns[-1]["id"]
        return "0"  # No common ancestor

    async def _merge_turns(
        self,
        target_turns: List[Dict],
        source_turns: List[Dict],
        strategy: str,
        conflict_resolution: str,
    ) -> List[Dict]:
        """Merge turns from source and target sessions."""
        if strategy == "append":
            # Append source turns to target turns
            return target_turns + source_turns
        elif strategy == "interleave":
            # Interleave turns based on timestamps (simplified)
            merged = []
            i, j = 0, 0
            while i < len(target_turns) and j < len(source_turns):
                if target_turns[i]["created_at"] <= source_turns[j]["created_at"]:
                    merged.append(target_turns[i])
                    i += 1
                else:
                    merged.append(source_turns[j])
                    j += 1
            merged.extend(target_turns[i:])
            merged.extend(source_turns[j:])
            return merged
        elif strategy == "replace":
            # Replace target turns with source turns (simplified)
            return target_turns[: -len(source_turns)] + source_turns
        else:
            raise ValueError(f"Unknown merge strategy: {strategy}")

    async def _merge_memory_files(
        self, source_session_id: str, target_session_id: str
    ) -> None:
        """Merge memory files from source to target session."""
        try:
            # Get memory directories
            source_memory_dir = self.md_store.get_session_memory_dir(source_session_id)
            target_memory_dir = self.md_store.get_session_memory_dir(target_session_id)

            if not source_memory_dir.exists():
                return

            # Create target memory directory if it doesn't exist
            target_memory_dir.mkdir(parents=True, exist_ok=True)

            # Merge memory files
            memory_files = [
                "PROJECT.md",
                "LEARNED.md",
                "PREFERENCES.md",
                "FACTS.md",
                "DECISIONS.md",
            ]

            for file_name in memory_files:
                source_file = source_memory_dir / file_name
                target_file = target_memory_dir / file_name

                if source_file.exists():
                    if target_file.exists():
                        # Append content from source to target
                        target_content = target_file.read_text(encoding="utf-8")
                        source_content = source_file.read_text(encoding="utf-8")

                        # Add separator and append
                        merged_content = target_content + "\n\n---\n\n" + source_content
                        target_file.write_text(merged_content, encoding="utf-8")
                    else:
                        # Copy file to target
                        target_file.write_text(source_file.read_text(encoding="utf-8"))

        except Exception as e:
            logger.error(f"Failed to merge memory files: {e}")
            raise ValueError(f"Failed to merge memory files: {str(e)}")

    async def _update_merge_metadata(
        self,
        target_session_id: str,
        source_session_id: str,
        strategy: str,
        results: List[Dict],
    ) -> None:
        """Update session metadata after merge."""
        try:
            # Get target session
            target_session = await self.session_manager.get_session(target_session_id)
            if not target_session:
                return

            # Update metadata
            merge_metadata = target_session.get("metadata", {})
            merge_metadata.setdefault("merge_history", []).append(
                {
                    "source_session_id": source_session_id,
                    "merge_strategy": strategy,
                    "merged_at": datetime.utcnow().isoformat(),
                    "merged_turns": len(results),
                    "results": results,
                }
            )

            # Update session
            await self.session_manager.update_session_metadata(
                target_session_id, merge_metadata
            )

        except Exception as e:
            logger.error(f"Failed to update merge metadata: {e}")

    async def get_merge_history(self, session_id: str) -> List[Dict]:
        """Get merge history for a session."""
        try:
            session = await self.session_manager.get_session(session_id)
            if not session:
                return []

            return session.get("metadata", {}).get("merge_history", [])

        except Exception as e:
            logger.error(f"Failed to get merge history: {e}")
            return []


# Global instance
_branch_manager = None


def get_branch_manager() -> BranchManager:
    """Get the global branch manager instance."""
    global _branch_manager
    if _branch_manager is None:
        _branch_manager = BranchManager()
    return _branch_manager
