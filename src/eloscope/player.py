"""Personal analysis: compare one player's games with the 2 million-game baseline.

The games come either from the Lichess API (``/api/games/user/{username}``) or from a PGN file
exported by the player. They go through the same parser and cleaning rules as the main pipeline,
then every comparison is made against players of the **same Elo band, time control and colour**
(``app/data/baseline_*.csv``). Nothing is stored: the analysis runs in memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from eloscope.clean import add_derived_columns, apply_exclusions
from eloscope.ingest import hash_username, parse_game, split_pgn

GAMES_URL = "https://lichess.org/api/games/user/{username}"
PERF_TYPES = ("ultraBullet", "bullet", "blitz", "rapid", "classical")
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,29}$")
TC_LABELS = {
    "ultrabullet": "UltraBullet",
    "bullet": "Bullet",
    "blitz": "Blitz",
    "rapid": "Rapide",
    "classical": "Classique",
}
PERIODS = [(0, 5, "nuit"), (6, 11, "matin"), (12, 17, "après-midi"), (18, 23, "soir")]
MIN_PLAYER_GAMES = 10  # minimum games of the player before any comparison or advice
Z_95 = 1.96
# Usernames are only hashed in memory to find the player's colour; this salt never leaves the process.
_SALT = "player-view"


class LichessError(RuntimeError):
    """The Lichess API did not return games (unknown account, rate limit, blocked network…)."""


# --------------------------------------------------------------------------------------
# Loading games
# --------------------------------------------------------------------------------------
def valid_username(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch(username.strip()))


def fetch_user_games(
    username: str,
    max_games: int = 300,
    perf_types: tuple[str, ...] = PERF_TYPES,
    session: requests.Session | None = None,
) -> str:
    """Download the most recent rated games of ``username`` as PGN text (with clocks)."""
    username = username.strip()
    if not valid_username(username):
        raise LichessError("Pseudo invalide : 2 à 30 caractères, lettres, chiffres, « _ » ou « - ».")
    params = {
        "max": max(1, min(int(max_games), 1000)),
        "rated": "true",
        "perfType": ",".join(perf_types),
        "clocks": "true",
        "opening": "true",
        "evals": "false",
    }
    headers = {"Accept": "application/x-chess-pgn", "User-Agent": "64-squares portfolio app"}
    http = session or requests.Session()
    try:
        resp = http.get(GAMES_URL.format(username=username), params=params, headers=headers, timeout=(10, 90))
    except requests.RequestException as exc:
        raise LichessError(f"Lichess est injoignable ({exc.__class__.__name__}).") from exc
    if resp.status_code == 404:
        raise LichessError(
            "Lichess n'a renvoyé aucune partie : compte introuvable, ou export indisponible depuis ce serveur. "
            "Utilisez l'option « Fichier PGN »."
        )
    if resp.status_code == 429:
        raise LichessError("Trop de requêtes vers Lichess : réessayez dans une minute.")
    if resp.status_code != 200:
        raise LichessError(f"Réponse inattendue de Lichess (HTTP {resp.status_code}).")
    if "[Event " not in resp.text:
        raise LichessError("Aucune partie classée trouvée pour ce compte avec ces cadences.")
    return resp.text


def player_games(pgn_text: str | bytes, username: str, config: dict[str, Any]) -> pd.DataFrame:
    """Parse, clean and turn ``username``'s games into one row per game from their point of view."""
    data = pgn_text.encode("utf-8") if isinstance(pgn_text, str) else pgn_text
    games = split_pgn(data.replace(b"\r\n", b"\n"))
    if not games:
        return pd.DataFrame()
    rows = pd.DataFrame([parse_game(g, _SALT, i, config["cleaning"]["opening_moves"]) for i, g in enumerate(games)])
    me = hash_username(username.strip(), _SALT)
    rows = rows[(rows["white_hash"] == me) | (rows["black_hash"] == me)]
    if rows.empty:
        return pd.DataFrame()
    kept, _ = apply_exclusions(rows, config)
    if kept.empty:
        return pd.DataFrame()
    games_df = add_derived_columns(kept, config, None)
    white = games_df["white_hash"] == me
    out = pd.DataFrame(
        {
            "date": games_df["date"],
            "hour": games_df["hour"],
            "color": np.where(white, "white", "black"),
            "elo_band": games_df["elo_band"],
            "tc_category": games_df["tc_category"],
            "tc_label": games_df["tc_category"].map(TC_LABELS),
            "player_elo": np.where(white, games_df["white_elo"], games_df["black_elo"]),
            "opponent_elo": np.where(white, games_df["black_elo"], games_df["white_elo"]),
            "score": np.where(white, games_df["white_score"], 1 - games_df["white_score"]),
            "expected": np.where(white, games_df["expected_score"], 1 - games_df["expected_score"]),
            "lost_on_time": (games_df["time_loser"] == np.where(white, "white", "black")).astype(int),
            "time_used_10": np.where(white, games_df["white_time_used_10"], games_df["black_time_used_10"]),
            "opening_family": games_df["opening_family"],
            "opening": games_df["opening"],
            "termination": games_df["termination"],
        }
    )
    out["period"] = out["hour"].map(period_of)
    return out.reset_index(drop=True)


def period_of(hour: int) -> str:
    for low, high, name in PERIODS:
        if low <= hour <= high:
            return name
    raise ValueError(hour)


# --------------------------------------------------------------------------------------
# Baseline and comparisons
# --------------------------------------------------------------------------------------
@dataclass
class Baseline:
    """Reference tables computed on the 2 million-game sample."""

    results: pd.DataFrame
    time_used: pd.DataFrame
    time_quantiles: pd.DataFrame
    openings: pd.DataFrame
    periods: pd.DataFrame

    @classmethod
    def load(cls, folder: Path) -> Baseline:
        read = lambda name: pd.read_csv(folder / f"baseline_{name}.csv")  # noqa: E731
        return cls(read("results"), read("time_used"), read("time_quantiles"), read("openings"), read("periods"))


@dataclass
class Report:
    """Everything the app displays, computed from the player's games and the baseline."""

    games: int
    main_band: str
    summary: dict[str, float]
    by_tc: pd.DataFrame
    clock: pd.DataFrame
    openings: pd.DataFrame
    periods: pd.DataFrame
    advice: list[str] = field(default_factory=list)


def _weighted_baseline(player: pd.DataFrame, table: pd.DataFrame, keys: list[str], cols: list[str]) -> pd.Series:
    """Baseline values averaged over the player's own mix of (band, time control, colour)."""
    mix = player.groupby(keys).size().rename("n").reset_index()
    merged = mix.merge(table, on=keys, how="inner")
    if merged.empty:
        return pd.Series(np.nan, index=cols)
    return pd.Series({c: np.average(merged[c], weights=merged["n"]) for c in cols})


def percentile_of(value: float, quantiles: pd.DataFrame) -> float:
    """Approximate percentile (0-100) of ``value`` in a distribution given by its quantiles."""
    q = quantiles.sort_values("quantile")
    return float(np.interp(value, q["share_used"], q["quantile"] * 100, left=0, right=100))


def score_at(share: float, curve: pd.DataFrame) -> float:
    """Baseline score of players using ``share`` of their clock in 10 moves (5-point bins)."""
    if curve.empty:
        return float("nan")
    bin_pct = min(int(share * 20), 19) * 5
    row = curve.iloc[(curve["bin_pct"] - bin_pct).abs().argmin()]
    return float(row["score"])


def build_report(player: pd.DataFrame, base: Baseline) -> Report:
    """Compare the player with the baseline: results, clock, openings, time of day, advice."""
    keys = ["elo_band", "tc_category", "color"]
    ref = _weighted_baseline(player, base.results, keys, ["score", "expected", "lost_on_time_rate"])
    summary = {
        "score": player["score"].mean(),
        "expected": player["expected"].mean(),
        "performance": player["score"].mean() - player["expected"].mean(),
        "lost_on_time": player["lost_on_time"].mean(),
        "ref_score": ref["score"],
        "ref_lost_on_time": ref["lost_on_time_rate"],
        "rating": float(player.sort_values("date")["player_elo"].iloc[-1]) if len(player) else np.nan,
    }

    # Results and losses on time per time control, against the same mix of bands and colours
    rows = []
    for tc, sub in player.groupby("tc_category", sort=False):
        r = _weighted_baseline(sub, base.results, keys, ["score", "lost_on_time_rate"])
        rows.append(
            {
                "tc_category": tc,
                "tc_label": TC_LABELS[tc],
                "games": len(sub),
                "score": sub["score"].mean(),
                "ref_score": r["score"],
                "lost_on_time": sub["lost_on_time"].mean(),
                "ref_lost_on_time": r["lost_on_time_rate"],
            }
        )
    by_tc = pd.DataFrame(rows).sort_values("games", ascending=False).reset_index(drop=True)

    # Clock: average share of the base time used in the first 10 moves, and its percentile
    clock_rows = []
    timed = player.dropna(subset=["time_used_10"])
    for tc, sub in timed.groupby("tc_category", sort=False):
        quantiles = base.time_quantiles[base.time_quantiles["tc_category"] == tc]
        if quantiles.empty:
            continue
        median = float(quantiles.loc[(quantiles["quantile"] - 0.5).abs().idxmin(), "share_used"])
        avg = float(sub["time_used_10"].median())
        curve = base.time_used[base.time_used["tc_category"] == tc]
        clock_rows.append(
            {
                "tc_category": tc,
                "tc_label": TC_LABELS[tc],
                "games": len(sub),
                "median_share": avg,
                "ref_median_share": median,
                "percentile": percentile_of(avg, quantiles),
                "ref_score_at_you": score_at(avg, curve),
                "ref_score_at_median": score_at(median, curve),
            }
        )
    clock = pd.DataFrame(clock_rows)

    # Openings: the player's families vs players of the same band and colour
    main_band = player["elo_band"].mode().iloc[0]
    fam = (
        player.groupby(["color", "opening_family"])
        .agg(games=("score", "size"), score=("score", "mean"), expected=("expected", "mean"))
        .reset_index()
    )
    fam["score_vs_expected"] = fam["score"] - fam["expected"]
    ref_open = base.openings[base.openings["elo_band"] == main_band][
        ["color", "opening_family", "score", "score_vs_expected"]
    ].rename(columns={"score": "ref_score", "score_vs_expected": "ref_score_vs_expected"})
    openings = fam.merge(ref_open, on=["color", "opening_family"], how="left")
    openings = openings.sort_values(["games", "score"], ascending=False).reset_index(drop=True)

    # Time of day (UTC)
    per = (
        player.groupby(["tc_category", "period"])
        .agg(games=("score", "size"), lost_on_time=("lost_on_time", "mean"), score=("score", "mean"))
        .reset_index()
        .merge(
            base.periods.rename(
                columns={"lost_on_time_rate": "ref_lost_on_time", "score": "ref_score", "player_games": "ref_games"}
            ),
            on=["tc_category", "period"],
            how="left",
        )
    )
    report = Report(len(player), main_band, summary, by_tc, clock, openings, per)
    report.advice = advice(report)
    return report


def beyond_noise(diff: float, n: int, p: float = 0.5) -> bool:
    """True when ``diff`` exceeds the 95 % sampling margin of a rate ``p`` measured on ``n`` games.

    With p = 0.5 this is also a conservative margin for a mean score (standard deviation <= 0.5).
    """
    if n < MIN_PLAYER_GAMES or not np.isfinite(diff):
        return False
    return abs(diff) > Z_95 * np.sqrt(max(p * (1 - p), 0.01) / n)


def advice(report: Report) -> list[str]:
    """Plain-language recommendations derived from the comparisons (French)."""
    tips: list[str] = []
    s = report.summary
    gap = s["lost_on_time"] - s["ref_lost_on_time"]
    if gap > 0.03 and beyond_noise(gap, report.games, s["ref_lost_on_time"]):
        tips.append(
            f"Tu perds **{s['lost_on_time']:.0%}** de tes parties au temps, contre {s['ref_lost_on_time']:.0%} "
            "pour les joueurs de ton niveau aux mêmes cadences : joue avec incrément et garde des réserves."
        )
    for _, row in report.clock.iterrows():
        slower_costs = row["ref_score_at_median"] - row["ref_score_at_you"] >= 0.02
        if row["games"] >= MIN_PLAYER_GAMES and row["percentile"] >= 75 and slower_costs:
            tips.append(
                f"En {row['tc_label']}, tu consommes {row['median_share']:.0%} de ton temps sur les 10 premiers coups "
                f"(plus que {row['percentile']:.0f} % des joueurs ; médiane {row['ref_median_share']:.0%}). "
                f"Sur 2 millions de parties, les joueurs à ce rythme marquent {row['ref_score_at_you']:.0%} contre "
                f"{row['ref_score_at_median']:.0%} au rythme médian : prépare tes ouvertures pour les jouer plus vite."
            )
    playable = report.openings[
        [beyond_noise(d, n) for d, n in zip(report.openings["score_vs_expected"], report.openings["games"])]
    ]
    if not playable.empty:
        best = playable.sort_values("score_vs_expected", ascending=False).iloc[0]
        worst = playable.sort_values("score_vs_expected").iloc[0]
        side = {"white": "avec les Blancs", "black": "avec les Noirs"}
        if best["score_vs_expected"] > 0:
            tips.append(
                f"Ton point fort : **{best['opening_family']}** {side[best['color']]} "
                f"({best['score']:.0%} de score sur {best['games']} parties, "
                f"{best['score_vs_expected']:+.0%} par rapport à ton classement)."
            )
        if worst["score_vs_expected"] < 0 and worst["opening_family"] != best["opening_family"]:
            tips.append(
                f"À retravailler : **{worst['opening_family']}** {side[worst['color']]} "
                f"({worst['score']:.0%} de score sur {worst['games']} parties, "
                f"{worst['score_vs_expected']:+.0%} par rapport à ton classement)."
            )
    if beyond_noise(s["performance"], report.games):
        direction = "au-dessus" if s["performance"] > 0 else "en dessous"
        tips.append(
            f"Tu marques {abs(s['performance']):.0%} {direction} de ce que prédit ton classement face à tes "
            f"adversaires : ton classement devrait {'monter' if s['performance'] > 0 else 'baisser'}."
        )
    night = report.periods[(report.periods["period"] == "nuit") & (report.periods["games"] >= MIN_PLAYER_GAMES)]
    day = report.periods[(report.periods["period"] != "nuit") & (report.periods["games"] >= MIN_PLAYER_GAMES)]
    if not night.empty and not day.empty:
        n_rate = np.average(night["lost_on_time"], weights=night["games"])
        d_rate = np.average(day["lost_on_time"], weights=day["games"])
        n_night = int(night["games"].sum())
        if n_rate > d_rate and beyond_noise(n_rate - d_rate, n_night, d_rate):
            tips.append(
                f"La nuit (0h–5h UTC), tu perds au temps {n_rate:.0%} de tes parties contre {d_rate:.0%} en journée."
            )
    if not tips:
        tips.append(
            "Aucun écart net avec les joueurs de ton niveau sur ces parties (les différences restent dans la "
            "marge d'erreur). Analyse davantage de parties pour affiner."
        )
    return tips
