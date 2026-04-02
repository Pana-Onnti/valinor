"""
Playground Swarm — Agent registry.

Imports and exports all 10 playground agents for the orchestrator.
"""

from scripts.playground.agents.base import (
    PlaygroundAgent,
    PlaygroundContext,
    AgentResult,
    DatasetRecord,
)

# ── Tier 1: Hunters (fetch real-world data) ─────────────────────────────
from scripts.playground.agents.public_data_scout import PublicDataScoutAgent
from scripts.playground.agents.real_company_harvester import RealCompanyHarvesterAgent

# ── Tier 2: Generators (synthetic data) ─────────────────────────────────
from scripts.playground.agents.erp_forge import ERPForgeAgent
from scripts.playground.agents.industry_mimicker import IndustryMimickerAgent
from scripts.playground.agents.edge_case_forge import EdgeCaseForgeAgent

# ── Tier 3: Bootstrappers (resample / mutate / evolve) ──────────────────
from scripts.playground.agents.bootstrap_resampler import BootstrapResamplerAgent
from scripts.playground.agents.perturbation_engine import PerturbationEngineAgent
from scripts.playground.agents.time_warp_generator import TimeWarpGeneratorAgent

# ── Tier 4: Testers (continuous validation) ─────────────────────────────
from scripts.playground.agents.pipeline_smoker import PipelineSmokerAgent
from scripts.playground.agents.quality_auditor import QualityAuditorAgent

# Ordered list matching agent numbers 1-10
ALL_AGENTS = [
    PublicDataScoutAgent,       # 1
    RealCompanyHarvesterAgent,  # 2
    ERPForgeAgent,              # 3
    IndustryMimickerAgent,      # 4
    EdgeCaseForgeAgent,         # 5
    BootstrapResamplerAgent,    # 6
    PerturbationEngineAgent,    # 7
    TimeWarpGeneratorAgent,     # 8
    PipelineSmokerAgent,        # 9
    QualityAuditorAgent,        # 10
]

__all__ = [
    "PlaygroundAgent",
    "PlaygroundContext",
    "AgentResult",
    "DatasetRecord",
    "ALL_AGENTS",
    "PublicDataScoutAgent",
    "RealCompanyHarvesterAgent",
    "ERPForgeAgent",
    "IndustryMimickerAgent",
    "EdgeCaseForgeAgent",
    "BootstrapResamplerAgent",
    "PerturbationEngineAgent",
    "TimeWarpGeneratorAgent",
    "PipelineSmokerAgent",
    "QualityAuditorAgent",
]
