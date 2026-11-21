"""Turn context for capability-based tool filtering (B-29)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TurnContext:
    """Context for a single turn used by CapabilityRegistry to filter tools.

    This context provides information about the current turn to determine
    which tools are relevant and should be made available to the LLM.
    """

    # Language context
    language: str | None = None
    """Current programming language based on file extension or user intent."""

    # File context
    file_path: str | None = None
    """Path of the file being worked on, if any."""

    file_content: str | None = None
    """Content of the file being worked on, if available."""

    # Intent context
    intent: str | None = None
    """User's intent (e.g., 'rename', 'search', 'build', 'test')."""

    # Memory context
    referential_marker: bool = False
    """Whether the user message contains referential markers like 'помнишь', 'ранее', etc."""

    asking_about_past: bool = False
    """Whether the user is asking about past work or decisions."""

    # Search context
    cross_project_search: bool = False
    """Whether the user is searching across multiple projects."""

    # LSP context
    has_symbol_at_cursor: bool = False
    """Whether there's a symbol definition at the current cursor position."""

    # Additional context fields
    turn_count: int = 0
    """Current turn number in the session."""

    last_message: str = ""
    """The last user message for analysis."""

    previous_messages: list[str] = None
    """Previous messages in the session for context."""

    current_dir: str = "/"
    """Current working directory."""

    def __post_init__(self):
        """Initialize default values for list fields."""
        if self.previous_messages is None:
            self.previous_messages = []

    @classmethod
    def from_session_state(cls, session_state: dict[str, Any]) -> TurnContext:
        """Create TurnContext from session state.

        Args:
            session_state: LangGraph session state dictionary.

        Returns:
            TurnContext instance populated from session state.
        """
        context = cls()

        # Extract basic fields
        context.turn_count = session_state.get("turn_count", 0)
        context.last_message = session_state.get("last_message", "")
        context.previous_messages = session_state.get("previous_messages", [])
        context.current_dir = session_state.get("current_dir", "/")

        # Extract file context
        context.file_path = session_state.get("file_path")
        context.file_content = session_state.get("file_content")

        # Extract language from file path if not explicitly set
        if context.file_path and not context.language:
            context.language = cls._detect_language_from_path(context.file_path)

        # Extract intent from context
        context.intent = session_state.get("intent")

        # Extract memory-related context
        context.referential_marker = cls._has_referential_marker(context.last_message)
        context.asking_about_past = cls._is_asking_about_past(context.last_message)

        # Extract search context
        context.cross_project_search = session_state.get("cross_project_search", False)

        # Extract LSP context
        context.has_symbol_at_cursor = session_state.get("has_symbol_at_cursor", False)

        return context

    @staticmethod
    def _detect_language_from_path(file_path: str | Path) -> str | None:
        """Detect programming language from file path.

        Args:
            file_path: Path to analyze.

        Returns:
            Detected language or None if unknown.
        """
        if not file_path:
            return None

        path = Path(file_path)
        suffix = path.suffix.lower()

        language_map = {
            ".java": "java",
            ".kt": "kotlin",
            ".scala": "scala",
            ".py": "python",
            ".rs": "rust",
            ".go": "go",
            ".js": "javascript",
            ".mjs": "javascript",
            ".cjs": "javascript",
            ".ts": "typescript",
            ".tsx": "frontend",
            ".jsx": "frontend",
            ".css": "css",
            ".html": "html",
            ".lua": "lua",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "cpp",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".php": "php",
            ".rb": "ruby",
            ".swift": "swift",
        }

        return language_map.get(suffix)

    @staticmethod
    def _has_referential_marker(message: str) -> bool:
        """Check if message contains referential markers.

        Args:
            message: User message to analyze.

        Returns:
            True if referential markers are found.
        """
        if not message:
            return False

        markers = [
            "помнишь",
            "обсуждали",
            "ранее",
            "в прошлый раз",
            "раньше",
            "до этого",
            "предыдущий",
            "предыдущие",
            "remember",
            "discussed",
            "earlier",
            "before",
            "previous",
            "earlier",
        ]

        message_lower = message.lower()
        return any(marker in message_lower for marker in markers)

    @staticmethod
    def _is_asking_about_past(message: str) -> bool:
        """Check if user is asking about past work.

        Args:
            message: User message to analyze.

        Returns:
            True if asking about past work.
        """
        if not message:
            return False

        patterns = [
            "что мы делали",
            "что было сделано",
            "как мы решали",
            "какие решения",
            "что решили",
            "как мы работали",
            "what did we do",
            "what was done",
            "how did we solve",
            "what decisions",
            "what solutions",
        ]

        message_lower = message.lower()
        return any(pattern in message_lower for pattern in patterns)

    def to_dict(self) -> dict[str, Any]:
        """Convert context to dictionary for serialization."""
        return {
            "language": self.language,
            "file_path": self.file_path,
            "file_content": self.file_content,
            "intent": self.intent,
            "referential_marker": self.referential_marker,
            "asking_about_past": self.asking_about_past,
            "cross_project_search": self.cross_project_search,
            "has_symbol_at_cursor": self.has_symbol_at_cursor,
            "turn_count": self.turn_count,
            "last_message": self.last_message,
            "previous_messages": self.previous_messages,
            "current_dir": self.current_dir,
        }
