"""Integrity of the static dashboard data (``site/data/dashboard.json``)."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from eloscope.settings import PROJECT_ROOT
from eloscope.site import _rows

DATA = PROJECT_ROOT / "site" / "data" / "dashboard.json"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def frame(payload: dict, name: str) -> pd.DataFrame:
    return pd.DataFrame(payload["tables"][name], columns=payload["columns"][name])


def test_rows_keep_integers_and_nulls() -> None:
    df = pd.DataFrame({"a": [1.0, float("nan")], "b": ["x", "y"], "c": [0.5, 2.0]})
    assert _rows(df) == [[1, "x", 0.5], [None, "y", 2]]


def test_every_table_adds_up_to_the_sample(payload: dict) -> None:
    games = payload["meta"]["games"]
    assert frame(payload, "results")["n"].sum() == games
    assert frame(payload, "calibration")["n"].sum() == games
    assert frame(payload, "activity")["n"].sum() == games
    # player view: two rows per game
    assert frame(payload, "openings")["n"].sum() == 2 * games


def test_counts_are_consistent(payload: dict) -> None:
    res = frame(payload, "results")
    assert (res["ww"] + res["d"] + res["bw"] == res["n"]).all()
    assert (res["lot"] <= res["ww"] + res["bw"]).all()
    op = frame(payload, "openings")
    assert ((op["w"] + op["d"] <= op["n"]) & (op["p"] <= op["n"])).all()
    assert sum(payload["meta"]["days_per_weekday"]) == 30


def test_every_family_has_a_board(payload: dict) -> None:
    for family, info in payload["openings"].items():
        assert (PROJECT_ROOT / "site" / "boards" / f"{info['board']}.svg").exists(), family
        assert info["chosen_by"] in {"Blancs", "Noirs"}
