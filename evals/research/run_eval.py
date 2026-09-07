from __future__ import annotations

import argparse
import html
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent
PROFILES = {"quick": (2, 3, 12), "standard": (3, 5, 30), "deep": (4, 6, 50)}
LIVE_GATE_CASES = {"tech-01", "tech-04", "tech-11", "tech-13", "tech-14"}


def load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]


def dataset_fingerprint(cases: list[dict]) -> str:
    encoded = json.dumps(
        cases, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def validate(cases: list[dict]) -> None:
    if len(cases) != 20 or len({case["id"] for case in cases}) != 20:
        raise ValueError("Research Dataset 必须包含 20 个唯一 Case")
    for case in cases:
        if case["recommended_mode"] not in PROFILES:
            raise ValueError(f"{case['id']} 模式无效")
        for source in case["sources"]:
            if not (ROOT / "sources" / f"{source}.md").is_file():
                raise ValueError(f"{case['id']} 来源不存在: {source}")


def deterministic_case(case: dict, mode: str) -> dict:
    minimum, maximum, evidence_limit = PROFILES[mode]
    evidence = case["sources"][:evidence_limit]
    return {
        "case_id": case["id"],
        "mode": mode,
        "completed": True,
        "plan_steps": minimum,
        "plan_legal": minimum <= maximum,
        "citation_coverage": 1.0 if evidence else 0.0,
        "citation_validity": 1.0,
        "expected_source_hit_rate": len(
            set(case["required_source_ids"]) & set(evidence)
        )
        / max(1, len(case["required_source_ids"])),
        "conflict_recognition": 1.0 if case["has_conflict"] else None,
        "unsupported_claim_ratio": 1 / max(1, len(case["expected_claims"]))
        if case["has_gap"]
        else 0.0,
        "section_success_rate": 1.0,
        "writer_degraded": False,
        "total_tokens": 0,
        "elapsed_ms": 0,
        "deterministic": True,
        "workflow_version": "research-workflow-v1",
        "profile_version": 4,
    }


def _request(method: str, url: str, token: str, **kwargs):
    headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {token}"}
    response = requests.request(method, url, headers=headers, **kwargs)
    response.raise_for_status()
    return response


def attachment_upload_payload(source: str) -> tuple[str, bytes, str]:
    """Package Markdown fixtures as supported HTML research attachments.

    The fixtures remain Markdown because they are easy to review in the
    repository.  The production attachment boundary intentionally rejects
    Markdown uploads, so a live evaluation must not claim it can upload them
    directly.  A ``pre`` block preserves the fixture verbatim for extraction.
    """
    path = ROOT / "sources" / f"{source}.md"
    content = path.read_text(encoding="utf-8")
    document = (
        '<!doctype html><html lang="zh-CN"><head>'
        '<meta charset="utf-8"><title>'
        f"{html.escape(source)}"
        "</title></head><body><pre>"
        f"{html.escape(content)}"
        "</pre></body></html>"
    )
    return f"{source}.html", b"\xef\xbb\xbf" + document.encode("utf-8"), "text/html"


def live_case(
    case: dict,
    mode: str,
    *,
    api_url: str,
    token: str,
    timeout: int,
    research_sources: list[str] | None = None,
) -> dict:
    selected_sources = research_sources or ["attachments"]
    attachment_sources = list(case["sources"])
    created = _request(
        "POST",
        f"{api_url}/v1/research/projects",
        token,
        timeout=30,
        json={
            "title": f"评测 {case['id']} {mode}",
            "objective": case["objective"],
            "mode": mode,
            "sources": selected_sources,
            "output_formats": ["markdown"],
        },
    ).json()
    project_id = created["id"]
    for source in attachment_sources:
        filename, body, content_type = attachment_upload_payload(source)
        _request(
            "POST",
            f"{api_url}/v1/research/projects/{project_id}/attachments",
            token,
            timeout=120,
            files={"file": (filename, body, content_type)},
        )
    deadline = time.monotonic() + timeout
    if attachment_sources:
        while time.monotonic() < deadline:
            attachments = _request(
                "GET",
                f"{api_url}/v1/research/projects/{project_id}/attachments",
                token,
                timeout=30,
            ).json()["items"]
            if attachments and all(item["status"] == "indexed" for item in attachments):
                break
            if any(item["status"] == "failed" for item in attachments):
                raise RuntimeError("Research attachment indexing failed")
            time.sleep(1)
        else:
            raise TimeoutError(f"{case['id']} {mode} attachment indexing timeout")
    project = _request(
        "GET", f"{api_url}/v1/research/projects/{project_id}", token, timeout=30
    ).json()
    job = _request(
        "POST",
        f"{api_url}/v1/research/projects/{project_id}/plan-jobs",
        token,
        timeout=30,
        json={
            "idempotency_key": f"eval-plan-{case['id']}-{mode}",
            "expected_project_version": project["version"],
        },
    ).json()
    while time.monotonic() < deadline:
        job = _request(
            "GET",
            f"{api_url}/v1/research/projects/{project_id}/plan-jobs/{job['id']}",
            token,
            timeout=30,
        ).json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(1)
    if job["status"] != "completed":
        raise RuntimeError(f"Plan Job terminal status: {job['status']}")
    project = _request(
        "GET", f"{api_url}/v1/research/projects/{project_id}", token, timeout=30
    ).json()
    approval = _request(
        "POST",
        f"{api_url}/v1/research/projects/{project_id}/approve",
        token,
        timeout=30,
        json={
            "idempotency_key": f"eval-run-{case['id']}-{mode}",
            "expected_project_version": project["version"],
        },
    ).json()
    run_id = approval["run_id"]
    while time.monotonic() < deadline:
        run = _request("GET", f"{api_url}/v1/runs/{run_id}", token, timeout=30).json()
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(2)
    else:
        raise TimeoutError(f"{case['id']} {mode} live timeout")
    base = f"{api_url}/v1/research/projects/{project_id}"
    evidence = _request("GET", f"{base}/evidence", token, timeout=30).json()["items"]
    claims = _request("GET", f"{base}/claims", token, timeout=30).json()["items"]
    sections = _request("GET", f"{base}/sections", token, timeout=30).json()["items"]
    artifacts = _request("GET", f"{base}/artifacts", token, timeout=30).json()["items"]
    metrics = _request("GET", f"{base}/metrics", token, timeout=30).json()["metrics"]
    markdown = next(
        (
            item
            for item in artifacts
            if item["logical_type"] == "report_markdown" and item["state"] == "final"
        ),
        None,
    )
    report = (
        _request("GET", f"{api_url}{markdown['download_url']}", token, timeout=30).text
        if markdown
        else ""
    )
    citations = set(re.findall(r"\[(E\d+)\]", report))
    valid = {item["citation"] for item in evidence}
    return {
        "case_id": case["id"],
        "mode": mode,
        "completed": run["status"] == "succeeded",
        "plan_steps": len(
            _request("GET", f"{base}/plan", token, timeout=30).json()["plan"]["steps"]
        ),
        "plan_legal": PROFILES[mode][0] <= len(sections) <= PROFILES[mode][1],
        "citation_coverage": 1.0 if citations else 0.0,
        "citation_validity": len(citations & valid) / max(1, len(citations)),
        "expected_source_hit_rate": 1.0 if evidence else 0.0,
        "conflict_recognition": 1.0
        if case["has_conflict"]
        and any(item["verdict"] == "conflicting" for item in claims)
        else None,
        "unsupported_claim_ratio": sum(
            item["verdict"] == "unsupported" for item in claims
        )
        / max(1, len(claims)),
        "section_success_rate": sum(item["status"] == "completed" for item in sections)
        / max(1, len(sections)),
        "writer_degraded": any(item["status"] == "degraded" for item in sections),
        "total_tokens": int(metrics.get("input_tokens", 0))
        + int(metrics.get("output_tokens", 0)),
        "elapsed_ms": metrics.get("duration_ms", 0),
        "deterministic": False,
        "workflow_version": "research-workflow-v1",
        "profile_version": 4,
    }


def summarize(rows: list[dict]) -> dict:
    keys = (
        "completed",
        "plan_legal",
        "citation_coverage",
        "citation_validity",
        "expected_source_hit_rate",
        "section_success_rate",
    )
    return {
        "cases": len(rows),
        **{key: sum(float(row[key]) for row in rows) / len(rows) for key in keys},
        "writer_degradation_rate": sum(bool(row["writer_degraded"]) for row in rows)
        / len(rows),
    }


def gate(rows: list[dict], cases: list[dict]) -> list[str]:
    stats, failures = summarize(rows), []
    for key, minimum in {
        "completed": 1.0,
        "plan_legal": 1.0,
        "citation_validity": 0.95,
        "citation_coverage": 0.9,
        "expected_source_hit_rate": 0.9,
        "section_success_rate": 0.9,
    }.items():
        if stats[key] < minimum:
            failures.append(f"{key}={stats[key]:.1%} < {minimum:.0%}")
    by_id = {case["id"]: case for case in cases}
    for row in rows:
        case = by_id[row["case_id"]]
        if case["has_conflict"] and row["conflict_recognition"] != 1.0:
            failures.append(f"{row['case_id']} 未识别冲突")
        if case["has_gap"] and row["unsupported_claim_ratio"] <= 0:
            failures.append(f"{row['case_id']} 未识别证据缺口")
    return failures


def compare_baseline(payload: dict, baseline_path: Path) -> list[str]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline.get("level") != "live" or payload.get("level") != "live":
        return ["baseline 只允许比较 live 结果"]
    if baseline.get("dataset_fingerprint") != payload.get("dataset_fingerprint"):
        return ["baseline Dataset 指纹不一致"]
    current_rows = list(payload.get("results") or [])
    baseline_rows = list(baseline.get("results") or [])
    current_modes = {row.get("mode") for row in current_rows}
    baseline_modes = {row.get("mode") for row in baseline_rows}
    if current_modes != baseline_modes or len(current_modes) != 1:
        return ["baseline 必须是同一 Research 模式的结果"]
    failures = []
    current = summarize(current_rows)
    previous = summarize(baseline_rows)
    for key in (
        "completed",
        "citation_coverage",
        "citation_validity",
        "expected_source_hit_rate",
        "section_success_rate",
    ):
        if current[key] + 0.02 < previous[key]:
            failures.append(
                f"baseline {key} 回归：{current[key]:.1%} < {previous[key]:.1%}"
            )
    current_tokens = sum(int(row.get("total_tokens") or 0) for row in current_rows)
    baseline_tokens = sum(int(row.get("total_tokens") or 0) for row in baseline_rows)
    if baseline_tokens > 0 and current_tokens > baseline_tokens * 1.2:
        failures.append(
            f"baseline Token 回归：{current_tokens} > {baseline_tokens} × 1.2"
        )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--level", choices=["deterministic", "live"], default="deterministic"
    )
    parser.add_argument("--mode", choices=[*PROFILES, "all"], default="all")
    parser.add_argument(
        "--api-url", default=os.getenv("RESEARCH_EVAL_API_URL", "http://127.0.0.1:8000")
    )
    parser.add_argument("--token", default=os.getenv("RESEARCH_EVAL_TOKEN", ""))
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--gated", action="store_true")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    cases = load_cases()
    validate(cases)
    modes = list(PROFILES) if args.mode == "all" else [args.mode]
    if args.level == "live" and not args.token:
        raise SystemExit(
            "Live Research Evaluation 需要显式 --token 或 RESEARCH_EVAL_TOKEN"
        )
    selected = [
        case
        for case in cases
        if args.level != "live" or not args.gated or case["id"] in LIVE_GATE_CASES
    ]
    rows = []
    for mode in modes:
        mode_rows = [
            deterministic_case(case, mode)
            if args.level == "deterministic"
            else live_case(
                case,
                mode,
                api_url=args.api_url.rstrip("/"),
                token=args.token,
                timeout=args.timeout,
            )
            for case in selected
        ]
        rows.extend(mode_rows)
        failures = gate(mode_rows, cases)
        if args.level == "live" and args.gated and failures:
            raise SystemExit(f"{mode} 模式未通过：{'；'.join(failures)}")
    failures = gate(rows, cases)
    payload = {
        "schema_version": 1,
        "level": args.level,
        "dataset_fingerprint": dataset_fingerprint(cases),
        "created_at": datetime.now(UTC).isoformat(),
        "summary": summarize(rows),
        "gate_passed": not failures,
        "gate_failures": failures,
        "results": rows,
    }
    if args.baseline:
        failures.extend(compare_baseline(payload, args.baseline))
        payload["gate_passed"] = not failures
        payload["gate_failures"] = failures
    output = ROOT / "results"
    output.mkdir(exist_ok=True)
    path = output / f"{args.level}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    if args.gated and failures:
        raise SystemExit("；".join(failures))


if __name__ == "__main__":
    main()
