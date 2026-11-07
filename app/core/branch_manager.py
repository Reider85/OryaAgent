"""BranchManager: fork session (B-09) - create branch from any turn.

Provides functionality to create branches from any session turn,
enabling parallel development and experimentation.
"""

from __future__ import annotations

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
    ) -> str:
        """Create a new branch from any session turn.

        Args:
            session_id: ID of the parent session
            turn_id: Specific turn to fork from (defaults to latest)
            branch_name: Name for the new branch (auto-generated if None)
            parent_turn_id: ID of the parent turn (for reference)

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
                },
            }

            # Save the branch session
            await self.session_manager.create_session(branch_session)

            # Copy session state to the branch
            await self._copy_session_state(session_id, branch_session_id, turn_id)

            # Copy memory files to the branch
            await self._copy_memory_files(session_id, branch_session_id)

            logger.info(f"Created branch '{branch_name}' from session {session_id}, turn {turn_id}")
            return branch_session_id

        except Exception as e:
            logger.error(f"Failed to create branch: {e}")
            raise ValueError(f"Failed to create branch: {str(e)}")

    async def _copy_session_state(
        self, parent_session_id: str, branch_session_id: str, parent_turn_id: str
    ) -> None:
        """Copy session state from parent to branch."""
        try:
            # Get all turns from parent session up to the fork point
            parent_turns = await self.session_manager.get_session_turns(parent_session_id)
            
            # Filter turns up to the fork point
            fork_turns = [turn for turn in parent_turns if turn["id"] <= parent_turn_id]
            
            # Copy turns to branch session
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

        except Exception as e:
            logger.error(f"Failed to copy session state: {e}")
            raise ValueError(f"Failed to copy session state: {str(e)}")

    async def _copy_memory_files(self, parent_session_id: str, branch_session_id: str) -> None:
        """Copy memory files from parent to branch."""
        try:
            # Get memory files from parent session
            parent_memory_dir = self.md_store.get_session_memory_dir(parent_session_id)
            
            if not parent_memory_dir.exists():
                return

            # Create memory directory for branch
            branch_memory_dir = self.md_store.get_session_memory_dir(branch_session_id)
            branch_memory_dir.mkdir(parents=True, exist_ok=True)

            # Copy memory files
            memory_files = ["PROJECT.md", "LEARNED.md", "PREFERENCES.md", "FACTS.md", "DECISIONS.md"]
            
            for file_name in memory_files:
                source_file = parent_memory_dir / file_name
                if source_file.exists():
                    destination_file = branch_memory_dir / file_name
                    destination_file.write_text(source_file.read_text(encoding="utf-8"))

        except Exception as e:
            logger.error(f"Failed to copy memory files: {e}")
            raise ValueError(f"Failed to copy memory files: {str(e)}")

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


# Global instance
_branch_manager = None


def get_branch_manager() -> BranchManager:
    """Get the global branch manager instance."""
    global _branch_manager
    if _branch_manager is None:
        _branch_manager = BranchManager()
    return _branch_manager