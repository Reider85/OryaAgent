"""Memory extraction prompts for B-22 Memory-extractor LLM-worker."""

from __future__ import annotations

import json
from typing import List

MEMORY_EXTRACTION_PROMPT = """You are a memory extraction assistant. Analyze the conversation and extract structured facts, decisions, and preferences.

Extract items in this JSON format:
{
  "items": [
    {
      "type": "fact|decision|preference|todo",
      "content": "extracted content", 
      "confidence": 0.5-0.95,
      "project": "project_name",
      "supersede_id": null,
      "needs_review": false
    }
  ]
}

Confidence scoring rules:
- Explicit user mentions ("remember that", "I want", "I prefer", "let's decide") → confidence 0.95
- High-confidence inferred items (clear facts, decisions, preferences) → confidence 0.8  
- Low-confidence items (unclear context, ambiguous) → confidence 0.5
- If confidence < 0.7, mark needs_review=true
- Deduplicate similar content

Content type definitions:
- fact: Objective information, code patterns, project details
- decision: Choices made, approaches selected, decisions reached
- preference: User preferences, style choices, tool preferences
- todo: Action items, tasks, next steps

Conversation:
{messages}

Return only the JSON array of extracted items.
"""

DEDUPLICATION_SEARCH_PROMPT = """Search for similar existing memory items to avoid duplication.

Query: {query}
Context: {context}

Return JSON with similarity analysis:
{
  "similar_items": [
    {
      "id": "existing_item_id",
      "content": "existing content",
      "similarity_score": 0.0-1.0
    }
  ],
  "should_supersede": true/false,
  "supersede_id": "item_id_to_supersede" or null
}

Use semantic similarity and exact content matching.
"""

MEMORY_EXTRACTION_SUMMARY_PROMPT = """Generate a concise summary of extracted facts for memory storage.

Summary requirements:
- Keep under 200 characters
- Capture key essence of the extracted fact
- Use clear, descriptive language
- Include relevant technical terms if applicable

Fact: {fact_content}
Type: {fact_type}
Confidence: {confidence}

Summary:
"""