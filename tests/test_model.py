"""Integration test: build the star schema and views from the fixture games in memory."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from eloscope import clean, ingest
from eloscope.model import SQL_DIR, load_named_queries, run_sql_file
from eloscope.settings import load_config

FIXTURES = Path(__file__).parent / "fixtures" / "sample_games.pgn"
CFG = load_config()


@pytest.fixture(scope="module")
def con() -> duckdb.DuckDBPyConnection:
    raw = pd.DataFrame([ingest.parse_game(g, "salt", i) for i, g in enumerate(ingest.split_pgn(FIXTURES.read_bytes()))])
    kept, _ = clean.apply_exclusions(raw, CFG)
    reference = pd.DataFrame({"name": ["Sicilian Defense: Smith-Morra Gambit"]})
    games = clean.add_derived_columns(kept, CFG, reference)
    bands = pd.DataFrame(CFG["cleaning"]["elo_bands"], columns=["label", "lower_bound", "upper_bound"])
    bands["band_order"] = range(1, len(bands) + 1)
    connection = duckdb.connect()
    connection.register("games_df", games)
    connection.register("bands_df", bands)
    connection.execute("CREATE TABLE stg_games AS SELECT * FROM games_df")
    connection.execute("CREATE TABLE cfg_elo_bands AS SELECT * FROM bands_df")
    run_sql_file(connection, SQL_DIR / "01_schema.sql")
    run_sql_file(connection, SQL_DIR / "02_views.sql")
    connection.execute("SET VARIABLE min_games = 1")
    connection.execute("SET VARIABLE top_openings = 10")
    return connection


def test_fact_keeps_every_clean_game(con: duckdb.DuckDBPyConnection) -> None:
    assert con.sql("SELECT COUNT(*) FROM fact_games").fetchone()[0] == 14
    assert (
        con.sql("SELECT COUNT(*) FROM fact_games WHERE opening_key IS NULL OR time_control_key IS NULL").fetchone()[0]
        == 0
    )


def test_dimensions(con: duckdb.DuckDBPyConnection) -> None:
    assert con.sql("SELECT COUNT(*) FROM dim_elo_band").fetchone()[0] == 4
    weekday = con.sql("SELECT weekday_name FROM dim_date WHERE date = DATE '2026-09-01'").fetchone()[0]
    assert weekday == "Mardi"  # 1 September 2026 is a Tuesday
    assert con.sql("SELECT COUNT(DISTINCT category) FROM dim_time_control").fetchone()[0] == 5


def test_player_view_has_two_rows_per_game_and_consistent_rates(con: duckdb.DuckDBPyConnection) -> None:
    rows, wins, losses, flags = con.sql(
        "SELECT COUNT(*), SUM(win), SUM(loss), SUM(lost_on_time) FROM v_player_games"
    ).fetchone()
    assert rows == 28 and wins == losses
    games_lost_on_time = con.sql("SELECT SUM(lost_on_time::INT) FROM fact_games").fetchone()[0]
    assert flags == games_lost_on_time  # each flag counted once, on the loser's row
    # a player cannot lose on time more often than they lose
    assert con.sql("SELECT BOOL_AND(lost_on_time <= loss) FROM v_player_games").fetchone()[0]
    assert con.sql("SELECT COUNT(*) FROM v_player_games WHERE lost_on_time IS NULL").fetchone()[0] == 0


def test_every_analysis_query_runs(con: duckdb.DuckDBPyConnection) -> None:
    for name, query in load_named_queries().items():
        assert con.sql(query).df() is not None, name  # raises on any SQL error
