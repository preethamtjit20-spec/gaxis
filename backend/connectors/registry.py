"""Connector registry — central hub for discovering and executing skills.

The registry:
  1. Holds all registered connectors
  2. Provides skill discovery for the orchestrator
  3. Routes skill execution to the right connector
  4. Generates prompt context so agents know what skills are available
"""

from __future__ import annotations

import logging
from typing import Any

from backend.connectors.base import BaseConnector, Skill, SkillResult

logger = logging.getLogger("gaxis.connectors")


class ConnectorRegistry:
    """Central registry for all connectors and their skills."""

    def __init__(self):
        self._connectors: dict[str, BaseConnector] = {}
        self._skill_index: dict[str, tuple[str, str]] = {}  # full_tool_name → (connector, skill)

    def register(self, connector: BaseConnector) -> None:
        """Register a connector and index its skills."""
        self._connectors[connector.name] = connector
        for skill_name, skill in connector.skills.items():
            tool_name = f"skill_{connector.name}_{skill_name}"
            self._skill_index[tool_name] = (connector.name, skill_name)
        logger.info(
            f"Registered connector: {connector.name} "
            f"({len(connector.skills)} skills)"
        )

    def get_connector(self, name: str) -> BaseConnector | None:
        return self._connectors.get(name)

    @property
    def connectors(self) -> dict[str, BaseConnector]:
        return self._connectors

    # ── Skill discovery ──

    def all_skills(self) -> list[Skill]:
        """Return all registered skills across all connectors."""
        skills = []
        for conn in self._connectors.values():
            skills.extend(conn.skills.values())
        return skills

    def find_skills(self, query: str) -> list[Skill]:
        """Find skills matching a natural language query."""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        scored: list[tuple[int, Skill]] = []

        # Common words to ignore during matching
        stop_words = {
            "a", "the", "to", "for", "in", "on", "and", "or", "my", "is", "it",
            "an", "of", "search", "find", "get", "check", "open", "go", "do",
            "please", "can", "you", "i", "want", "need", "help", "me", "with",
        }
        meaningful_words = query_words - stop_words

        for skill in self.all_skills():
            score = 0
            # Exact skill name match
            if query_lower in skill.name.lower():
                score += 15
            # Tag matching — require the tag word to be meaningful
            for tag in skill.tags:
                tag_l = tag.lower()
                if tag_l in meaningful_words:
                    score += 8
                elif any(w in tag_l for w in meaningful_words if len(w) > 3):
                    score += 3
            # Description word overlap (only meaningful words)
            desc_lower = skill.description.lower()
            for word in meaningful_words:
                if len(word) > 3 and word in desc_lower:
                    score += 2
            # Example matching
            for example in skill.examples:
                ex_lower = example.lower()
                overlap = sum(1 for w in meaningful_words if len(w) > 3 and w in ex_lower)
                score += overlap
            if score > 5:  # Minimum threshold to avoid weak matches
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored]

    def is_skill_tool(self, tool_name: str) -> bool:
        """Check if a Gemini tool name maps to a connector skill."""
        return tool_name in self._skill_index

    async def execute_skill_tool(
        self, tool_name: str, params: dict,
        tool_executor=None, emit_fn=None, task_id: str = "", mode: str = "extension",
    ) -> SkillResult:
        """Execute a skill by its Gemini tool name."""
        if tool_name not in self._skill_index:
            return SkillResult(success=False, error=f"Unknown skill tool: {tool_name}")

        connector_name, skill_name = self._skill_index[tool_name]
        connector = self._connectors.get(connector_name)
        if not connector:
            return SkillResult(success=False, error=f"Connector not found: {connector_name}")

        logger.info(f"Executing skill: {connector_name}.{skill_name} with {params}")
        return await connector.execute_skill(
            skill_name, params,
            tool_executor=tool_executor, emit_fn=emit_fn,
            task_id=task_id, mode=mode,
        )

    def find_deterministic_skill(self, instruction: str) -> tuple[Skill, str, str] | None:
        """Find the best skill with a deterministic executor for this instruction.

        Returns (skill, connector_name, skill_name) or None if no match.
        """
        matches = self.find_skills(instruction)
        for skill in matches:
            if skill.has_executor:
                conn_name = skill.connector
                return skill, conn_name, skill.name
        return None

    async def execute_deterministic(
        self,
        instruction: str,
        params: dict,
        tool_executor,
        emit_fn=None,
        task_id: str = "",
        mode: str = "extension",
    ) -> SkillResult | None:
        """Try to execute the task deterministically using a matching skill.

        Returns None if no deterministic skill matches. Otherwise returns
        the SkillResult from the executor.
        """
        match = self.find_deterministic_skill(instruction)
        if not match:
            return None

        skill, connector_name, skill_name = match
        connector = self._connectors.get(connector_name)
        if not connector:
            return None

        logger.info(
            f"Deterministic execution: {connector_name}.{skill_name} "
            f"(skipping LLM)"
        )
        return await connector.execute_skill(
            skill_name, params,
            tool_executor=tool_executor, emit_fn=emit_fn,
            task_id=task_id, mode=mode,
        )

    # ── Gemini integration ──

    def get_gemini_tools(self) -> list:
        """Get all skill FunctionDeclarations for Gemini."""
        tools = []
        for skill in self.all_skills():
            tools.append(skill.to_gemini_tool())
        return tools

    def get_orchestrator_prompt(self) -> str:
        """Generate the skills section for the orchestrator prompt."""
        if not self._connectors:
            return ""

        lines = [
            "\n\n── CONNECTED SERVICES & SKILLS ──",
            "You have access to the following service connectors. "
            "When a task involves these services, use the appropriate skill "
            "instead of generic browser navigation.\n",
        ]

        for connector in self._connectors.values():
            lines.append(connector.get_skills_prompt())
            lines.append("")

        lines.append(
            "To use a skill, delegate to the appropriate specialist with "
            "the skill instruction, or call the skill tool directly if available."
        )
        return "\n".join(lines)

    def get_skill_routing_hints(self, instruction: str) -> dict[str, Any]:
        """Analyze an instruction and suggest relevant skills/connectors."""
        relevant = self.find_skills(instruction)
        if not relevant:
            return {"has_skills": False, "skills": []}

        return {
            "has_skills": True,
            "skills": [
                {
                    "name": s.full_name,
                    "description": s.description,
                    "mode": s.mode.value,
                    "start_url": s.start_url,
                }
                for s in relevant[:5]
            ],
            "primary_connector": relevant[0].connector,
        }
