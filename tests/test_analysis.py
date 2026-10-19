"""Tests for the statistical helpers and the SQL query loader."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eloscope.analyze import add_rate_columns, cramers_v, mean_abs_calibration_error, wilson_interval
from eloscope.model import load_named_queries


def test_wilson_interval_known_value() -> None:
    # 50 successes out of 100: Wilson 95 % interval is [0.4038, 0.5962]
    low, high = wilson_interval([50], [100])
    assert low[0] == pytest.approx(0.4038, abs=1e-4)
    assert high[0] == pytest.approx(0.5962, abs=1e-4)


def test_wilson_interval_stays_in_bounds() -> None:
    low, high = wilson_interval([0, 10], [10, 10])
    assert low[0] == 0 and 0 < high[0] < 0.35
    assert 0.65 < low[1] < 1 and high[1] == pytest.approx(1)


def test_add_rate_columns() -> None:
    df = pd.DataFrame({"n": [200], "white_wins": [100], "draws": [20], "black_wins": [80]})
    out = add_rate_columns(df)
    assert out.loc[0, "white_win_rate"] == 0.5
    assert out.loc[0, "draw_rate"] == 0.1
    assert out.loc[0, "white_win_ci_low"] < 0.5 < out.loc[0, "white_win_ci_high"]


def test_cramers_v_independent_and_dependent() -> None:
    independent = np.array([[100, 100], [100, 100]])
    _, p, dof, v = cramers_v(independent)
    assert v == pytest.approx(0) and p == pytest.approx(1) and dof == 1
    dependent = np.array([[100, 0], [0, 100]])
    assert cramers_v(dependent)[3] == pytest.approx(1)


def test_mean_abs_calibration_error_is_weighted() -> None:
    buckets = pd.DataFrame({"games": [3, 1], "actual_score": [0.6, 0.5], "expected_score": [0.5, 0.7]})
    assert mean_abs_calibration_error(buckets) == pytest.approx((3 * 0.1 + 1 * 0.2) / 4)


def test_named_queries_cover_every_question() -> None:
    queries = load_named_queries()
    for prefix in ("q1_", "q2_", "q3_", "q4_", "q5_", "q6_"):
        assert any(name.startswith(prefix) for name in queries), prefix
    for query in queries.values():
        code = "\n".join(line for line in query.splitlines() if not line.lstrip().startswith("--"))
        assert code.lstrip().upper().startswith(("SELECT", "WITH"))
    assert all("getvariable('min_games')" in q for name, q in queries.items() if name != "q5_activity_heatmap"
               and not name.startswith("q0") and not name.startswith("qc"))  # fmt: skip
