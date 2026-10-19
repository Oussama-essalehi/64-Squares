"""Build the DuckDB star schema (``data/eloscope.duckdb``) from the clean Parquet table.

Runs ``sql/01_schema.sql`` (dimensions and fact table) then ``sql/02_views.sql`` (analytical
views), and checks the referential integrity of the result.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from eloscope.settings import PROJECT_ROOT, load_config, project_path, setup_logging

log = logging.getLogger("eloscope.model")

SQL_DIR = PROJECT_ROOT / "sql"
QUERY_NAME_RE = re.compile(r"^-- name: (\w+)\s*$", re.MULTILINE)


def connect(config: dict[str, Any] | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the project database and set the SQL variables used by the analysis queries."""
    cfg = config or load_config()
    con = duckdb.connect(str(project_path("duckdb", cfg)), read_only=read_only)
    con.execute("SET VARIABLE min_games = ?", [cfg["analysis"]["min_games"]])
    con.execute("SET VARIABLE top_openings = ?", [cfg["analysis"]["top_openings"]])
    return con


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    """Execute every statement of a SQL file."""
    con.execute(path.read_text(encoding="utf-8"))


def load_named_queries(path: Path | None = None) -> dict[str, str]:
    """Split ``03_analysis_queries.sql`` into ``{name: sql}`` using the ``-- name:`` markers."""
    text = (path or SQL_DIR / "03_analysis_queries.sql").read_text(encoding="utf-8")
    parts = QUERY_NAME_RE.split(text)
    # parts = [preamble, name1, body1, name2, body2, ...]
    return {name: body.strip().rstrip(";") for name, body in zip(parts[1::2], parts[2::2])}


def integrity_checks(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Row counts and orphan-key checks of the star schema."""
    checks = {
        "stg_games": con.sql("SELECT COUNT(*) FROM stg_games").fetchone()[0],
        "fact_games": con.sql("SELECT COUNT(*) FROM fact_games").fetchone()[0],
        "dim_opening": con.sql("SELECT COUNT(*) FROM dim_opening").fetchone()[0],
        "dim_time_control": con.sql("SELECT COUNT(*) FROM dim_time_control").fetchone()[0],
        "dim_elo_band": con.sql("SELECT COUNT(*) FROM dim_elo_band").fetchone()[0],
        "dim_date": con.sql("SELECT COUNT(*) FROM dim_date").fetchone()[0],
        "duplicate_game_ids": con.sql("SELECT COUNT(*) - COUNT(DISTINCT game_id) FROM fact_games").fetchone()[0],
        "orphan_dates": con.sql("SELECT COUNT(*) FROM fact_games f ANTI JOIN dim_date d USING (date_key)").fetchone()[
            0
        ],
    }
    if checks["fact_games"] != checks["stg_games"]:
        raise RuntimeError(f"fact_games lost rows during the joins: {checks}")
    if checks["duplicate_game_ids"] or checks["orphan_dates"]:
        raise RuntimeError(f"integrity check failed: {checks}")
    return checks


def run(config: dict[str, Any] | None = None) -> dict[str, int]:
    """Create or replace the star schema and the views."""
    cfg = config or load_config()
    clean_path = project_path("processed", cfg) / "games_clean.parquet"
    if not clean_path.exists():
        raise FileNotFoundError(f"{clean_path} not found; run the clean step first")

    bands = pd.DataFrame(cfg["cleaning"]["elo_bands"], columns=["label", "lower_bound", "upper_bound"])
    bands["band_order"] = range(1, len(bands) + 1)

    con = connect(cfg)
    try:
        con.register("cfg_elo_bands_df", bands)
        con.execute("CREATE OR REPLACE TABLE cfg_elo_bands AS SELECT * FROM cfg_elo_bands_df")
        con.execute("CREATE OR REPLACE TABLE stg_games AS SELECT * FROM read_parquet(?)", [str(clean_path)])
        run_sql_file(con, SQL_DIR / "01_schema.sql")
        run_sql_file(con, SQL_DIR / "02_views.sql")
        checks = integrity_checks(con)
        con.execute("DROP TABLE stg_games")
        con.execute("CHECKPOINT")
    finally:
        con.close()
    log.info("star schema built: %s", ", ".join(f"{k}={v:,}" for k, v in checks.items()))
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the DuckDB star schema.")
    parser.add_argument("--config", help="path to an alternative config.yaml")
    args = parser.parse_args()
    setup_logging()
    run(load_config(args.config) if args.config else None)


if __name__ == "__main__":
    main()
