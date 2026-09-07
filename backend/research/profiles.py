from __future__ import annotations

from copy import deepcopy


PROFILE_VERSION = 5
_PROFILES = {
    "quick": {
        "label": "快速",
        "min_steps": 2,
        "max_steps": 3,
        "results_per_source": 3,
        "max_evidence": 12,
        "max_rounds": 1,
        "max_gaps": 0,
        "model_timeout_seconds": 180,
        "writing_budget_seconds": 360,
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
        "model_timeout_seconds": 360,
        "writing_budget_seconds": 600,
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
        "model_timeout_seconds": 720,
        "writing_budget_seconds": 1200,
        "section_evidence_limit": 10,
        "section_concurrency": 6,
        "max_revisions": 1,
    },
}


def resolve_research_profile(mode: str) -> dict:
    if mode not in _PROFILES:
        raise ValueError(f"unsupported research mode: {mode}")
    result = deepcopy(_PROFILES[mode])
    result.update({"mode": mode, "profile_version": PROFILE_VERSION})
    return result
