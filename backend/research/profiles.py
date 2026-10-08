from __future__ import annotations

from copy import deepcopy


PROFILE_VERSION = 8
WORKFLOW_VERSION = "research-workflow-v5"
PROMPT_VERSION = "research-prompts-v5"
_PROFILES = {
    "quick": {
        "label": "快速",
        "min_steps": 2,
        "max_steps": 3,
        "results_per_source": 3,
        "max_evidence": 12,
        "max_rounds": 1,
        "max_gaps": 0,
        "model_timeout_seconds": 45,
        "writing_budget_seconds": 60,
        "run_budget_seconds": 90,
        "retrieval_budget_seconds": 25,
        "source_timeout_seconds": 20,
        "review_timeout_seconds": 20,
        "synthesis_timeout_seconds": 20,
        "section_length_hint": 600,
        "section_evidence_limit": 5,
        "section_concurrency": 3,
        "max_revisions": 0,
    },
    "standard": {
        "label": "标准",
        "min_steps": 3,
        "max_steps": 5,
        "results_per_source": 5,
        "max_evidence": 30,
        "max_rounds": 2,
        "max_gaps": 2,
        "model_timeout_seconds": 60,
        "writing_budget_seconds": 120,
        "run_budget_seconds": 180,
        "retrieval_budget_seconds": 45,
        "source_timeout_seconds": 25,
        "review_timeout_seconds": 30,
        "gap_timeout_seconds": 15,
        "synthesis_timeout_seconds": 30,
        "section_length_hint": 1000,
        "section_evidence_limit": 8,
        "section_concurrency": 5,
        "max_revisions": 1,
    },
    "deep": {
        "label": "深度",
        "min_steps": 4,
        "max_steps": 6,
        "results_per_source": 8,
        "max_evidence": 50,
        "max_rounds": 2,
        "max_gaps": 3,
        "model_timeout_seconds": 90,
        "writing_budget_seconds": 180,
        "run_budget_seconds": 300,
        "retrieval_budget_seconds": 60,
        "source_timeout_seconds": 30,
        "review_timeout_seconds": 40,
        "gap_timeout_seconds": 20,
        "synthesis_timeout_seconds": 45,
        "section_length_hint": 1500,
        "section_evidence_limit": 10,
        "section_concurrency": 6,
        "max_revisions": 1,
    },
}


def resolve_research_profile(mode: str) -> dict:
    if mode not in _PROFILES:
        raise ValueError(f"unsupported research mode: {mode}")
    result = deepcopy(_PROFILES[mode])
    result.update(
        {
            "mode": mode,
            "profile_version": PROFILE_VERSION,
            "model_max_tokens": {"quick": 1600, "standard": 2400, "deep": 3200}[mode],
            "review_max_tokens": 1000,
            "gap_max_tokens": 500,
            "synthesis_max_tokens": 1600,
            "disable_thinking": True,
            "reuse_prior_evidence": True,
            "verify_synthesis": True,
        }
    )
    return result
