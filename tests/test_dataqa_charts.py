from copy import deepcopy

import pytest

from backend.dataqa.charts import infer_chart
from backend.dataqa.contracts import DataQaGroundedSqlDecision, DataQaResultV1


def test_multiple_metrics_default_to_first_and_accept_valid_llm_mapping():
    columns = ["region", "sales", "orders"]
    rows = [["East", "1234.50", 5], ["West", "987.00", 3]]
    original = deepcopy(rows)
    assert infer_chart(columns, rows)["value_field"] == "sales"
    suggestion = {
        "chart_type": "bar",
        "label_field": "region",
        "value_field": "orders",
        "title": "Order count",
    }
    chart = infer_chart(columns, rows, suggestion)
    assert chart["source"] == "llm"
    assert chart["value_field"] == "orders"
    assert rows == original
    assert (
        DataQaResultV1(columns=columns, rows=rows, chart=chart).chart.title
        == "Order count"
    )


def test_dates_default_to_line_without_reordering_original_rows():
    rows = [["2026-03-01", 3], ["2026-01-01", 1]]
    assert infer_chart(["month", "sales"], rows)["chart_type"] == "line"
    assert rows[0][0] == "2026-03-01"


@pytest.mark.parametrize(
    "proposal",
    [
        [],
        "<script>bad()</script>",
        {},
        {"chart_type": "bar", "label_field": "missing", "value_field": "sales"},
        {"chart_type": "line", "label_field": "region", "value_field": "sales"},
        {"chart_type": "pie", "label_field": "region", "value_field": "sales"},
        {
            "chart_type": "bar",
            "label_field": "region",
            "value_field": "sales",
            "rows": [["fake", 99]],
        },
    ],
)
def test_bad_suggestions_fall_back_without_changing_data(proposal):
    decision = DataQaGroundedSqlDecision(sql="SELECT 1", chart=proposal)
    rows = [["East", -1], ["West", 2]]
    chart = infer_chart(["region", "sales"], rows, decision.chart)
    assert chart["chart_type"] == "bar"
    assert chart["source"] == "rules"
    assert chart["recommendation_error"] == "DATAQA_CHART_SUGGESTION_REJECTED"
    assert rows == [["East", -1], ["West", 2]]


@pytest.mark.parametrize(
    "rows",
    [
        [["East", None], ["West", 2]],
        [["East", 1], ["East", 2]],
        [["East", True], ["West", False]],
        [["East", "NaN"], ["West", 2]],
        [["East", "9007199254740993"], ["West", 2]],
        [["East"], ["West", 2]],
    ],
)
def test_invalid_shapes_are_not_silently_filtered_or_aggregated(rows):
    assert infer_chart(["region", "sales"], rows)["chart_type"] == "none"
