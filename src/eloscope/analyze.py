"""Statistical analysis: answers the business questions with numbers, tables and figures.

Outputs
-------
* ``reports/tables/*.csv``     every SQL query of ``sql/03_analysis_queries.sql`` and every
                               Python result table (Wilson intervals, tests, regression)
* ``reports/metrics.json``     key numbers quoted in ``reports/findings.md`` and the README
* ``reports/figures/*.png``    the charts
* ``reports/tables/cross_check.csv``  SQL vs Python agreement
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import chi2_contingency
from statsmodels.stats.proportion import proportion_confint

from eloscope import charts
from eloscope.model import connect, load_named_queries
from eloscope.settings import PROJECT_ROOT, load_config, project_path, setup_logging

log = logging.getLogger("eloscope.analyze")

TABLES_DIR = PROJECT_ROOT / "reports" / "tables"
METRICS_PATH = PROJECT_ROOT / "reports" / "metrics.json"


# --------------------------------------------------------------------------------------
# Statistics helpers
# --------------------------------------------------------------------------------------
def wilson_interval(successes: Any, n: Any, confidence: float = 0.95) -> tuple[np.ndarray, np.ndarray]:
    """Wilson score interval for a binomial proportion (vectorised)."""
    low, high = proportion_confint(np.asarray(successes), np.asarray(n), alpha=1 - confidence, method="wilson")
    return np.asarray(low), np.asarray(high)


def add_rate_columns(df: pd.DataFrame, confidence: float = 0.95) -> pd.DataFrame:
    """Add win / draw / loss rates with Wilson intervals from count columns.

    Expects ``n, white_wins, draws, black_wins`` and adds ``<x>_rate``, ``<x>_ci_low``,
    ``<x>_ci_high`` for each outcome.
    """
    out = df.copy()
    for count, name in (("white_wins", "white_win"), ("draws", "draw"), ("black_wins", "black_win")):
        out[f"{name}_rate"] = out[count] / out["n"]
        out[f"{name}_ci_low"], out[f"{name}_ci_high"] = wilson_interval(out[count], out["n"], confidence)
    return out


def cramers_v(table: np.ndarray) -> tuple[float, float, int, float]:
    """Chi-square test of independence and Cramér's V for a contingency table.

    Returns ``(chi2, p_value, dof, v)`` with ``V = sqrt(chi2 / (n * (min(r, c) - 1)))``.
    """
    chi2, p_value, dof, _ = chi2_contingency(table, correction=False)
    n = table.sum()
    k = min(table.shape) - 1
    return float(chi2), float(p_value), int(dof), float(np.sqrt(chi2 / (n * k))) if k > 0 else float("nan")


def json_default(value: Any) -> Any:
    """Serialise numpy / pandas scalars, dates and missing values for ``json.dumps``."""
    if isinstance(value, (pd.Timestamp, np.datetime64)) or hasattr(value, "isoformat"):
        return str(pd.Timestamp(value).date())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)
    if value is pd.NA or value is pd.NaT:
        return None
    return float(value)


def mean_abs_calibration_error(buckets: pd.DataFrame) -> float:
    """Game-weighted mean of |actual - expected| over rating-gap buckets."""
    weights = buckets["games"]
    return float((buckets["actual_score"] - buckets["expected_score"]).abs().mul(weights).sum() / weights.sum())


# --------------------------------------------------------------------------------------
# Analyses
# --------------------------------------------------------------------------------------
def outcome_counts(con: duckdb.DuckDBPyConnection, by: list[str], min_games: int) -> pd.DataFrame:
    cols = ", ".join(by)
    frame = con.sql(
        f"""
        SELECT {cols}, COUNT(*) AS n, SUM(white_win) AS white_wins, SUM(draw) AS draws,
               SUM(black_win) AS black_wins, AVG(white_score) AS white_score,
               STDDEV_SAMP(white_score) AS white_score_sd, AVG(expected_score) AS expected_score
        FROM v_games GROUP BY ALL HAVING COUNT(*) >= {int(min_games)}
        """
    ).df()
    order = [c for c in by if c.endswith("_order")] + [c for c in by if not c.endswith("_order")]
    return frame.sort_values(order).reset_index(drop=True)


def chi_square_by_band(con: duckdb.DuckDBPyConnection, min_games: int) -> pd.DataFrame:
    """Opening family x result independence test in each Elo band (families >= min_games)."""
    counts = con.sql(
        "SELECT elo_band, elo_band_order, opening_family, winner, COUNT(*) AS n FROM v_games GROUP BY ALL"
    ).df()
    rows = []
    for (band, order), sub in counts.groupby(["elo_band", "elo_band_order"]):
        table = sub.pivot_table(index="opening_family", columns="winner", values="n", fill_value=0, aggfunc="sum")
        table = table[table.sum(axis=1) >= min_games]
        chi2, p, dof, v = cramers_v(table.to_numpy())
        rows.append(
            {"elo_band": band, "elo_band_order": order, "families": len(table), "games": int(table.to_numpy().sum()),
             "chi2": chi2, "dof": dof, "p_value": p, "cramers_v": v}
        )  # fmt: skip
    return pd.DataFrame(rows).sort_values("elo_band_order").reset_index(drop=True)


def logistic_regression(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Logit of a White win (decisive games) on rating gap, time control and opening clock use."""
    data = con.sql(
        """
        SELECT white_win, rating_gap / 100.0 AS gap_100, tc_label, elo_band,
               white_time_used_10 * 10 AS white_used_10pts, black_time_used_10 * 10 AS black_used_10pts
        FROM v_games
        WHERE winner <> 'draw' AND white_time_used_10 IS NOT NULL AND black_time_used_10 IS NOT NULL
        """
    ).df()
    formula = (
        "white_win ~ gap_100 + C(tc_label, Treatment('Blitz')) + C(elo_band, Treatment('1600-1999'))"
        " + white_used_10pts + black_used_10pts"
    )
    result = smf.logit(formula, data=data).fit(disp=False, maxiter=100)
    ci = result.conf_int()
    labels = {
        "Intercept": "Constante",
        "gap_100": "Écart Elo +100 (Blancs − Noirs)",
        "white_used_10pts": "Blancs : +10 pts de temps utilisé (10 coups)",
        "black_used_10pts": "Noirs : +10 pts de temps utilisé (10 coups)",
    }
    table = pd.DataFrame(
        {
            "term": result.params.index,
            "coef": result.params.values,
            "std_err": result.bse.values,
            "p_value": result.pvalues.values,
            "odds_ratio": np.exp(result.params.values),
            "or_low": np.exp(ci[0].values),
            "or_high": np.exp(ci[1].values),
        }
    )

    def label(term: str) -> str:
        if term in labels:
            return labels[term]
        level = term.split("[T.")[-1].rstrip("]")
        return f"Cadence {level} (vs Blitz)" if "tc_label" in term else f"Elo {level} (vs 1600-1999)"

    table["label"] = table["term"].map(label)
    info = {
        "n_games": int(result.nobs),
        "pseudo_r2": float(result.prsquared),
        "white_win_share": float(data["white_win"].mean()),
        "formula": formula,
    }
    return table, info


def cross_check(con: duckdb.DuckDBPyConnection, cfg: dict[str, Any], queries: dict[str, str]) -> pd.DataFrame:
    """Recompute White's score per band and the top-3 opening families of two bands in pandas
    from the clean Parquet file, and compare with the SQL results."""
    clean = pd.read_parquet(
        project_path("processed", cfg) / "games_clean.parquet", columns=["elo_band", "white_score", "opening_family"]
    )
    rows = []
    sql_score = con.sql(queries["qc_white_score_by_band"]).df().set_index("elo_band")
    py_score = clean.groupby("elo_band")["white_score"].agg(["mean", "size"])
    for band in sql_score.index:
        rows.append(
            {"check": f"white_score {band}", "sql": float(sql_score.loc[band, "white_score"]),
             "python": round(float(py_score.loc[band, "mean"]), 6),
             "match": abs(sql_score.loc[band, "white_score"] - py_score.loc[band, "mean"]) < 1e-6
             and int(sql_score.loc[band, "games"]) == int(py_score.loc[band, "size"])}
        )  # fmt: skip
    sql_top = con.sql(queries["q1_top_openings_by_band"]).df()
    for band in ("< 1200", "2000+"):
        sql_list = sql_top[sql_top["elo_band"] == band].nsmallest(3, "popularity_rank")["opening_family"].tolist()
        py_list = clean.loc[clean["elo_band"] == band, "opening_family"].value_counts().head(3).index.tolist()
        rows.append({"check": f"top-3 openings {band}", "sql": " | ".join(sql_list), "python": " | ".join(py_list),
                     "match": sql_list == py_list})  # fmt: skip
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def _configure_browser() -> None:
    """kaleido needs Chrome: honour BROWSER_PATH, else fall back to a known Chromium install."""
    for noisy in ("choreographer", "kaleido", "logistro"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if os.environ.get("BROWSER_PATH"):
        return
    for candidate in ("/opt/pw-browsers/chromium-1194/chrome-linux/chrome",):
        if Path(candidate).exists():
            os.environ["BROWSER_PATH"] = candidate
            return


def run(config: dict[str, Any] | None = None, figures: bool = True) -> dict[str, Any]:
    cfg = config or load_config()
    min_games = cfg["analysis"]["min_games"]
    confidence = cfg["analysis"]["confidence"]
    bands = [b[0] for b in cfg["cleaning"]["elo_bands"]]
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    fig_dir = project_path("figures", cfg)
    con = connect(cfg, read_only=True)
    queries = load_named_queries()

    # 1. Every SQL answer, saved for traceability
    sql: dict[str, pd.DataFrame] = {}
    for name, query in queries.items():
        sql[name] = con.sql(query).df()
        sql[name].to_csv(TABLES_DIR / f"{name}.csv", index=False)
    log.info("%d SQL queries executed and saved", len(sql))

    # 2. Rates with Wilson intervals
    by_band = add_rate_columns(outcome_counts(con, ["elo_band", "elo_band_order"], min_games), confidence)
    by_band_tc = add_rate_columns(
        outcome_counts(con, ["elo_band", "elo_band_order", "tc_label", "tc_order"], min_games), confidence
    )
    by_tc = add_rate_columns(outcome_counts(con, ["tc_label", "tc_order"], min_games), confidence)
    by_family = add_rate_columns(
        outcome_counts(con, ["elo_band", "elo_band_order", "opening_family"], min_games), confidence
    )
    for frame in (by_band, by_band_tc, by_tc):
        frame["white_score_ci"] = 1.96 * frame["white_score_sd"] / np.sqrt(frame["n"])
    by_band.to_csv(TABLES_DIR / "py_results_by_band_wilson.csv", index=False)
    by_band_tc.to_csv(TABLES_DIR / "py_results_by_band_tc_wilson.csv", index=False)
    by_tc.to_csv(TABLES_DIR / "py_results_by_tc_wilson.csv", index=False)
    by_family.to_csv(TABLES_DIR / "py_results_by_band_family_wilson.csv", index=False)

    # 3. Chi-square opening family x result per band
    chi = chi_square_by_band(con, min_games)
    chi.to_csv(TABLES_DIR / "py_chi_square_by_band.csv", index=False)

    # 4. Elo calibration
    calib = sql["q3_calibration"]
    mace = {tc: mean_abs_calibration_error(sub) for tc, sub in calib.groupby("time_control", sort=False)}

    # 5. Logistic regression
    logit, logit_info = logistic_regression(con)
    logit.to_csv(TABLES_DIR / "py_logit_white_win.csv", index=False)

    # 6. Cross-check SQL vs Python
    checks = cross_check(con, cfg, queries)
    checks.to_csv(TABLES_DIR / "cross_check.csv", index=False)
    if not checks["match"].all():
        log.error("SQL / Python cross-check failed:\n%s", checks.to_string())
    else:
        log.info("SQL / Python cross-check: %d/%d checks match", checks["match"].sum(), len(checks))

    metrics = build_metrics(con, sql, by_band, by_tc, chi, mace, logit, logit_info, checks, cfg)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=json_default), encoding="utf-8")
    con.close()

    if figures:
        _configure_browser()
        make_figures(sql, by_band, chi, logit, bands, fig_dir)
    return metrics


def build_metrics(
    con: duckdb.DuckDBPyConnection,
    sql: dict[str, pd.DataFrame],
    by_band: pd.DataFrame,
    by_tc: pd.DataFrame,
    chi: pd.DataFrame,
    mace: dict[str, float],
    logit: pd.DataFrame,
    logit_info: dict[str, Any],
    checks: pd.DataFrame,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Collect the headline numbers in one JSON document."""
    overview = (
        con.sql(
            """SELECT COUNT(*) AS games, AVG(white_score) AS white_score, AVG(white_win) AS white_win,
                  AVG(draw) AS draw, AVG(black_win) AS black_win, AVG(lost_on_time::INT) AS lost_on_time,
                  AVG(has_clock::INT) AS has_clock, AVG((white_time_used_10 IS NOT NULL)::INT) AS has_time_used,
                  AVG(white_score - expected_score) AS white_edge, COUNT(DISTINCT opening_family) AS families,
                  MIN(date) AS first_day, MAX(date) AS last_day
           FROM v_games"""
        )
        .df()
        .iloc[0]
        .to_dict()
    )
    players = con.sql(
        "SELECT COUNT(DISTINCT h) FROM "
        "(SELECT white_hash AS h FROM fact_games UNION ALL SELECT black_hash FROM fact_games)"
    ).fetchone()[0]
    report = json.loads((project_path("processed", cfg) / "cleaning_report.json").read_text(encoding="utf-8"))
    deciles = sql["q4_time_used_deciles"]
    decile_summary = {
        tc: {
            "d1_score": float(s.loc[s.decile == 1, "score"].iloc[0]),
            "d10_score": float(s.loc[s.decile == 10, "score"].iloc[0]),
            "d1_lost_on_time": float(s.loc[s.decile == 1, "lost_on_time_rate"].iloc[0]),
            "d10_lost_on_time": float(s.loc[s.decile == 10, "lost_on_time_rate"].iloc[0]),
            "d10_min_share": float(s.loc[s.decile == 10, "min_share_used"].iloc[0]),
            "d1_max_share": float(s.loc[s.decile == 1, "max_share_used"].iloc[0]),
        }
        for tc, s in deciles.groupby("time_control", sort=False)
        if set(s.decile) >= {1, 10}
    }
    return {
        "sample": {
            "month": cfg["source"]["month"],
            "rows_sampled": report["rows_in"],
            "rows_clean": report["rows_out"],
            "distinct_players": int(players),
            "cleaning_rules": report["rules"],
            "checks": {k: v for k, v in report["checks"].items() if not isinstance(v, dict)},
        },
        "overview": overview,
        "results_by_band": by_band[
            [
                "elo_band",
                "n",
                "white_win_rate",
                "white_win_ci_low",
                "white_win_ci_high",
                "draw_rate",
                "black_win_rate",
                "white_score",
                "white_score_ci",
                "expected_score",
            ]
        ].to_dict("records"),  # fmt: skip
        "results_by_tc": by_tc[
            ["tc_label", "n", "white_win_rate", "draw_rate", "black_win_rate", "white_score", "white_score_ci"]
        ].to_dict("records"),  # fmt: skip
        "white_advantage": sql["q2_white_advantage"].to_dict("records"),
        "top_openings": sql["q1_top_openings_by_band"].to_dict("records"),
        "repertoire_shift": sql["q1_repertoire_shift"].to_dict("records"),
        "chi_square": chi.to_dict("records"),
        "calibration_mace": mace,
        "calibration_error_sql": sql["q3_calibration_error"].to_dict("records"),
        "favourite_calibration": sql["q3_favourite_calibration"].to_dict("records"),
        "time_losses": sql["q4_time_losses"].to_dict("records"),
        "time_used_deciles": decile_summary,
        "increment_effect": sql["q4_increment_effect"].to_dict("records"),
        "logit": {"info": logit_info, "terms": logit.to_dict("records")},
        "activity_peak": sql["q5_activity_heatmap"].nlargest(3, "games_per_day").to_dict("records"),
        "activity_low": sql["q5_activity_heatmap"].nsmallest(3, "games_per_day").to_dict("records"),
        "results_by_hour": sql["q5_results_by_hour"].to_dict("records"),
        "night_vs_day": sql["q5_night_vs_day"].to_dict("records"),
        "recommendations": sql["q6_best_openings_per_band"].to_dict("records"),
        "cross_check": checks.to_dict("records"),
    }


def make_figures(
    sql: dict[str, pd.DataFrame],
    by_band: pd.DataFrame,
    chi: pd.DataFrame,
    logit: pd.DataFrame,
    bands: list[str],
    fig_dir: Path,
) -> list[Path]:
    """Render and save the report figures."""
    adv = sql["q2_white_advantage"]
    cells = adv[(adv["elo_band"] != "Toutes") & (adv["time_control"] != "Toutes")]
    losses = sql["q4_time_losses"]
    losses = losses[(losses["elo_band"] != "Toutes") & (losses["time_control"] != "Toutes")]
    figures = [
        ("fig01_results_by_band.png", charts.results_by_band(by_band)),
        ("fig02_top_openings_by_band.png", charts.top_openings(sql["q1_top_openings_by_band"], bands)),
        ("fig03_white_score_band_tc.png", charts.white_score_heatmap(cells)),
        ("fig04_elo_calibration.png", charts.calibration(sql["q3_calibration"])),
        ("fig05_lost_on_time.png", charts.lost_on_time(losses, bands)),
        ("fig06_time_used_deciles.png", charts.time_used_deciles(sql["q4_time_used_deciles"])),
        ("fig07_activity_heatmap.png", charts.activity_heatmap(sql["q5_activity_heatmap"])),
        ("fig08_results_by_hour.png", charts.results_by_hour(sql["q5_results_by_hour"])),
        ("fig09_cramers_v.png", charts.cramers_v(chi)),
        ("fig10_logit_odds_ratios.png", charts.odds_ratios(logit[logit["term"] != "Intercept"])),
    ]
    paths = []
    for name, fig in figures:
        height = 900 if name.startswith("fig02") else 620
        paths.append(charts.save(fig, fig_dir / name, height=height))
    log.info("%d figures written to %s", len(paths), fig_dir)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the statistical analysis.")
    parser.add_argument("--config", help="path to an alternative config.yaml")
    parser.add_argument("--no-figures", action="store_true", help="skip PNG rendering")
    args = parser.parse_args()
    setup_logging()
    run(load_config(args.config) if args.config else None, figures=not args.no_figures)


if __name__ == "__main__":
    main()
