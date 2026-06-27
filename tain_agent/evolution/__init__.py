"""Evolution module — goal system, self-modification, capability tracking,
self-improvement pipeline, and continuous improvement loop.

This is the "二生三，三生万物" engine:
  - Goal: what the agent wants to achieve
  - SelfModify: ability to change own code
  - CapabilityRegistry: self-knowledge of what it can/cannot do
  - SelfImprovementPipeline: systematic analyze→design→forge→verify→register
  - ImprovementLoop: continuous cyclic self-evolution scheduler
  - EvolutionReporter: version bump, report generation, git commit/push
"""

from tain_agent.evolution.goal import Goal, GoalSystem
from tain_agent.evolution.self_modify import SelfModify
from tain_agent.evolution.capability import CapabilityRegistry, DESIRED_CAPABILITIES
from tain_agent.evolution.pipeline import (
    SelfImprovementPipeline,
    ImprovementSpec,
    StageResult,
    PipelineResult,
)
from tain_agent.evolution.improvement_loop import ImprovementLoop
from tain_agent.evolution.reporter import EvolutionReporter
from tain_agent.evolution.behavior_contract import (
    BehaviorContract,
    ContractValidationError,
    ContractComplianceResult,
)
