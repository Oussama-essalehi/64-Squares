"""Tests for the personal analysis (``eloscope.player``)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from eloscope import player
from eloscope.settings import PROJECT_ROOT, load_config

FIXTURES = Path(__file__).parent / "fixtures" / "sample_games.pgn"
CFG = load_config()


class FakeResponse:
    def __init__(self, status: int, text: str = "") -> None:
        self.status_code, self.text = status, text


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response, self.calls = response, []

    def get(self, url: str, **kwargs):  # noqa: ANN003
        self.calls.append((url, kwargs))
        return self.response


@pytest.fixture(scope="module")
def games() -> pd.DataFrame:
    return player.player_games(FIXTURES.read_text(encoding="utf-8"), "PlayerWhite", CFG)


@pytest.fixture(scope="module")
def report(games: pd.DataFrame) -> player.Report:
    return player.build_report(games, player.Baseline.load(PROJECT_ROOT / "app" / "data"))


def test_username_validation() -> None:
    assert player.valid_username("DrDrunkenstein")
    assert player.valid_username("a_b-c9")
    assert not player.valid_username("x")
    assert not player.valid_username("bad name")
    assert not player.valid_username("../etc")


def test_fetch_builds_the_api_request() -> None:
    session = FakeSession(FakeResponse(200, '[Event "Rated Blitz game"]\n\n1. e4 e5 1-0\n'))
    text = player.fetch_user_games("SomeUser", max_games=50, perf_types=("blitz",), session=session)
    url, kwargs = session.calls[0]
    assert url == "https://lichess.org/api/games/user/SomeUser"
    assert kwargs["params"]["max"] == 50 and kwargs["params"]["perfType"] == "blitz"
    assert kwargs["params"]["clocks"] == "true" and kwargs["headers"]["Accept"] == "application/x-chess-pgn"
    assert text.startswith("[Event")


@pytest.mark.parametrize(("status", "message"), [(404, "Fichier PGN"), (429, "Trop de requêtes"), (500, "HTTP 500")])
def test_fetch_errors_are_explained(status: int, message: str) -> None:
    with pytest.raises(player.LichessError, match=message):
        player.fetch_user_games("SomeUser", session=FakeSession(FakeResponse(status)))


def test_fetch_rejects_invalid_username() -> None:
    with pytest.raises(player.LichessError, match="Pseudo invalide"):
        player.fetch_user_games("bad name", session=FakeSession(FakeResponse(200)))


def test_player_games_uses_the_cleaning_rules(games: pd.DataFrame) -> None:
    # PlayerWhite has White in every fixture game; 14 of the 24 games pass the cleaning rules
    assert len(games) == 14
    assert set(games["color"]) == {"white"}
    assert games["score"].between(0, 1).all()
    assert set(games["period"]) <= {"nuit", "matin", "après-midi", "soir"}


def test_player_games_from_black_side() -> None:
    black = player.player_games(FIXTURES.read_bytes(), "playerblack", CFG)  # case-insensitive
    assert len(black) == 14 and set(black["color"]) == {"black"}


def test_player_games_unknown_player() -> None:
    assert player.player_games(FIXTURES.read_text(encoding="utf-8"), "Nobody", CFG).empty
    assert player.player_games("", "Nobody", CFG).empty


def test_lost_on_time_is_from_the_player_point_of_view(games: pd.DataFrame) -> None:
    # In the fixtures, White flagged in exactly one clean game (fx_eval)
    assert games["lost_on_time"].sum() == 1


def test_report(report: player.Report) -> None:
    assert report.games == 14
    assert report.main_band in {"< 1200", "1200-1599", "1600-1999", "2000+"}
    assert 0 <= report.summary["score"] <= 1
    assert 0.4 < report.summary["ref_score"] < 0.6
    assert set(report.by_tc["tc_category"]) <= set(player.TC_LABELS)
    assert report.clock["percentile"].between(0, 100).all()
    assert report.advice and all(isinstance(t, str) for t in report.advice)


def test_percentile_of() -> None:
    q = pd.DataFrame({"quantile": [0.25, 0.5, 0.75], "share_used": [0.05, 0.10, 0.20]})
    assert player.percentile_of(0.10, q) == pytest.approx(50)
    assert player.percentile_of(0.15, q) == pytest.approx(62.5)
    assert player.percentile_of(0.0, q) == 0 and player.percentile_of(0.9, q) == 100


def test_beyond_noise() -> None:
    assert not player.beyond_noise(0.5, 5)  # too few games
    assert not player.beyond_noise(0.1, 20)  # 10 points on 20 games is within the margin (±22 pts)
    assert player.beyond_noise(0.3, 20)
    assert player.beyond_noise(-0.05, 2000)
    assert not player.beyond_noise(float("nan"), 100)


def test_player_games_accepts_the_api_pgn_format() -> None:
    """Games downloaded from the API: lower-case Event, Variant and GameId headers."""
    text = FIXTURES.read_text(encoding="utf-8")
    api_like = text.replace('[Event "Rated ', '[Event "rated ').replace(' game"]', ' game"]\n[Variant "Standard"]')
    api_like = api_like.replace('[Event "rated Bullet', '[Event "rated bullet').replace(
        '[Event "rated Blitz', '[Event "rated blitz'
    )
    games = player.player_games(api_like, "PlayerWhite", CFG)
    assert len(games) == len(player.player_games(text, "PlayerWhite", CFG)) == 14
