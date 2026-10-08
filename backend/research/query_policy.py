from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


_GITHUB = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I
)
_SLUG = re.compile(r"(?<![\w.-])([A-Za-z0-9][\w.-]+)/([A-Za-z0-9][\w.-]+)(?![\w.-])")
_INSTRUCTIONS = re.compile(
    r"请|根据|围绕|关于|研究|比较|分析|评估|梳理|核验|说明|介绍|设计|方案|建议|"
    r"核心|关键|主要|哪些|什么|如何|是否|以及|进行|和|与|的|在|对|及"
)
_LATIN_STOPWORDS = {"github", "https", "http", "www", "compare", "research", "repo"}
_DIMENSIONS = {"成本", "效果", "性能", "优势", "限制", "风险", "建议", "方案"}
# Reviewed primary documentation entry points; unknown subjects use discovery.
_OFFICIAL_DOCUMENTATION = {
    "postgresql": "postgresql.org/docs",
    "pgvector": "github.com/pgvector/pgvector",
    "milvus": "milvus.io/docs",
    "qdrant": "qdrant.tech/documentation",
    "redis": "redis.io/docs",
    "rabbitmq": "rabbitmq.com/docs",
}
_SEARCH_DIMENSIONS = {
    "租户": "multitenancy isolation",
    "隔离": "multitenancy isolation",
    "混合": "hybrid search",
    "一致性": "consistency",
    "更新": "update upsert",
    "运维": "deployment operations",
    "扩展": "scaling",
    "持久化": "persistence fsync",
    "故障切换": "replication failover",
    "确认": "acknowledgements publisher confirms",
    "重试": "redelivery retry delivery count",
    "死信": "dead lettering",
    "长任务": "consumer timeout pending claim",
    "幂等": "idempotence duplicate delivery",
}


def objective_versions(objective: str) -> dict[str, str]:
    return {
        term: match[1]
        for term in _OFFICIAL_DOCUMENTATION
        if (match := re.search(rf"\b{term}\s+v?(\d+(?:\.\d+){{0,2}})", objective, re.I))
    }


def is_decision_step(title: str) -> bool:
    # The frozen plan's title owns the step intent; the objective appears in every question.
    return bool(
        re.search(
            r"横向比较|选型|综合(?:判断|结论|建议|评估)|cross[- ]?comparison|selection|recommendation|synthesis",
            title,
            re.I,
        )
    )


@dataclass(frozen=True, slots=True)
class ResearchTarget:
    kind: str
    key: str
    name: str
    primary_url: str


def resolve_research_targets(objective: str) -> list[ResearchTarget]:
    matches = list(_GITHUB.finditer(objective or ""))
    if not matches:
        if not any(
            word in (objective or "").casefold()
            for word in ("github", "仓库", "repo", "项目")
        ):
            return []
        matches = list(_SLUG.finditer(objective or ""))
    targets: dict[str, ResearchTarget] = {}
    for match in matches:
        owner, repository = match.groups()
        repository = repository.removesuffix(".git")
        key = f"{owner}/{repository}"
        targets[key.casefold()] = ResearchTarget(
            "github_repository", key, repository, f"https://github.com/{key}"
        )
    return list(targets.values())


def resolve_research_target(objective: str) -> ResearchTarget | None:
    targets = resolve_research_targets(objective)
    return targets[0] if targets else None


def objective_terms(objective: str) -> list[str]:
    """Bounded lexical anchors, including Chinese bigrams without a new tokenizer."""
    latin = {
        value.casefold()
        for value in re.findall(r"[A-Za-z][A-Za-z0-9_.+#-]{2,}", objective)
        if value.casefold() not in _LATIN_STOPWORDS
    }
    if latin:
        return sorted(latin)
    terms: set[str] = set()
    for phrase in re.findall(r"[\u4e00-\u9fff]+", objective):
        for word in _INSTRUCTIONS.split(phrase):
            terms.update(word[index : index + 2] for index in range(len(word) - 1))
    anchors = terms - _DIMENSIONS
    return sorted(anchors or terms)


def anchor_question(objective: str, question: str) -> str:
    targets = resolve_research_targets(objective)
    anchor = (
        "、".join(target.key for target in targets)
        if targets
        else " ".join((objective or "").split())[:500]
    )
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
    targets = resolve_research_targets(objective)
    if targets:
        anchors = " OR ".join(f'"{target.key}"' for target in targets)
        return f"({anchors}) {question}"[:1200]
    anchors = " ".join(objective_terms(objective)[:4])[:100]
    return f"{anchors} {_web_focus(objective, question)}"[:320]


def _web_focus(objective: str, question: str) -> str:
    # The planner's complete objective is useful for writing, but dilutes search.
    focus = question.rsplit("当前子问题：", 1)[-1].replace(objective, "")
    return " ".join(focus.split()).strip("：:。；，‘’“” ")[:180]


def build_web_queries(objective: str, question: str) -> list[str]:
    terms = objective_terms(objective)
    products = [term for term in terms if term in _OFFICIAL_DOCUMENTATION]
    terms = products or terms
    versions = objective_versions(objective)
    official = any(
        word in objective.casefold() for word in ("官方", "official", "primary source")
    )
    if (
        official
        and not resolve_research_targets(objective)
        and 1 <= len(terms) <= 4
        and all(re.search(r"[a-z]", term) for term in terms)
    ):
        focus = _web_focus(objective, question)
        for term in terms:
            focus = re.sub(re.escape(term), "", focus, flags=re.I)
        dimensions = list(
            dict.fromkeys(
                value for word, value in _SEARCH_DIMENSIONS.items() if word in focus
            )
        )
        search_focus = " ".join(dimensions)[:180] if dimensions else focus
        queries = []
        for term in terms:
            site = _OFFICIAL_DOCUMENTATION.get(term)
            dimension = search_focus
            if term == "pgvector":
                dimension = f"README {search_focus}"
            if term == "postgresql":
                if "multitenancy" in search_focus:
                    dimension = "row level security policies"
                if not re.search(r"postgresql\s+v?\d", objective, flags=re.I):
                    site = "postgresql.org/docs/current"
            if term == "rabbitmq" and term in versions:
                site = f"rabbitmq.com/docs/{versions[term]}"
            version = f" {versions[term]}" if term in versions else ""
            queries.append(
                f"{term}{version} {dimension} official documentation"[:240]
                + (f" site:{site}" if site else "")
            )
        return queries
    query = build_web_query(objective, question)
    return [f"{query} official documentation"[:360] if official else query]


def objective_match(
    objective: str, *, title: str = "", locator: str = "", content: str = ""
) -> dict:
    targets = resolve_research_targets(objective)
    combined = f"{title}\n{locator}\n{content}".casefold()
    if targets:
        parsed = urlparse(locator)
        host = (parsed.hostname or "").casefold()
        path = parsed.path.casefold().rstrip("/")
        matched_targets = []
        primary = False
        exact = False
        for target in targets:
            key = target.key.casefold()
            official = host in {
                "github.com",
                "www.github.com",
                "raw.githubusercontent.com",
            } and (path == f"/{key}" or path.startswith(f"/{key}/"))
            direct = official or bool(
                re.search(rf"(?<![\w/.-]){re.escape(key)}(?![\w.-])", combined)
            )
            named = bool(
                re.search(
                    rf"(?<![\w.-]){re.escape(target.name.casefold())}(?![\w.-])",
                    combined,
                )
            )
            if direct or named:
                matched_targets.append(target.key)
                primary = primary or official
                exact = exact or direct
        return {
            "objective_match": bool(matched_targets),
            "direct_target_match": exact,
            "primary_source": primary,
            "objective_relevance": 1.0 if exact else 0.85 if matched_targets else 0.0,
            "objective_policy_applied": True,
            "target_key": matched_targets[0] if matched_targets else targets[0].key,
            "matched_target_keys": matched_targets,
        }
    terms = objective_terms(objective or "")
    if not terms:
        return {
            "objective_match": True,
            "objective_relevance": 0.5,
            "objective_policy_applied": False,
        }
    matched = [term for term in terms if term in combined]
    score = len(matched) / len(terms)
    chinese = all(re.fullmatch(r"[\u4e00-\u9fff]+", term) for term in terms)
    return {
        "objective_match": bool(matched) and score >= 0.1 if chinese else bool(matched),
        "direct_target_match": False,
        "primary_source": _official_documentation_source(terms, locator),
        "objective_relevance": round(score, 4),
        "objective_policy_applied": True,
        "matched_objective_terms": matched,
    }


def _official_documentation_source(terms: list[str], locator: str) -> bool:
    parsed = urlparse(locator)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.rstrip("/")
    for term in terms:
        site = _OFFICIAL_DOCUMENTATION.get(term)
        if not site:
            continue
        domain, prefix = site.split("/", 1)
        root = f"/{prefix}"
        if host != domain:
            continue
        if domain == "github.com":
            if path == root or path == f"{root}/blob/master/README.md":
                return True
        elif path == root or path.startswith(f"{root}/"):
            return True
    return False


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
