"""Cleaning rules: turn the raw sampled games into an analysis-ready table.

Every exclusion rule is applied in a fixed order and logged with the number of rows before
and after, so ``docs/methodology.md`` can report the exact impact of each rule. Derived columns
(time-control category, Elo band, rating gap bucket, opening family, results, clock features)
are added once the exclusions are done.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from eloscope.openings import load_reference, map_families, opening_family, opening_variation
from eloscope.settings import load_config, project_path, setup_logging

log = logging.getLogger("eloscope.clean")

VALID_RESULTS = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}
STANDARD_SPEEDS = ("UltraBullet", "Bullet", "Blitz", "Rapid", "Classical", "Correspondence")
TC_ORDER = ["ultrabullet", "bullet", "blitz", "rapid", "classical"]
WEEKDAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


@dataclass
class RuleResult:
    """Row counts of one cleaning rule."""

    rule: str
    description: str
    rows_before: int
    rows_after: int

    @property
    def removed(self) -> int:
        return self.rows_before - self.rows_after


# --------------------------------------------------------------------------------------
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------------------
def parse_time_control(value: str | None) -> tuple[int, int] | None:
    """Parse ``"base+increment"`` (seconds) into integers; ``None`` for ``-`` or invalid values."""
    if not isinstance(value, str) or "+" not in value:
        return None
    base, _, increment = value.partition("+")
    if not (base.isdigit() and increment.isdigit()):
        return None
    return int(base), int(increment)


def categorize_time_control(base: int, increment: int) -> str:
    """Lichess speed category from the estimated duration ``base + 40 * increment`` (seconds)."""
    estimated = base + 40 * increment
    if estimated < 30:
        return "ultrabullet"
    if estimated < 180:
        return "bullet"
    if estimated < 480:
        return "blitz"
    if estimated < 1500:
        return "rapid"
    return "classical"


def elo_band(avg_elo: float, bands: list[list[Any]]) -> str | None:
    """Label of the band ``[label, low, high)`` containing ``avg_elo``."""
    for label, low, high in bands:
        if low <= avg_elo < high:
            return label
    return None


def rating_gap_bucket(gap: pd.Series | np.ndarray | float, width: int = 50, cap: int = 600) -> Any:
    """Round the rating gap (White - Black) to the nearest multiple of ``width``, capped at ±``cap``.

    Buckets are centred: bucket 0 holds gaps in [-25, 25), bucket 50 holds [25, 75), etc.
    """
    bucket = width * np.floor(np.asarray(gap, dtype=float) / width + 0.5)
    bucket = np.clip(bucket, -cap, cap)
    if isinstance(gap, pd.Series):
        return pd.Series(bucket.astype(int), index=gap.index)
    return int(bucket) if np.ndim(bucket) == 0 else bucket.astype(int)


def expected_score(gap: Any) -> Any:
    """Elo expected score of White: ``1 / (1 + 10^(-gap/400))``."""
    return 1.0 / (1.0 + np.power(10.0, -np.asarray(gap, dtype=float) / 400.0))


def is_rated_standard(event: pd.Series, variant: pd.Series) -> pd.Series:
    """Rated games of standard chess (no variant, no casual game)."""
    speed = event.fillna("").str.extract(r"^Rated (\w+) ", expand=False)
    no_variant = variant.isna() | variant.fillna("").str.lower().eq("standard")
    return speed.isin(STANDARD_SPEEDS).fillna(False) & no_variant


def clock_features(
    clk_start: pd.Series, clk_10: pd.Series, base: pd.Series, increment: pd.Series, moves: int = 10
) -> pd.DataFrame:
    """Time used in the first ``moves`` moves, in seconds and as a share of the base time.

    On Lichess the first move does not consume clock time and does not add the increment, so
    the time used up to move ``moves`` is ``clk_start + (moves - 1) * inc - clk_moves``. In a
    tournament berserk the start clock is halved and the increment removed: the share is then
    computed against the halved clock. Games with a zero base time get no share.
    """
    berserk = clk_start.notna() & (base > 0) & (clk_start < 0.75 * base)
    eff_increment = increment.where(~berserk, 0)
    used = (clk_start + (moves - 1) * eff_increment - clk_10).clip(lower=0)
    denominator = base.where(~berserk, base / 2).astype(float).where(base > 0)
    share = (used / denominator).clip(upper=1.0)
    return pd.DataFrame({"time_used": used, "time_share": share, "berserk": berserk}, index=clk_start.index)


# --------------------------------------------------------------------------------------
# Rule engine
# --------------------------------------------------------------------------------------
def apply_exclusions(df: pd.DataFrame, cfg: dict[str, Any]) -> tuple[pd.DataFrame, list[RuleResult]]:
    """Apply the exclusion rules in order and return the kept rows plus a log of counts."""
    c = cfg["cleaning"]
    white_elo = pd.to_numeric(df["white_elo"], errors="coerce")
    black_elo = pd.to_numeric(df["black_elo"], errors="coerce")
    tc = df["time_control"].map(parse_time_control)

    rules: list[tuple[str, str, Callable[[pd.DataFrame], pd.Series]]] = [
        ("R0", "Duplicate game ids removed", lambda d: ~d["game_id"].duplicated() & d["game_id"].notna()),
        (
            "R1",
            "Rated standard games only (no variant, no casual)",
            lambda d: is_rated_standard(d["event"], d["variant"]),
        ),
        (
            "R2",
            f"Termination in {c['keep_terminations']} and a valid result",
            lambda d: d["termination"].isin(c["keep_terminations"]) & d["result"].isin(VALID_RESULTS),
        ),
        ("R3", f"At least {c['min_plies']} plies", lambda d: d["plies"] >= c["min_plies"]),
        (
            "R4",
            "No BOT account on either side",
            lambda d: ~(d["white_title"].fillna("").eq("BOT") | d["black_title"].fillna("").eq("BOT")),
        ),
        (
            "R5",
            f"Both ratings present, numeric and within {c['rating_min']}-{c['rating_max']}",
            lambda d: (
                white_elo.loc[d.index].between(c["rating_min"], c["rating_max"])
                & black_elo.loc[d.index].between(c["rating_min"], c["rating_max"])
            ),
        ),
        ("R6", "Valid base+increment time control (correspondence excluded)", lambda d: tc.loc[d.index].notna()),
    ]

    results: list[RuleResult] = []
    current = df
    for rule, description, predicate in rules:
        before = len(current)
        current = current[predicate(current).fillna(False).to_numpy(dtype=bool)]
        results.append(RuleResult(rule, description, before, len(current)))
        log.info(
            "%s %-70s %10s -> %10s (-%s)",
            rule,
            description[:70],
            f"{before:,}",
            f"{len(current):,}",
            f"{before - len(current):,}",
        )
    return current.copy(), results


def add_derived_columns(df: pd.DataFrame, cfg: dict[str, Any], reference: pd.DataFrame | None) -> pd.DataFrame:
    """Add every analysis column (rules 6-10 of the methodology)."""
    c = cfg["cleaning"]
    out = df.copy()

    # Ratings
    out["white_elo"] = pd.to_numeric(out["white_elo"]).astype("int32")
    out["black_elo"] = pd.to_numeric(out["black_elo"]).astype("int32")
    out["white_rating_diff"] = pd.to_numeric(out["white_rating_diff"], errors="coerce").astype("Int32")
    out["black_rating_diff"] = pd.to_numeric(out["black_rating_diff"], errors="coerce").astype("Int32")

    # Rule 6: time control
    tc = out["time_control"].map(parse_time_control)
    out["tc_base"] = tc.map(lambda t: t[0]).astype("int32")
    out["tc_increment"] = tc.map(lambda t: t[1]).astype("int32")
    out["tc_estimated"] = out["tc_base"] + 40 * out["tc_increment"]
    out["tc_category"] = [categorize_time_control(b, i) for b, i in zip(out["tc_base"], out["tc_increment"])]
    out["event_speed"] = out["event"].str.extract(r"^Rated (\w+) ", expand=False).str.lower()

    # Rule 7: Elo band and rating gap
    out["avg_elo"] = (out["white_elo"] + out["black_elo"]) / 2
    labels = [b[0] for b in c["elo_bands"]]
    edges = [b[1] for b in c["elo_bands"]] + [c["elo_bands"][-1][2]]
    out["elo_band"] = pd.cut(out["avg_elo"], bins=edges, labels=labels, right=False).astype("string")
    out["rating_gap"] = (out["white_elo"] - out["black_elo"]).astype("int32")
    out["rating_gap_bucket"] = rating_gap_bucket(out["rating_gap"], c["rating_gap_bucket"], c["rating_gap_cap"])
    out["expected_score"] = expected_score(out["rating_gap"])

    # Rule 8: opening family
    out["opening"] = out["opening"].fillna("?")
    out["eco"] = out["eco"].fillna("?")
    if reference is not None:
        mapped = map_families(out["opening"], reference)
        out["opening_family"] = mapped["opening_family"]
        out["opening_in_reference"] = mapped["in_reference"]
    else:
        out["opening_family"] = out["opening"].map(opening_family)
        out["opening_in_reference"] = pd.NA
    out["opening_variation"] = out["opening"].map(opening_variation)

    # Rule 9: results
    out["white_score"] = out["result"].map(VALID_RESULTS).astype(float)
    out["winner"] = out["result"].map({"1-0": "white", "0-1": "black", "1/2-1/2": "draw"})
    out["lost_on_time"] = out["termination"].eq("Time forfeit") & out["winner"].ne("draw")
    out["time_loser"] = np.where(out["lost_on_time"], np.where(out["winner"].eq("white"), "black", "white"), None)

    # Dates
    out["date"] = pd.to_datetime(out["utc_date"], format="%Y.%m.%d").dt.date
    timestamp = pd.to_datetime(out["utc_date"] + " " + out["utc_time"], format="%Y.%m.%d %H:%M:%S")
    out["hour"] = timestamp.dt.hour.astype("int8")
    out["weekday"] = timestamp.dt.weekday.astype("int8")  # 0 = Monday

    # Rule 10: clock features (only when clock data exists)
    moves = c["opening_moves"]
    out["has_clock"] = out["n_clocks"].eq(out["plies"]) & out["n_clocks"].gt(0)
    for side in ("white", "black"):
        feats = clock_features(
            out[f"{side}_clk_start"], out[f"{side}_clk_10"], out["tc_base"], out["tc_increment"], moves
        )
        out[f"{side}_time_used_10_s"] = feats["time_used"]
        out[f"{side}_time_used_10"] = feats["time_share"]
        out[f"{side}_berserk"] = feats["berserk"]

    keep = [
        "game_id",
        "game_index",
        "date",
        "hour",
        "weekday",
        "event",
        "event_speed",
        "white_hash",
        "black_hash",
        "white_title",
        "black_title",
        "white_elo",
        "black_elo",
        "avg_elo",
        "elo_band",
        "rating_gap",
        "rating_gap_bucket",
        "expected_score",
        "white_rating_diff",
        "black_rating_diff",
        "eco",
        "opening",
        "opening_family",
        "opening_variation",
        "opening_in_reference",
        "time_control",
        "tc_base",
        "tc_increment",
        "tc_estimated",
        "tc_category",
        "result",
        "white_score",
        "winner",
        "termination",
        "lost_on_time",
        "time_loser",
        "plies",
        "has_clock",
        "has_eval",
        "white_clk_10",
        "black_clk_10",
        "white_time_used_10_s",
        "black_time_used_10_s",
        "white_time_used_10",
        "black_time_used_10",
        "white_berserk",
        "black_berserk",
    ]
    return out[keep].reset_index(drop=True)


def load_sample(cfg: dict[str, Any]) -> pd.DataFrame:
    """Read all Parquet batches of the configured month."""
    folder = project_path("sample", cfg) / cfg["source"]["month"]
    files = sorted(folder.glob("batch_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no sampled batches in {folder}; run the ingest step first")
    return pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)


def run(config: dict[str, Any] | None = None) -> pd.DataFrame:
    """Clean the sample and write ``data/processed/games_clean.parquet`` plus the rule log."""
    cfg = config or load_config()
    raw = load_sample(cfg)
    log.info("loaded %s sampled games", f"{len(raw):,}")
    reference = load_reference(cfg)

    kept, rules = apply_exclusions(raw, cfg)
    clean = add_derived_columns(kept, cfg, reference)

    processed = project_path("processed", cfg)
    clean.to_parquet(processed / "games_clean.parquet", index=False, compression="zstd")

    speed_agreement = float((clean["event_speed"] == clean["tc_category"]).mean())
    report = {
        "month": cfg["source"]["month"],
        "rows_in": len(raw),
        "rows_out": len(clean),
        "rules": [asdict(r) | {"removed": r.removed} for r in rules],
        "checks": {
            "event_speed_matches_tc_category": round(speed_agreement, 6),
            "opening_name_in_reference": round(float(clean["opening_in_reference"].mean()), 6),
            "has_clock": round(float(clean["has_clock"].mean()), 6),
            "has_time_used_10": round(float(clean["white_time_used_10"].notna().mean()), 6),
            "has_eval": round(float(clean["has_eval"].mean()), 6),
            "berserk_any": round(float((clean["white_berserk"] | clean["black_berserk"]).mean()), 6),
            "terminations_raw": raw["termination"].value_counts(dropna=False).to_dict(),
            "events_raw": raw["event"].str.extract(r"^(\w+ \w+)", expand=False).value_counts(dropna=False).to_dict(),
        },
    }
    (processed / "cleaning_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    log.info("clean table: %s rows (%.1f%% of the sample kept)", f"{len(clean):,}", 100 * len(clean) / len(raw))
    log.info("event speed agrees with the time-control rule for %.3f%% of games", 100 * speed_agreement)
    return clean


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the cleaning rules to the sampled games.")
    parser.add_argument("--config", help="path to an alternative config.yaml")
    args = parser.parse_args()
    setup_logging()
    run(load_config(args.config) if args.config else None)


if __name__ == "__main__":
    main()
