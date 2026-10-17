from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import urlparse

from backend.research.query_policy import (
    objective_match,
    objective_versions,
    official_source_domains,
)


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
    captured = item.get("captured_at") or datetime.now(UTC).replace(tzinfo=None)
    uri = str(item.get("source_uri") or item.get("url") or "")
    host = (urlparse(uri).hostname or "").casefold()
    authority = (
        0.95
        if host.endswith(_PRIMARY_SUFFIXES)
        or any(
            host.startswith(value)
            if value.endswith(".")
            else host == value or host.endswith(f".{value}")
            for value in _PRIMARY_HINTS
        )
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
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    documentation = bool(
        re.search(r"/(?:docs?|documentation|manual)(?:/|$)", urlparse(uri).path)
    ) or host.startswith(("docs.", "developer."))
    version = re.search(
        r"/(?:docs?|documentation|manual)/(?:[a-z]{2}(?:-[a-z]{2})?/)?v?(\d+(?:\.\d+){0,2})(?:\.x)?(?:/|$)",
        urlparse(uri).path,
    )
    source_version = version[1] if version else None
    if not source_version and host == "docs.postgresql.tw":
        path_version = re.match(r"/(\d+(?:\.\d+){0,2})/", urlparse(uri).path)
        source_version = path_version[1] if path_version else None
    if not source_version and "postgresql" in str(item.get("title") or "").casefold():
        title_version = re.search(
            r"Documentation:\s*(\d+(?:\.\d+){0,2})(?=\s|:|$)",
            str(item.get("title") or ""),
            re.I,
        )
        source_version = title_version[1] if title_version else None
    if not source_version:
        header_version = re.search(
            r"(?:^|#\s*)(Redis|RabbitMQ)\s+(\d+(?:\.\d+){0,2})(?:\s|$)",
            f"{item.get('title', '')}\n{content[:1000]}",
            re.I | re.M,
        )
        source_version = header_version[2] if header_version else None
    version_hint = source_version or "未标明（不能推定为最新版本）"
    scope = "unknown"
    notes = []
    for product, expected in objective_versions(objective).items():
        if product not in f"{host} {item.get('title', '')} {content}".casefold():
            continue
        if product == "redis" and re.search(r"/operate/(?:rs|rc)/", uri):
            scope = "mismatch"
            notes.append(
                "产品不匹配：Redis Software/Cloud 资料不能直接证明 Redis 开源版行为。"
            )
        elif source_version and product in host:
            if source_version == expected or source_version.startswith(expected + "."):
                if scope != "mismatch":
                    scope = "matched"
            else:
                scope = "mismatch"
                notes.append(
                    f"版本不匹配：来源 {source_version}，目标 {product} {expected}。"
                )
    feature_hints = [
        line.strip()[:400]
        for line in content.splitlines()
        if re.search(
            r"(?:since|added|introduced|starting with|新增|引入).*\d+\.\d+", line, re.I
        )
    ][:4]
    if feature_hints:
        notes.append("新增特性必须逐项核对版本：" + "；".join(feature_hints))
    # An entry point or empty code fence is evidence of a documentation location,
    # not of the persistence/acknowledgement mechanisms linked from that page.
    substantive = bool(content.strip().strip("` .[]\n")) and not bool(
        re.search(
            r"documentation is versioned.*table of contents", content, re.I | re.S
        )
    )
    return {
        **item,
        **match,
        "domain": host,
        "captured_at": captured,
        "content_hash": digest,
        "stable_key": item.get("stable_key")
        or hashlib.sha256(f"{uri}\n{digest}".encode()).hexdigest(),
        "documentation_candidate": documentation,
        "version_hint": version_hint,
        "version_scope": scope,
        "substantive": substantive,
        "metadata": {
            **dict(item.get("metadata") or {}),
            **match,
            "documentation_candidate": documentation,
            "version_hint": version_hint,
            "version_scope": scope,
            "scope_note": "；".join(notes)
            or "需逐条核对适用产品、版本和前提，URL 不能证明行为。",
            "substantive": substantive,
        },
        "quality_score": round(quality, 4),
        "quality_reason": f"相关度、权威性、时效性和目标匹配综合；{freshness_reason}",
    }


def rank_web_evidence(
    items: list[dict], *, objective: str, limit: int, per_domain: int | None = None
) -> list[dict]:
    enriched = [enrich_web_evidence(item, objective=objective) for item in items]
    enriched = [item for item in enriched if item.get("objective_match")]
    if official_source_domains(objective):
        enriched = [item for item in enriched if item.get("primary_source")]
    # Preserve different snapshots, including conflicts, while reusing identical ones.
    enriched = list(
        {
            (item.get("source_uri"), item["content_hash"]): item for item in enriched
        }.values()
    )
    enriched.sort(
        key=lambda item: (
            item.get("version_scope") != "mismatch",
            bool(item.get("substantive")),
            bool(item.get("primary_source")),
            item.get("version_scope") == "matched",
            bool(item.get("documentation_candidate")),
            bool(item.get("direct_target_match")),
            float(item.get("quality_score", 0)),
        ),
        reverse=True,
    )
    counts: dict[str, int] = defaultdict(int)
    selected = []
    for item in enriched:
        domain = str(item.get("domain") or "unknown")
        domain_limit = (
            per_domain
            if per_domain is not None
            else 4
            if item.get("primary_source")
            else 2
        )
        if counts[domain] >= domain_limit:
            continue
        counts[domain] += 1
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected
