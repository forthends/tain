"""Pydantic schema for config.yaml validation."""
from typing import Optional
from pydantic import BaseModel, Field


class RetryConfigSchema(BaseModel):
    enabled: bool = True
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0


class LLMConfigSchema(BaseModel):
    provider: str = "minimax"
    model: str = "MiniMax-M2.7"
    max_tokens: int = 8192
    api_key_env: str = "MINIMAX_API_KEY"
    base_url: Optional[str] = None
    retry: RetryConfigSchema = Field(default_factory=RetryConfigSchema)


class AgentConfigSchema(BaseModel):
    default_agent: str = "default"
    timezone: str = "Asia/Shanghai"


class AgentWorkspaceSchema(BaseModel):
    dir: str = "agent_workspace"
    auto_create: bool = True


class ConversationConfigSchema(BaseModel):
    token_limit: int = 80000
    model_context_window: int = 131072


class ExplorationConfigSchema(BaseModel):
    max_exploration_cycles: int = 10
    max_definition_cycles: int = 5
    min_bootstrap_cycles: int = 5
    min_action_categories: int = 2


class DiversityConstraintsSchema(BaseModel):
    allow_network: bool = True
    allow_file_write: bool = True
    allow_forge: bool = True


class DiversityToolBiasSchema(BaseModel):
    observation: float = 1.0
    creation: float = 1.0
    reflection: float = 1.0


class DiversitySchema(BaseModel):
    seed: str = "random"
    tool_bias: DiversityToolBiasSchema = Field(default_factory=DiversityToolBiasSchema)
    knowledge_seeds: list[str] = Field(default_factory=list)
    constraints: DiversityConstraintsSchema = Field(default_factory=DiversityConstraintsSchema)


class DrivesExplorationSchema(BaseModel):
    curiosity_bonus_rate: float = 0.05
    max_curiosity_bonus: float = 0.30
    novelty_weight: float = 0.20
    idle_pressure_rate: float = 0.10
    max_idle_pressure: float = 0.40


class DrivesSchema(BaseModel):
    exploration: DrivesExplorationSchema = Field(default_factory=DrivesExplorationSchema)


class ForgeConfigSchema(BaseModel):
    allowed_packages: list[str] = Field(default=[
        "requests", "pandas", "numpy", "pytest", "beautifulsoup4",
        "matplotlib", "plotly", "scipy", "pillow", "httpx", "aiohttp",
    ])
    max_forges_per_session: int = 3


class MetricsSchema(BaseModel):
    degradation_alert_threshold: float = 0.15
    auto_collect_on_report: bool = True
    snapshot_dir: str = "tain_agent/state/metrics_snapshots"


class SafetySchema(BaseModel):
    protected_paths: list[str] = Field(default_factory=list)
    confirm_destructive: bool = False


class LoggingSchema(BaseModel):
    directory: str = "tain_agent/logs"
    decision_log_file: str = "decisions.jsonl"
    memory_file: str = "memory.json"
    checkpoint_file: str = "conversation_checkpoint.json"
    lineage_file: str = "lineage.jsonl"


class FrameworkConfigSchema(BaseModel):
    version: str = "0.5.1"
    min_agent_version: str = "0.0.1"


class AppConfig(BaseModel):
    framework: FrameworkConfigSchema = Field(default_factory=FrameworkConfigSchema)
    agent: AgentConfigSchema = Field(default_factory=AgentConfigSchema)
    agent_workspace: AgentWorkspaceSchema = Field(default_factory=AgentWorkspaceSchema)
    llm: LLMConfigSchema = Field(default_factory=LLMConfigSchema)
    conversation: ConversationConfigSchema = Field(default_factory=ConversationConfigSchema)
    exploration: ExplorationConfigSchema = Field(default_factory=ExplorationConfigSchema)
    diversity: DiversitySchema = Field(default_factory=DiversitySchema)
    drives: DrivesSchema = Field(default_factory=DrivesSchema)
    forge: ForgeConfigSchema = Field(default_factory=ForgeConfigSchema)
    metrics: MetricsSchema = Field(default_factory=MetricsSchema)
    safety: SafetySchema = Field(default_factory=SafetySchema)
    logging: LoggingSchema = Field(default_factory=LoggingSchema)
