"""Reference tables for the "Analyse mes parties" app (``app/data/``).

Each table describes the 2 million-game sample from the point of view of one player (both colours),
so that a visitor's games can be compared with players of the same Elo band, time control and
colour. Only aggregates with at least ``min_games`` games are kept (opening and clock tables).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from eloscope.model import connect
from eloscope.settings import PROJECT_ROOT, load_config

log = logging.getLogger("eloscope.baseline")

APP_DATA = PROJECT_ROOT / "app" / "data"

QUANTILES = ", ".join(f"{q / 100:.2f}" for q in range(5, 100, 5))

QUERIES: dict[str, str] = {
    # score, expectation and losses on time per band x time control x colour
    "baseline_results": """
        SELECT elo_band, tc_category, color, COUNT(*) AS games,
               ROUND(AVG(score), 6) AS score, ROUND(AVG(expected), 6) AS expected,
               ROUND(AVG(win), 6) AS win_rate, ROUND(AVG(draw), 6) AS draw_rate,
               ROUND(AVG(lost_on_time), 6) AS lost_on_time_rate
        FROM v_player_games GROUP BY ALL HAVING COUNT(*) >= {min_games} ORDER BY ALL""",
    # score and losses on time by 5-point bin of clock share used in the first 10 moves
    "baseline_time_used": """
        SELECT tc_category, LEAST(CAST(FLOOR(time_used_10 * 20) AS INTEGER), 19) * 5 AS bin_pct,
               COUNT(*) AS player_games, ROUND(AVG(score), 6) AS score,
               ROUND(AVG(lost_on_time), 6) AS lost_on_time_rate
        FROM v_player_games WHERE time_used_10 IS NOT NULL
        GROUP BY ALL HAVING COUNT(*) >= {min_games} ORDER BY ALL""",
    # percentiles of the clock share used, to place a player in the distribution
    "baseline_time_quantiles": """
        WITH q AS (
            SELECT tc_category,
                   QUANTILE_CONT(time_used_10, [{quantiles}]) AS shares
            FROM v_player_games WHERE time_used_10 IS NOT NULL GROUP BY tc_category
        )
        SELECT tc_category, UNNEST([{quantiles}]) AS quantile, ROUND(UNNEST(shares), 6) AS share_used
        FROM q ORDER BY ALL""",
    # opening families from the point of view of the side playing them
    "baseline_openings": """
        SELECT elo_band, color, opening_family, COUNT(*) AS games,
               ROUND(AVG(score), 6) AS score, ROUND(AVG(score - expected), 6) AS score_vs_expected
        FROM v_player_games GROUP BY ALL HAVING COUNT(*) >= {min_games} ORDER BY ALL""",
    # losses on time by period of the day (UTC)
    "baseline_periods": """
        SELECT tc_category,
               CASE WHEN hour BETWEEN 0 AND 5 THEN 'nuit' WHEN hour BETWEEN 6 AND 11 THEN 'matin'
                    WHEN hour BETWEEN 12 AND 17 THEN 'après-midi' ELSE 'soir' END AS period,
               COUNT(*) AS player_games, ROUND(AVG(lost_on_time), 6) AS lost_on_time_rate,
               ROUND(AVG(score), 6) AS score
        FROM v_player_games GROUP BY ALL HAVING COUNT(*) >= {min_games} ORDER BY ALL""",
}


def run(config: dict[str, Any] | None = None, out_dir: Path = APP_DATA) -> dict[str, int]:
    """Write the baseline CSV files used by the app; returns row counts."""
    cfg = config or load_config()
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    con = connect(cfg, read_only=True)
    try:
        for name, query in QUERIES.items():
            sql = query.format(min_games=int(cfg["analysis"]["min_games"]), quantiles=QUANTILES)
            frame = con.sql(sql).df()
            frame.to_csv(out_dir / f"{name}.csv", index=False)
            counts[name] = len(frame)
    finally:
        con.close()
    roots = PROJECT_ROOT / "reports" / "tables" / "opening_roots.csv"
    if roots.exists():  # written by the analysis step; used for the board diagrams
        shutil.copyfile(roots, out_dir / "opening_roots.csv")
    log.info("app baseline written: %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return counts
