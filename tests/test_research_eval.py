import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "evals/research/run_eval.py"
    spec = importlib.util.spec_from_file_location("research_eval", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_research_dataset_is_twenty_cases_and_all_modes_make_sixty_rows():
    module = _module()
    cases = module.load_cases()
    module.validate(cases)
    rows = [
        module.deterministic_case(case, mode)
        for mode in module.PROFILES
        for case in cases
    ]
    assert len(rows) == 60
    assert module.gate(rows, cases) == []
    assert len(module.dataset_fingerprint(cases)) == 64


def test_live_baseline_comparison_rejects_cross_mode_and_token_regression(tmp_path):
    module = _module()
    cases = module.load_cases()
    fingerprint = module.dataset_fingerprint(cases)
    row = module.deterministic_case(cases[0], "standard")
    row.update(deterministic=False, total_tokens=100)
    baseline = {
        "level": "live",
        "dataset_fingerprint": fingerprint,
        "results": [row],
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    current = dict(baseline)
    current["results"] = [{**row, "total_tokens": 121}]
    assert "Token 回归" in "；".join(module.compare_baseline(current, baseline_path))

    current["results"] = [{**row, "mode": "quick"}]
    assert module.compare_baseline(current, baseline_path) == [
        "baseline 必须是同一 Research 模式的结果"
    ]


def test_live_fixture_uploads_markdown_as_supported_html_attachment(tmp_path):
    module = _module()

    filename, body, content_type = module.attachment_upload_payload(
        "mode_comparison_brief"
    )

    assert filename == "mode_comparison_brief.html"
    assert content_type == "text/html"
    assert body.startswith(b"\xef\xbb\xbf<!doctype html>")
    assert b"<pre>" in body

    uploaded = tmp_path / filename
    uploaded.write_bytes(body)
    from backend.indexing.html_processor import parse_html_file_to_sections

    text = "\n".join(item["text"] for item in parse_html_file_to_sections(uploaded))
    assert "受监管企业" in text
    assert "Agent 平台" in text
