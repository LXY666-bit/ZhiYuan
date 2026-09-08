"""Display recommendations never own, aggregate, or rewrite query values."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from backend.dataqa.contracts import DataQaChartSuggestion, DataQaChartV1

_NUMBER = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T.*)?$")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and not _NUMBER.fullmatch(value):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and abs(number) <= 2**53 - 1 else None


def _date(value: Any) -> bool:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def chart_fields(
    columns: list[str], rows: list[list[Any]]
) -> tuple[list[str], list[str], list[str]]:
    if (
        len(set(columns)) != len(columns)
        or not 2 <= len(rows) <= 60
        or any(len(row) != len(columns) for row in rows)
    ):
        return [], [], []
    dimensions, metrics, dates = [], [], []
    for index, name in enumerate(columns):
        values = [row[index] for row in rows]
        if all(_number(value) is not None for value in values):
            metrics.append(name)
        if all(_date(value) for value in values):
            dates.append(name)
        if all(
            isinstance(value, (str, int, float))
            and not isinstance(value, bool)
            and str(value).strip()
            and (not isinstance(value, float) or math.isfinite(value))
            for value in values
        ) and len({str(value) for value in values}) == len(rows):
            dimensions.append(name)
    return dimensions, metrics, dates


def infer_chart(
    columns: list[str], rows: list[list[Any]], proposal: Any = None
) -> dict[str, Any]:
    dimensions, metrics, dates = chart_fields(columns, rows)
    chart = DataQaChartV1()
    labels = sorted(dimensions, key=lambda name: (name not in dates, name in metrics))
    for label in labels:
        value = next((name for name in metrics if name != label), None)
        if value:
            chart = DataQaChartV1(
                chart_type="line" if label in dates else "bar",
                label_field=label,
                value_field=value,
            )
            break
    if proposal is None:
        return chart.model_dump()
    try:
        suggestion = DataQaChartSuggestion.model_validate(proposal)
        valid = (
            suggestion.label_field in dimensions
            and suggestion.value_field in metrics
            and suggestion.label_field != suggestion.value_field
        )
        if suggestion.chart_type == "line":
            valid = valid and suggestion.label_field in dates
        if valid and suggestion.chart_type == "pie":
            index = columns.index(suggestion.value_field)
            values = [float(row[index]) for row in rows]
            valid = (
                len(rows) <= 12
                and all(value >= 0 for value in values)
                and sum(values) > 0
            )
        if not valid:
            raise ValueError("Invalid display mapping")
    except (ValidationError, ValueError):
        chart.recommendation_error = "DATAQA_CHART_SUGGESTION_REJECTED"
        return chart.model_dump()
    return DataQaChartV1(**suggestion.model_dump(), source="llm").model_dump()
