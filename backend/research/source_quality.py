from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import urlparse

from backend.research.query_policy import objective_match


_PRIMARY_SUFFIXES = (".gov", ".gov.cn", ".edu", ".edu.cn", ".ac.cn")
_PRIMARY_HINTS = (
    "docs.",
    "developer.",
    "standards.",
    "arxiv.org",
    "doi.org",
    "github.com",
)


def _freshness(published: str | None, captured: datetime) -> tuple[float, str]:
    if not published:
        return 0.5, "来源未提供发布日期，使用中性时效分"
    try:
        parsed = (
            datetime.fromisoformat(published.replace("Z", "+00:00"))
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        age_days = max((captured - parsed).days, 0)
        return max(
            0.15, min(1.0, math.exp(-age_days / 1095))
        ), f"距抓取时间约 {age_days} 天"
    except (TypeError, ValueError):
        return 0.5, "发布日期无法解析，使用中性时效分"


def enrich_web_evidence(item: dict, *, objective: str) -> dict:
    captured = datetime.now(UTC).replace(tzinfo=None)
    uri = str(item.get("source_uri") or item.get("url") or "")
    host = (urlparse(uri).hostname or "").casefold()
    authority = (
        0.95
        if host.endswith(_PRIMARY_SUFFIXES)
        or any(value in host for value in _PRIMARY_HINTS)
        else 0.6
        if host
        else 0.3
    )
    freshness, freshness_reason = _freshness(item.get("published_date"), captured)
    relevance = max(0.0, min(1.0, float(item.get("relevance_score", 0.5))))
    match = objective_match(
        objective,
        title=str(item.get("title") or ""),
        locator=uri,
        content=str(item.get("content") or ""),
    )
    target = float(match.get("objective_relevance", 0.5))
    quality = relevance * 0.4 + authority * 0.25 + freshness * 0.15 + target * 0.2
    content = str(item.get("content") or "")
    return {
        **item,
        **match,
        "domain": host,
        "captured_at": captured,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "quality_score": round(quality, 4),
        "quality_reason": f"相关度、权威性、时效性和目标匹配综合；{freshness_reason}",
    }


def rank_web_evidence(
    items: list[dict], *, objective: str, limit: int, per_domain: int = 2
) -> list[dict]:
    enriched = [enrich_web_evidence(item, objective=objective) for item in items]
    enriched = [item for item in enriched if item.get("objective_match")]
    enriched.sort(
        key=lambda item: (
            bool(item.get("primary_source")),
            bool(item.get("direct_target_match")),
            float(item.get("quality_score", 0)),
        ),
        reverse=True,
    )
    counts: dict[str, int] = defaultdict(int)
    selected = []
    for item in enriched:
        domain = str(item.get("domain") or "unknown")
        if counts[domain] >= per_domain:
            continue
        counts[domain] += 1
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected
