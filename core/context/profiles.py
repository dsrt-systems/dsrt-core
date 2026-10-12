"""
Context Profiles (C4 §47).

Defines how the token budget is allocated for different types of agents
during context compilation.
"""

from __future__ import annotations

from schemas.domain.context import ContextProfile


class ContextProfileManager:
    """Provides default and specialized context profiles for agents."""

    @staticmethod
    def get_profile(agent_slug: str) -> ContextProfile:
        """Get the context profile for a specific agent."""
        
        if agent_slug == "research_intelligence":
            return ContextProfile(
                agent_slug=agent_slug,
                task_priority=0.9,
                recent_events_priority=0.4,
                semantic_memory_priority=0.8,
                episodic_memory_priority=0.2,
                artifacts_priority=0.7,
                procedural_memory_priority=0.5,
                max_memory_items=30,
                max_evidence_items=50,
            )
            
        if agent_slug == "software_engineering":
            return ContextProfile(
                agent_slug=agent_slug,
                task_priority=0.9,
                recent_events_priority=0.8,
                semantic_memory_priority=0.4,
                episodic_memory_priority=0.3,
                artifacts_priority=0.8,  # High priority for code artifacts
                procedural_memory_priority=0.6,
                max_memory_items=20,
                max_evidence_items=30,
            )

        # Default fallback profile
        return ContextProfile(
            agent_slug=agent_slug,
            task_priority=0.8,
            recent_events_priority=0.5,
            semantic_memory_priority=0.5,
            episodic_memory_priority=0.3,
            artifacts_priority=0.5,
            procedural_memory_priority=0.4,
            max_memory_items=15,
            max_evidence_items=20,
        )