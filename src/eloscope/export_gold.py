"""Export the star schema to ``data/gold/`` as CSV files for Power BI.

Format: UTF-8, comma separator, ``.`` decimal separator, ISO dates, booleans as 0/1.
Usernames (even hashed) are not exported: the dashboard only shows aggregates.

Files
-----
* ``dim_date.csv``, ``dim_opening.csv``, ``dim_time_control.csv``, ``dim_elo_band.csv``
* ``fact_games.csv``                    one row per game (large, git-ignored)
* ``agg_opening_band_tc.csv``           opening x Elo band x time control x colour
* ``agg_time_used_band_tc.csv``         clock share used in 10 moves (5-point bins) x band x
                                        time control x colour
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from eloscope.model import connect
from eloscope.settings import load_config, project_path, setup_logging

log = logging.getLogger("eloscope.export_gold")

EXPORTS: dict[str, str] = {
    "dim_date": """
        SELECT date_key, strftime(date, '%Y-%m-%d') AS date, year, month, day, weekday_num, weekday_name,
               weekday_short, is_weekend::INTEGER AS is_weekend
        FROM dim_date ORDER BY date_key""",
    "dim_opening": """
        SELECT opening_key, eco, family, full_name, COALESCE(variation, '') AS variation,
               in_reference::INTEGER AS in_reference
        FROM dim_opening ORDER BY opening_key""",
    "dim_time_control": """
        SELECT time_control_key, time_control, category, category_label, category_order,
               base_seconds, increment_seconds, estimated_seconds
        FROM dim_time_control ORDER BY time_control_key""",
    "dim_elo_band": "SELECT elo_band_key, elo_band, elo_min, elo_max, sort_order FROM dim_elo_band ORDER BY sort_order",
    "fact_games": """
        SELECT ROW_NUMBER() OVER (ORDER BY date_key, game_id) AS game_key,
               date_key, hour, opening_key, time_control_key, elo_band_key,
               white_elo, black_elo, avg_elo, rating_gap, rating_gap_bucket,
               ROUND(expected_score, 6) AS expected_score, white_score, winner, termination,
               lost_on_time::INTEGER AS lost_on_time, COALESCE(time_loser, '') AS time_loser, plies,
               has_clock::INTEGER AS has_clock,
               ROUND(white_time_used_10, 4) AS white_time_used_10,
               ROUND(black_time_used_10, 4) AS black_time_used_10
        FROM fact_games ORDER BY game_key""",
    "agg_opening_band_tc": """
        WITH p AS (
            SELECT opening_key, elo_band_key, time_control_key, 'Blancs' AS color,
                   (winner = 'white')::INTEGER AS win, (winner = 'draw')::INTEGER AS draw,
                   (winner = 'black')::INTEGER AS loss, white_score AS score, expected_score AS expected,
                   COALESCE(time_loser = 'white', FALSE)::INTEGER AS lost_on_time
            FROM fact_games
            UNION ALL
            SELECT opening_key, elo_band_key, time_control_key, 'Noirs',
                   (winner = 'black')::INTEGER, (winner = 'draw')::INTEGER, (winner = 'white')::INTEGER,
                   1 - white_score, 1 - expected_score, COALESCE(time_loser = 'black', FALSE)::INTEGER
            FROM fact_games
        )
        SELECT opening_key, elo_band_key, time_control_key, color,
               COUNT(*) AS games, SUM(win) AS wins, SUM(draw) AS draws, SUM(loss) AS losses,
               SUM(score) AS points, ROUND(SUM(expected), 4) AS expected_points,
               SUM(lost_on_time) AS lost_on_time
        FROM p GROUP BY ALL ORDER BY ALL""",
    "agg_time_used_band_tc": """
        WITH p AS (
            SELECT elo_band_key, time_control_key, 'Blancs' AS color, white_time_used_10 AS used,
                   white_score AS score, COALESCE(time_loser = 'white', FALSE)::INTEGER AS lost_on_time,
                   (winner = 'black')::INTEGER AS loss
            FROM fact_games WHERE white_time_used_10 IS NOT NULL
            UNION ALL
            SELECT elo_band_key, time_control_key, 'Noirs', black_time_used_10,
                   1 - white_score, COALESCE(time_loser = 'black', FALSE)::INTEGER, (winner = 'white')::INTEGER
            FROM fact_games WHERE black_time_used_10 IS NOT NULL
        )
        SELECT elo_band_key, time_control_key, color,
               LEAST(CAST(FLOOR(used * 20) AS INTEGER), 19) * 5 AS time_used_bin_pct,
               COUNT(*) AS player_games, SUM(score) AS points, SUM(loss) AS losses,
               SUM(lost_on_time) AS lost_on_time
        FROM p GROUP BY ALL ORDER BY ALL""",
}

GIT_LIMIT_MB = 50


def run(config: dict[str, Any] | None = None) -> dict[str, dict[str, float]]:
    """Write every gold CSV and a manifest with row counts and sizes."""
    cfg = config or load_config()
    gold = project_path("gold", cfg)
    gold.mkdir(parents=True, exist_ok=True)
    con = connect(cfg, read_only=True)
    manifest: dict[str, dict[str, float]] = {}
    try:
        for name, query in EXPORTS.items():
            path = gold / f"{name}.csv"
            con.execute(f"COPY ({query}) TO '{path.as_posix()}' (HEADER, DELIMITER ',', QUOTE '\"')")
            rows = con.sql(f"SELECT COUNT(*) FROM ({query})").fetchone()[0]
            size_mb = path.stat().st_size / 1e6
            manifest[name] = {"rows": int(rows), "size_mb": round(size_mb, 2), "in_git": size_mb <= GIT_LIMIT_MB}
            note = "" if size_mb <= GIT_LIMIT_MB else "  (git-ignored)"
            log.info("%-24s %10s rows %8.1f MB%s", name, f"{rows:,}", size_mb, note)
    finally:
        con.close()
    (gold / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    too_big = [n for n, m in manifest.items() if not m["in_git"] and n != "fact_games"]
    if too_big:
        log.warning("files above %d MB that are not git-ignored: %s", GIT_LIMIT_MB, too_big)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the gold CSV files for Power BI.")
    parser.add_argument("--config", help="path to an alternative config.yaml")
    args = parser.parse_args()
    setup_logging()
    run(load_config(args.config) if args.config else None)


if __name__ == "__main__":
    main()
