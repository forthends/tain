"""Skill composition — create a new skill by merging sub-skills."""

from __future__ import annotations

from tain_agent.plugins.skill.model import MaturityLevel, Skill, Step


def compose_skills(
    name: str,
    display_name: str,
    description: str,
    sub_skills: list[Skill],
    workflow: list[Step] | None = None,
) -> Skill:
    """Compose a new skill from multiple sub-skills.

    The composed skill:
      - Merges all tools from sub-skills (deduplicated).
      - Merges all knowledge_refs from sub-skills (deduplicated).
      - Sets initial maturity to min(sub_maturities) - 1 (floor NOVICE).
      - Optionally takes a custom workflow; if none given, uses a
        flattened ordered list of sub-skill steps.

    Args:
        name: Unique name for the composed skill.
        display_name: Human-readable name.
        description: What the composed skill does.
        sub_skills: The sub-skills to merge.
        workflow: Optional custom workflow for the composed skill.

    Returns the new composed Skill.
    """
    # Merge tools and knowledge refs
    tools: list[str] = []
    knowledge_refs: list[str] = []
    seen_tools: set[str] = set()
    seen_refs: set[str] = set()

    for s in sub_skills:
        for t in s.tools:
            if t not in seen_tools:
                tools.append(t)
                seen_tools.add(t)
        for r in s.knowledge_refs:
            if r not in seen_refs:
                knowledge_refs.append(r)
                seen_refs.add(r)

    # Compute initial maturity: min(sub_maturities) - 1, floor NOVICE
    if sub_skills:
        min_mat = min(s.maturity for s in sub_skills)
        initial_mat = MaturityLevel(max(MaturityLevel.NOVICE.value, min_mat.value - 1))
    else:
        initial_mat = MaturityLevel.NOVICE

    # Build workflow
    if workflow is not None:
        final_workflow = list(workflow)
    else:
        final_workflow: list[Step] = []
        seen_steps: set[str] = set()
        order = 0
        for s in sub_skills:
            for step in s.workflow:
                if step.name not in seen_steps:
                    step_copy = Step(
                        name=step.name,
                        description=step.description,
                        tool=step.tool,
                        expected_output=step.expected_output,
                        order=order,
                    )
                    final_workflow.append(step_copy)
                    seen_steps.add(step.name)
                    order += 1

    return Skill(
        name=name,
        display_name=display_name,
        description=description,
        category="composed",
        tools=tools,
        knowledge_refs=knowledge_refs,
        workflow=final_workflow,
        maturity=initial_mat,
    )
