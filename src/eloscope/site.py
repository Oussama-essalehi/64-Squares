"""Data of the static web dashboard (``site/``).

The dashboard filters by Elo band and time control in the browser, so every table holds
**counts** (games, wins, points…) at the finest grain the filters need, never rates: the page
sums the selected cells and only then computes a rate, which keeps every number exact and lets
it apply the minimum-sample rule itself. Output: ``site/data/dashboard.json`` and one board
diagram per opening family in ``site/boards/``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from eloscope.boards import family_roots, slug, write_boards
from eloscope.model import connect
from eloscope.openings import load_reference
from eloscope.settings import PROJECT_ROOT, load_config

log = logging.getLogger("eloscope.site")

SITE = PROJECT_ROOT / "site"

TABLES: dict[str, str] = {
    # band x time control: result counts (White's point of view)
    "results": """
        SELECT elo_band_order AS b, tc_order AS t, COUNT(*) AS n, SUM(white_win) AS ww, SUM(draw) AS d,
               SUM(black_win) AS bw, ROUND(SUM(expected_score), 3) AS e, SUM(lost_on_time::INT) AS lot
        FROM v_games GROUP BY ALL ORDER BY ALL""",
    # band x time control x family x colour of the side playing it
    "openings": """
        SELECT elo_band_order AS b, tc_order AS t, opening_family AS f, color AS c, COUNT(*) AS n,
               SUM(win) AS w, SUM(draw) AS d, SUM(score) AS p, ROUND(SUM(expected), 3) AS e
        FROM v_player_games GROUP BY ALL ORDER BY ALL""",
    # band x time control x rating-gap bucket (White's point of view)
    "calibration": """
        SELECT elo_band_order AS b, tc_order AS t, rating_gap_bucket AS g, COUNT(*) AS n,
               SUM(white_score) AS p, ROUND(SUM(expected_score), 3) AS e
        FROM v_games GROUP BY ALL ORDER BY ALL""",
    # band x time control x 5-point bin of clock share used in 10 moves (player view)
    "clock": """
        SELECT elo_band_order AS b, tc_order AS t,
               LEAST(CAST(FLOOR(time_used_10 * 20) AS INTEGER), 19) * 5 AS k,
               COUNT(*) AS n, SUM(score) AS p, SUM(lost_on_time) AS lot
        FROM v_player_games WHERE time_used_10 IS NOT NULL GROUP BY ALL ORDER BY ALL""",
    # band x time control x weekday x hour
    "activity": """
        SELECT elo_band_order AS b, tc_order AS t, weekday_num AS w, hour AS h, COUNT(*) AS n,
               SUM(white_score) AS p, SUM(lost_on_time::INT) AS lot
        FROM v_games GROUP BY ALL ORDER BY ALL""",
}


def _rows(frame: Any) -> list[list[Any]]:
    """Compact JSON rows: integers stay integers, NaN becomes null."""
    out = []
    for row in frame.itertuples(index=False):
        cells = []
        for v in row:
            if isinstance(v, str):
                cells.append(v)
            elif v != v:  # NaN
                cells.append(None)
            else:
                cells.append(int(v) if float(v).is_integer() else float(v))
        out.append(cells)
    return out


def run(config: dict[str, Any] | None = None, out_dir: Path = SITE) -> dict[str, int]:
    """Write ``dashboard.json`` and the board diagrams; returns row counts per table."""
    cfg = config or load_config()
    con = connect(cfg, read_only=True)
    try:
        payload: dict[str, Any] = {
            "meta": {
                "month": cfg["source"]["month"],
                "games": con.sql("SELECT COUNT(*) FROM fact_games").fetchone()[0],
                "min_games": cfg["analysis"]["min_games"],
                "bands": [b[0] for b in cfg["cleaning"]["elo_bands"]],
                "time_controls": ["UltraBullet", "Bullet", "Blitz", "Rapide", "Classique"],
                "weekdays": ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"],
                "days_per_weekday": [
                    r[1] for r in con.sql("SELECT weekday_num, COUNT(*) FROM dim_date GROUP BY 1 ORDER BY 1").fetchall()
                ],  # fmt: skip
            },
            "columns": {},
            "tables": {},
        }
        for name, sql in TABLES.items():
            frame = con.sql(sql).df()
            payload["columns"][name] = list(frame.columns)
            payload["tables"][name] = _rows(frame)
    finally:
        con.close()

    roots = family_roots(load_reference(cfg))
    families = sorted({row[2] for row in payload["tables"]["openings"]})
    by_family = roots.set_index("family")
    payload["openings"] = {
        f: {"moves": by_family.loc[f, "moves"], "chosen_by": by_family.loc[f, "chosen_by"], "board": slug(f)}
        for f in families
        if f in by_family.index
    }
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    path = out_dir / "data" / "dashboard.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    boards = write_boards(list(payload["openings"]), roots, out_dir / "boards", size=200)
    counts = {name: len(rows) for name, rows in payload["tables"].items()}
    log.info("site data: %s (%.0f kB), %d boards", counts, path.stat().st_size / 1e3, len(boards))
    return counts
