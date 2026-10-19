"""Tests for the cleaning rules and derived columns (``eloscope.clean``, ``eloscope.openings``)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from eloscope import clean, ingest
from eloscope.openings import map_families, opening_family, opening_variation
from eloscope.settings import load_config

FIXTURES = Path(__file__).parent / "fixtures" / "sample_games.pgn"
CFG = load_config()
BANDS = CFG["cleaning"]["elo_bands"]


@pytest.fixture(scope="module")
def raw_frame() -> pd.DataFrame:
    games = ingest.split_pgn(FIXTURES.read_bytes())
    return pd.DataFrame([ingest.parse_game(g, "salt", i) for i, g in enumerate(games)])


@pytest.fixture(scope="module")
def cleaned(raw_frame: pd.DataFrame) -> tuple[pd.DataFrame, list[clean.RuleResult]]:
    return clean.apply_exclusions(raw_frame, CFG)


@pytest.fixture(scope="module")
def derived(cleaned: tuple[pd.DataFrame, list[clean.RuleResult]]) -> pd.DataFrame:
    reference = pd.DataFrame({"name": ["Sicilian Defense", "Sicilian Defense: Smith-Morra Gambit"]})
    return clean.add_derived_columns(cleaned[0], CFG, reference).set_index("game_id")


# --- time control ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [("180+2", (180, 2)), ("0+1", (0, 1)), ("15+0", (15, 0)), ("-", None), ("", None), (None, None), ("abc", None)],
)
def test_parse_time_control(value: str | None, expected: tuple[int, int] | None) -> None:
    assert clean.parse_time_control(value) == expected


@pytest.mark.parametrize(
    ("base", "increment", "category"),
    [
        (15, 0, "ultrabullet"),
        (29, 0, "ultrabullet"),  # 29 s: last ultrabullet value
        (30, 0, "bullet"),  # 30 s: first bullet value
        (0, 1, "bullet"),  # 0 + 40 = 40 s
        (60, 0, "bullet"),
        (120, 1, "bullet"),  # 160 s
        (179, 0, "bullet"),
        (180, 0, "blitz"),  # boundary
        (60, 3, "blitz"),  # 60 + 120 = 180 s
        (300, 3, "blitz"),  # 420 s
        (479, 0, "blitz"),
        (480, 0, "rapid"),  # boundary
        (600, 5, "rapid"),
        (1499, 0, "rapid"),
        (1500, 0, "classical"),  # boundary
        (900, 15, "classical"),  # 900 + 600 = 1500 s
        (1800, 20, "classical"),
    ],
)
def test_categorize_time_control(base: int, increment: int, category: str) -> None:
    assert clean.categorize_time_control(base, increment) == category


# --- Elo band and rating gap -------------------------------------------------------------
@pytest.mark.parametrize(
    ("avg", "band"),
    [(400, "< 1200"), (1199.5, "< 1200"), (1200, "1200-1599"), (1599.5, "1200-1599"), (1600, "1600-1999"),
     (1999.5, "1600-1999"), (2000, "2000+"), (3200, "2000+")],
)  # fmt: skip
def test_elo_band(avg: float, band: str) -> None:
    assert clean.elo_band(avg, BANDS) == band


@pytest.mark.parametrize(
    ("gap", "bucket"),
    [(0, 0), (24, 0), (-25, 0), (25, 50), (-26, -50), (49, 50), (74, 50), (75, 100), (-575, -550), (590, 600),
     (612, 600), (2000, 600), (-2000, -600)],
)  # fmt: skip
def test_rating_gap_bucket(gap: int, bucket: int) -> None:
    assert clean.rating_gap_bucket(gap) == bucket


def test_rating_gap_bucket_vectorised() -> None:
    gaps = pd.Series([-700, -30, 10, 80, 640], index=list("abcde"))
    result = clean.rating_gap_bucket(gaps)
    assert result.tolist() == [-600, -50, 0, 100, 600]
    assert list(result.index) == list("abcde")


def test_expected_score() -> None:
    assert clean.expected_score(0) == pytest.approx(0.5)
    assert clean.expected_score(400) == pytest.approx(10 / 11)
    assert clean.expected_score(-400) == pytest.approx(1 / 11)
    assert clean.expected_score(100) + clean.expected_score(-100) == pytest.approx(1.0)


def test_elo_band_column_matches_helper(derived: pd.DataFrame) -> None:
    for avg, band in zip(derived["avg_elo"], derived["elo_band"]):
        assert band == clean.elo_band(avg, BANDS)
    assert derived.loc["fx_titled", "elo_band"] == "2000+"
    assert derived.loc["fx_low_rating", "elo_band"] == "< 1200"


def test_rating_gap_is_white_minus_black(derived: pd.DataFrame) -> None:
    assert (derived["rating_gap"] == derived["white_elo"] - derived["black_elo"]).all()
    assert derived.loc["fx_no_ratingdiff", "rating_gap_bucket"] == -600  # capped (gap -961)


# --- exclusion rules ---------------------------------------------------------------------
EXCLUDED_BY = {
    "R1": {"fx_variant_chess960", "fx_casual"},
    "R2": {"fx_abandoned", "fx_insufficient", "fx_unterminated"},
    "R3": {"fx_short"},
    "R4": {"fx_bot"},
    "R5": {"fx_missing_elo", "fx_elo_out_of_range"},
    "R6": {"fx_correspondence"},
}


def test_each_rule_removes_the_expected_games(
    raw_frame: pd.DataFrame, cleaned: tuple[pd.DataFrame, list[clean.RuleResult]]
) -> None:
    kept, results = cleaned
    removed = {r.rule: r.removed for r in results}
    assert removed == {"R0": 0, **{rule: len(ids) for rule, ids in EXCLUDED_BY.items()}}
    excluded = set().union(*EXCLUDED_BY.values())
    assert set(raw_frame["game_id"]) - set(kept["game_id"]) == excluded
    assert len(kept) == 14


def test_rules_are_logged_in_order(cleaned: tuple[pd.DataFrame, list[clean.RuleResult]]) -> None:
    _, results = cleaned
    assert [r.rule for r in results] == ["R0", "R1", "R2", "R3", "R4", "R5", "R6"]
    for previous, current in zip(results, results[1:]):
        assert current.rows_before == previous.rows_after


def test_duplicates_removed(raw_frame: pd.DataFrame) -> None:
    doubled = pd.concat([raw_frame, raw_frame.iloc[:3]], ignore_index=True)
    _, results = clean.apply_exclusions(doubled, CFG)
    assert results[0].removed == 3


def test_rated_standard_filter() -> None:
    event = pd.Series(
        ["Rated Blitz game", "Casual Blitz game", "Rated Chess960 game", "Rated Rapid tournament x", None]
    )
    variant = pd.Series([None, None, "Chess960", None, None])
    assert clean.is_rated_standard(event, variant).tolist() == [True, False, False, True, False]


def test_lichess_api_event_format_is_accepted() -> None:
    """The API writes ``"rated blitz game"`` in lower case and adds ``Variant "Standard"``."""
    event = pd.Series(["rated blitz game", "rated bullet game", "casual blitz game", "rated crazyhouse game"])
    variant = pd.Series(["Standard", "Standard", "Standard", "Crazyhouse"])
    assert clean.is_rated_standard(event, variant).tolist() == [True, True, False, False]
    assert clean.event_speed(event).tolist()[:2] == ["Blitz", "Bullet"]


def test_time_forfeit_and_normal_are_kept(derived: pd.DataFrame) -> None:
    assert set(derived["termination"]) == {"Normal", "Time forfeit"}


def test_bot_on_black_side_is_excluded(raw_frame: pd.DataFrame) -> None:
    frame = raw_frame[raw_frame["game_id"] == "fx_bullet_normal"].copy()
    frame["black_title"] = "BOT"
    kept, _ = clean.apply_exclusions(frame, CFG)
    assert kept.empty


# --- results -------------------------------------------------------------------------------
def test_result_columns(derived: pd.DataFrame) -> None:
    mapping = {"1-0": (1.0, "white"), "0-1": (0.0, "black"), "1/2-1/2": (0.5, "draw")}
    for _, row in derived.iterrows():
        assert (row["white_score"], row["winner"]) == mapping[row["result"]]
    assert derived.loc["fx_rapid_draw", "winner"] == "draw"


def test_lost_on_time(derived: pd.DataFrame) -> None:
    assert derived.loc["fx_blitz_timeforfeit", "lost_on_time"]
    assert not derived.loc["fx_bullet_normal", "lost_on_time"]
    # the side that lost on time is the side that did not win
    for _, row in derived[derived["lost_on_time"]].iterrows():
        assert row["time_loser"] != row["winner"]


# --- openings ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "family", "variation"),
    [
        ("Sicilian Defense: Najdorf Variation", "Sicilian Defense", "Najdorf Variation"),
        (
            "Sicilian Defense: Najdorf Variation, English Attack",
            "Sicilian Defense",
            "Najdorf Variation, English Attack",
        ),
        ("Queen's Gambit Declined", "Queen's Gambit Declined", None),
        ("Van't Kruijs Opening", "Van't Kruijs Opening", None),
        ("?", "Unknown", None),
        ("", "Unknown", None),
        (None, "Unknown", None),
    ],
)
def test_opening_family(name: str | None, family: str, variation: str | None) -> None:
    assert opening_family(name) == family
    if name not in ("?", "", None):
        assert opening_variation(name) == variation


def test_map_families_flags_reference_membership() -> None:
    reference = pd.DataFrame({"name": ["Italian Game", "Italian Game: Giuoco Piano"]})
    openings = pd.Series(["Italian Game: Giuoco Piano", "Italian Game: Made Up Line", None])
    mapped = map_families(openings, reference)
    assert mapped["opening_family"].tolist() == ["Italian Game", "Italian Game", "Unknown"]
    assert mapped["in_reference"].tolist() == [True, False, False]


def test_opening_columns(derived: pd.DataFrame) -> None:
    row = derived.loc["fx_bullet_normal"]
    assert row["opening"] == "Sicilian Defense: Smith-Morra Gambit"
    assert row["opening_family"] == "Sicilian Defense"
    assert row["opening_variation"] == "Smith-Morra Gambit"
    assert bool(row["opening_in_reference"])


# --- clock features ------------------------------------------------------------------------
def test_clock_features_basic() -> None:
    feats = clean.clock_features(
        clk_start=pd.Series([180.0, 180.0, 60.0]),
        clk_10=pd.Series([150.0, 200.0, np.nan]),
        base=pd.Series([180, 180, 60]),
        increment=pd.Series([2, 2, 0]),
    )
    # 180 + 9 * 2 - 150 = 48 s, i.e. 48 / 180 of the base time
    assert feats["time_used"].iloc[0] == pytest.approx(48)
    assert feats["time_share"].iloc[0] == pytest.approx(48 / 180)
    assert feats["time_used"].iloc[1] == 0  # never negative
    assert np.isnan(feats["time_share"].iloc[2])  # no clock after move 10


def test_clock_features_berserk_and_zero_base() -> None:
    feats = clean.clock_features(
        clk_start=pd.Series([90.0, 3.0]),
        clk_10=pd.Series([60.0, 5.0]),
        base=pd.Series([180, 0]),
        increment=pd.Series([2, 1]),
    )
    assert feats["berserk"].tolist() == [True, False]
    assert feats["time_used"].iloc[0] == pytest.approx(30)  # increment removed under berserk
    assert feats["time_share"].iloc[0] == pytest.approx(30 / 90)
    assert np.isnan(feats["time_share"].iloc[1])  # no share when the base time is zero


def test_clock_columns_on_fixtures(derived: pd.DataFrame) -> None:
    assert derived.loc["fx_no_clock", "has_clock"] == False  # noqa: E712
    assert np.isnan(derived.loc["fx_no_clock", "white_time_used_10"])
    assert derived.loc["fx_berserk", "white_berserk"]
    shares = derived[["white_time_used_10", "black_time_used_10"]].stack().dropna()
    assert shares.between(0, 1).all()


def test_event_speed_agrees_with_time_control_rule(derived: pd.DataFrame) -> None:
    assert (derived["event_speed"] == derived["tc_category"]).all()


def test_dates_and_hours(derived: pd.DataFrame) -> None:
    assert derived["hour"].between(0, 23).all()
    assert derived["weekday"].between(0, 6).all()
    assert all(str(d).startswith("2026-09") for d in derived["date"])
