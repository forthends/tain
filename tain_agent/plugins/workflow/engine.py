"""Workflow engine — DAG-based workflow state machine with cycle detection."""

from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Literal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class StepType(str, Enum):
    TOOL = "tool"
    LLM = "llm"
    HUMAN = "human"
    SUB_WORKFLOW = "sub_workflow"
    CONDITION = "condition"


@dataclass
class RetryPolicy:
    """Retry configuration for a workflow step."""

    max_retries: int = 0
    delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    retry_on: list[str] = field(default_factory=lambda: ["error"])


@dataclass
class WorkflowStep:
    """A single step in a workflow DAG."""

    name: str
    description: str = ""
    step_type: StepType = StepType.TOOL
    tool: str = ""                    # tool name (for TOOL type)
    prompt: str = ""                  # LLM prompt (for LLM type)
    depends_on: list[str] = field(default_factory=list)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_seconds: float = 300.0
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    """Result of executing a single workflow step."""

    step_name: str
    success: bool
    output: Any = None
    error: str | None = None
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    retry_count: int = 0


@dataclass
class Workflow:
    """A DAG-based workflow with state management.

    The workflow is a directed acyclic graph where steps depend on other
    steps. Execution proceeds in topological order, with parallel steps
    grouped by dependency depth.
    """

    name: str
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    state: WorkflowState = WorkflowState.PENDING
    context: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, list[StepResult]] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def validate(self) -> list[str]:
        """Validate the workflow DAG. Returns list of error messages.

        Checks:
          1. No duplicate step names.
          2. All dependency references resolve to existing steps.
          3. No cycles in the dependency graph.
        """
        errors: list[str] = []

        # 1. Duplicate names
        names = [s.name for s in self.steps]
        if len(names) != len(set(names)):
            seen: set[str] = set()
            for n in names:
                if n in seen:
                    errors.append(f"Duplicate step name: {n}")
                seen.add(n)

        name_set = set(names)

        # 2. Unknown dependencies
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in name_set:
                    errors.append(
                        f"Step '{step.name}' depends on unknown step '{dep}'"
                    )

        # 3. Cycle detection via topological sort check
        if not errors:
            try:
                self.topological_order()
            except ValueError as e:
                errors.append(str(e))

        return errors

    def topological_order(self) -> list[str]:
        """Return step names in topological order (Kahn's algorithm).

        Raises ValueError if a cycle is detected.
        """
        # Build adjacency and in-degree
        in_degree: dict[str, int] = {s.name: 0 for s in self.steps}
        adj: dict[str, list[str]] = {s.name: [] for s in self.steps}

        for step in self.steps:
            for dep in step.depends_on:
                adj[dep].append(step.name)
                in_degree[step.name] = in_degree.get(step.name, 0) + 1

        # Kahn's algorithm
        queue: deque[str] = deque()
        for name, deg in in_degree.items():
            if deg == 0:
                queue.append(name)

        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self.steps):
            cycle_nodes = set(in_degree.keys()) - set(order)
            raise ValueError(
                f"Cycle detected in workflow: steps {sorted(cycle_nodes)} "
                "form a cycle"
            )

        return order

    def parallel_groups(self) -> list[list[str]]:
        """Group steps into parallel execution batches by dependency depth.

        Each group contains steps whose dependencies are all satisfied by
        steps in previous groups. Steps within a group can run in parallel.
        """
        # First get topological order
        order = self.topological_order()

        # Compute depth for each node: 0 for no-dependency nodes,
        # 1 + max(dep depths) for others
        depth: dict[str, int] = {}
        for name in order:
            step = next(s for s in self.steps if s.name == name)
            if not step.depends_on:
                depth[name] = 0
            else:
                depth[name] = 1 + max(depth[d] for d in step.depends_on)

        # Group by depth
        max_depth = max(depth.values()) if depth else 0
        groups: list[list[str]] = [[] for _ in range(max_depth + 1)]
        for name, d in depth.items():
            groups[d].append(name)

        return groups
