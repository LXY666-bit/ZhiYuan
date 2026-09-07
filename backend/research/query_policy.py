from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


_GITHUB = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I
)
_SLUG = re.compile(r"(?<![\w.-])([A-Za-z0-9][\w.-]+)/([A-Za-z0-9][\w.-]+)(?![\w.-])")


@dataclass(frozen=True, slots=True)
class ResearchTarget:
    kind: str
    key: str
    name: str
    primary_url: str


def resolve_research_target(objective: str) -> ResearchTarget | None:
    match = _GITHUB.search(objective or "")
    if match is None:
        match = _SLUG.search(objective or "")
        if match is None or not any(
            word in (objective or "").casefold()
            for word in ("github", "仓库", "repo", "项目")
        ):
            return None
    owner, repository = match.groups()
    repository = repository.removesuffix(".git")
    key = f"{owner}/{repository}"
    return ResearchTarget(
        "github_repository", key, repository, f"https://github.com/{key}"
    )


def anchor_question(objective: str, question: str) -> str:
    target = resolve_research_target(objective)
    anchor = target.key if target else " ".join((objective or "").split())[:500]
    anchored = (
        question
        if anchor.casefold() in question.casefold()
        else f"原始研究目标是“{anchor}”。当前子问题：{question}"
    )
    return anchored[:2000]


def focus_question(objective: str, title: str, question: str) -> str:
    """Keep every retrieval question anchored to both its objective and step focus."""
    normalized_title = " ".join((title or "").split())
    normalized_question = " ".join((question or objective or "").split())
    if normalized_title and not normalized_question.casefold().startswith(
        normalized_title.casefold()
    ):
        normalized_question = f"{normalized_title}：{normalized_question}"
    return anchor_question(objective, normalized_question)


def build_web_query(objective: str, question: str) -> str:
    target = resolve_research_target(objective)
    if target:
        return f'"{target.key}" "{target.name}" {question}'[:1200]
    normalized_objective = " ".join(objective.split())[:500]
    normalized_question = " ".join(question.split())
    if normalized_objective.casefold() in normalized_question.casefold():
        return normalized_question[:1200]
    return f"{normalized_objective} {normalized_question}"[:1200]


def objective_match(
    objective: str, *, title: str = "", locator: str = "", content: str = ""
) -> dict:
    target = resolve_research_target(objective)
    combined = f"{title}\n{locator}\n{content}".casefold()
    if target:
        parsed = urlparse(locator)
        host = (parsed.hostname or "").casefold()
        path = parsed.path.casefold().rstrip("/")
        key = target.key.casefold()
        primary = host in {
            "github.com",
            "www.github.com",
            "raw.githubusercontent.com",
        } and path.startswith(f"/{key}")
        exact = primary or key in combined
        named = target.name.casefold() in combined
        return {
            "objective_match": exact or named,
            "direct_target_match": exact,
            "primary_source": primary,
            "objective_relevance": 1.0 if exact else 0.85 if named else 0.0,
            "objective_policy_applied": True,
            "target_key": target.key,
        }
    terms = [
        value.casefold()
        for value in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+#-]{2,}", objective or "")
        if not value.isdigit()
    ]
    if not terms:
        return {
            "objective_match": True,
            "objective_relevance": 0.5,
            "objective_policy_applied": False,
        }
    matched = [term for term in terms if term in combined]
    score = len(matched) / len(terms)
    return {
        "objective_match": bool(matched),
        "direct_target_match": False,
        "primary_source": False,
        "objective_relevance": round(score, 4),
        "objective_policy_applied": True,
        "matched_objective_terms": matched,
    }


def filter_objective_evidence(
    raw: list[dict], objective: str
) -> tuple[list[dict], int]:
    kept = []
    for item in raw:
        match = objective_match(
            objective,
            title=str(item.get("title") or ""),
            locator=str(item.get("source_uri") or item.get("locator") or ""),
            content=str(item.get("content") or ""),
        )
        if match["objective_match"]:
            kept.append(
                {**item, "metadata": {**dict(item.get("metadata") or {}), **match}}
            )
    return kept, len(raw) - len(kept)
