from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.core.errors import AppError
from backend.dataqa.selector import select_candidates
from backend.dataqa.semantic_schema import build_semantic_schema, normalize_aliases


def _schema():
    tables = [
        {
            "schema": "public",
            "name": "orders",
            "columns": [
                {"name": "pay_amt", "data_type": "numeric", "sensitive": False},
                {"name": "pay_time", "data_type": "timestamp", "sensitive": False},
                {"name": "uid", "data_type": "text", "sensitive": True},
            ],
        },
        {
            "schema": "public",
            "name": "regions",
            "columns": [
                {"name": "region_name", "data_type": "text", "sensitive": False},
                {"name": "region_code", "data_type": "text", "sensitive": False},
            ],
        },
    ]
    metadata = [
        SimpleNamespace(
            schema_name="public",
            table_name="orders",
            column_name="",
            description="支付订单事实表",
            aliases_json=["销售订单"],
        ),
        SimpleNamespace(
            schema_name="public",
            table_name="orders",
            column_name="pay_amt",
            description="订单实际支付金额",
            aliases_json=["销售额", "成交金额", "支付金额"],
        ),
        SimpleNamespace(
            schema_name="public",
            table_name="orders",
            column_name="pay_time",
            description="支付完成时间",
            aliases_json=["今年"],
        ),
        SimpleNamespace(
            schema_name="public",
            table_name="regions",
            column_name="region_name",
            description="销售区域名称",
            aliases_json=["地区", "区域"],
        ),
    ]
    return build_semantic_schema(tables, metadata)


def test_selector_uses_semantics_and_omits_sensitive_columns():
    selection = select_candidates("统计今年各地区销售额", _schema())
    assert selection.relation_scope == ("public.orders", "public.regions")
    orders = selection.relations[0]
    assert {column.name for column in orders.columns} == {"pay_amt", "pay_time"}
    assert "uid" not in selection.prompt_schema(budget=12_000)
    assert selection.result_tables()[0]["name"] == "public.orders"


def test_selection_snapshot_is_stable_and_round_trips():
    selection = select_candidates("统计今年各地区销售额", _schema())
    restored = type(selection).from_snapshot(selection.snapshot())
    assert restored == selection


def test_compact_schema_is_bounded_without_dropping_candidate_scope():
    selection = select_candidates("统计今年各地区销售额", _schema())
    prompt = selection.prompt_schema(budget=180)
    assert len(prompt) <= 180
    assert selection.relation_scope == ("public.orders", "public.regions")


def test_zero_match_returns_no_candidate_instead_of_random_relation():
    assert select_candidates("完全无关的问题", _schema()).relations == ()


def test_alias_validation_rejects_control_characters():
    with pytest.raises(AppError):
        normalize_aliases(["销售\n额"])
