"""Plotly chart builders with one consistent, chessboard-inspired visual style (French labels)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

# Colours. Chrome (paper, ink, grid) carries the chessboard identity; data colours are checked
# for colour-vision deficiency, lightness band and contrast (see docs/design.md).
INK = "#262421"  # primary text
INK_2 = "#5c574f"  # secondary text
MUTED = "#8a847b"  # axis labels, notes, reference lines
DARK_SQUARE = "#b58863"  # Lichess dark square: single-series accent
LIGHT_SQUARE = "#f0d9b5"  # Lichess light square: chrome only, never a data colour
PAPER = "#ffffff"
GRID = "#e9e4dc"

# Categorical slots, fixed order (never cycled). Time controls take them by speed.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
TC_COLORS = dict(zip(["UltraBullet", "Bullet", "Blitz", "Rapide", "Classique"], SERIES))
# Results are a polarity: White pole (warm) / neutral draw / Black pole (cool).
WHITE_POLE, DRAW_MID, BLACK_POLE = "#c8732a", "#d3d1cb", "#2a5a9a"
RESULT_COLORS = {"Victoire Blancs": WHITE_POLE, "Nulle": DRAW_MID, "Victoire Noirs": BLACK_POLE}
# Elo bands are ordered: one brown ramp, light to dark (ordinal check passed).
BAND_COLORS = dict(zip(["< 1200", "1200-1599", "1600-1999", "2000+"], ["#d2a679", "#b07d4f", "#86562d", "#5a3518"]))
SEQUENTIAL = [[0.0, "#f7f1e8"], [0.35, "#d2a679"], [0.7, "#86562d"], [1.0, "#4a2b12"]]
DIVERGING = [[0.0, BLACK_POLE], [0.5, "#f0efec"], [1.0, WHITE_POLE]]  # < 50 % Black, > 50 % White

pio.templates["eloscope"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family="Segoe UI, Helvetica Neue, Arial, sans-serif", size=13, color=INK),
        title=dict(font=dict(size=18, color=INK), x=0.01, xanchor="left"),
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        colorway=SERIES,
        xaxis=dict(gridcolor=GRID, linecolor="#CFC8BC", zeroline=False, ticks="outside", tickcolor="#CFC8BC"),
        yaxis=dict(gridcolor=GRID, linecolor="#CFC8BC", zeroline=False),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        margin=dict(l=80, r=40, t=125, b=105),
    )
)
pio.templates.default = "eloscope"

SOURCE_NOTE = "Source : Lichess, parties classées standard, septembre 2026 (échantillon aléatoire)"


def _finish(fig: go.Figure, title: str, subtitle: str | None = None) -> go.Figure:
    text = f"<b>{title}</b>" + (f"<br><span style='font-size:13px;color:#6B655D'>{subtitle}</span>" if subtitle else "")
    fig.update_layout(title=dict(text=text))
    fig.add_annotation(
        text=SOURCE_NOTE, xref="paper", yref="paper", x=1, y=0, yshift=-80, showarrow=False,
        font=dict(size=10, color="#8A847B"), xanchor="right", yanchor="top",
    )  # fmt: skip
    return fig


def save(fig: go.Figure, path: Path, width: int = 1100, height: int = 620) -> Path:
    """Write a figure as PNG (needs kaleido and a Chrome/Chromium install)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(path, width=width, height=height, scale=2)
    return path


def _end_labels(
    fig: go.Figure,
    points: list[tuple[float, float, str]],
    min_gap: float,
    row: int | None = None,
    col: int | None = None,
) -> None:
    """Direct labels at line ends (identity never relies on colour alone), nudged apart vertically."""
    kwargs = {"row": row, "col": col} if row else {}
    placed: list[float] = []
    for x, y, text in sorted(points, key=lambda p: p[1]):
        y_label = max([y, *[p + min_gap for p in placed]]) if placed else y
        placed.append(y_label)
        fig.add_annotation(
            x=x, y=y_label, text=text, showarrow=False, xanchor="left", xshift=8,
            font=dict(size=11, color=INK_2), **kwargs,
        )  # fmt: skip


def results_by_band(df: pd.DataFrame) -> go.Figure:
    """Stacked 100 % bars of White win / draw / Black win per Elo band."""
    fig = go.Figure()
    for col, label in [
        ("white_win_rate", "Victoire Blancs"),
        ("draw_rate", "Nulle"),
        ("black_win_rate", "Victoire Noirs"),
    ]:
        fig.add_bar(
            x=df["elo_band"], y=df[col], name=label, marker_color=RESULT_COLORS[label],
            marker_line=dict(color=PAPER, width=2), text=[f"{v:.1%}" for v in df[col]], textposition="inside",
            insidetextfont=dict(color=INK if label == "Nulle" else "white"),
            hovertemplate=f"{label}<br>%{{x}} : %{{y:.1%}}<extra></extra>",
        )  # fmt: skip
    fig.update_layout(
        barmode="stack", bargap=0.35, uniformtext=dict(minsize=12, mode="show"),
        yaxis=dict(tickformat=".0%", title="Part des parties"), xaxis_title="Tranche Elo",
    )  # fmt: skip
    return _finish(fig, "Répartition des résultats par niveau", "Les Blancs gagnent plus souvent à tous les niveaux")


def top_openings(df: pd.DataFrame, bands: list[str], top: int = 10) -> go.Figure:
    """Top opening families per band: popularity (bar length) coloured by White's score around 50 %."""
    fig = make_subplots(
        rows=2, cols=2, subplot_titles=[f"Elo {b}" for b in bands], horizontal_spacing=0.3, vertical_spacing=0.1
    )
    spread = float((df["white_score"] - 0.5).abs().max())
    for i, band in enumerate(bands):
        sub = df[df["elo_band"] == band].nsmallest(top, "popularity_rank").iloc[::-1]
        fig.add_bar(
            x=sub["share_of_band"], y=sub["opening_family"], orientation="h", row=i // 2 + 1, col=i % 2 + 1,
            marker=dict(color=sub["white_score"], colorscale=DIVERGING, cmin=0.5 - spread, cmax=0.5 + spread,
                        colorbar=dict(title="Score<br>Blancs", tickformat=".0%") if i == 0 else None,
                        showscale=i == 0, line=dict(color=PAPER, width=2)),
            text=[f"{s:.1%}" for s in sub["share_of_band"]], textposition="outside", showlegend=False,
            customdata=sub["white_score"],
            hovertemplate="%{y}<br>%{x:.1%} des parties<br>score des Blancs %{customdata:.1%}<extra></extra>",
        )  # fmt: skip
    fig.update_xaxes(
        tickformat=".0%", showgrid=False, showticklabels=False, range=[0, df["share_of_band"].max() * 1.22]
    )
    fig.update_yaxes(tickfont=dict(size=11), automargin=True)
    fig.update_layout(margin=dict(l=190), bargap=0.25)
    return _finish(
        fig,
        "Ouvertures les plus jouées par niveau",
        "Longueur = part des parties de la tranche ; couleur = score des Blancs (brun > 50 %, bleu < 50 %)",
    )


def white_score_heatmap(df: pd.DataFrame) -> go.Figure:
    """Heatmap of White's score by Elo band (rows) and time control (columns)."""
    tc_order = [c for c in TC_COLORS if c in set(df["time_control"])]
    band_order = [b for b in BAND_COLORS if b in set(df["elo_band"])]
    pivot = df.pivot(index="elo_band", columns="time_control", values="white_score").reindex(
        index=band_order, columns=tc_order
    )
    counts = df.pivot(index="elo_band", columns="time_control", values="games").reindex(
        index=band_order, columns=tc_order
    )
    text = [
        [f"<b>{v:.1%}</b><br>n = {n:,.0f}".replace(",", " ") if pd.notna(v) else "n < min" for v, n in zip(rv, rn)]
        for rv, rn in zip(pivot.values, counts.values)
    ]
    spread = float(np.nanmax(np.abs(pivot.values - 0.5)))
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            text=text,
            texttemplate="%{text}",
            textfont=dict(size=14, color=INK),
            colorscale=DIVERGING,
            zmin=0.5 - spread,
            zmax=0.5 + spread,
            colorbar=dict(title="Score", tickformat=".0%"),
            xgap=2,
            ygap=2,
            hovertemplate="%{y} · %{x}<br>score des Blancs %{z:.1%}<extra></extra>",
        )  # fmt: skip
    )
    fig.update_layout(xaxis_title="Cadence", yaxis=dict(title=dict(text="Tranche Elo", standoff=18), automargin=True))
    return _finish(
        fig,
        "Score moyen des Blancs par niveau et cadence",
        "50 % = pas d'avantage ; brun = avantage Blancs ; cellules sous le minimum d'échantillon masquées",
    )


def calibration(df: pd.DataFrame) -> go.Figure:
    """Expected (Elo formula) vs actual White score by rating-gap bucket, one line per time control."""
    fig = go.Figure()
    gaps = np.arange(-600, 601, 10)
    fig.add_scatter(
        x=gaps, y=1 / (1 + 10 ** (-gaps / 400)), name="Formule Elo (attendu)", mode="lines",
        line=dict(color=MUTED, dash="dash", width=2), hovertemplate="écart %{x}<br>attendu %{y:.1%}<extra></extra>",
    )  # fmt: skip
    ends: list[tuple[float, float, str]] = []
    for tc, sub in df.groupby("time_control", sort=False):
        fig.add_scatter(
            x=sub["rating_gap_bucket"], y=sub["actual_score"], name=tc, mode="lines+markers",
            line=dict(color=TC_COLORS.get(tc, INK), width=2), marker=dict(size=8, line=dict(color=PAPER, width=2)),
            hovertemplate=f"{tc}<br>écart %{{x}}<br>score réel %{{y:.1%}}<extra></extra>",
        )  # fmt: skip
        last = sub.iloc[-1]
        ends.append((last["rating_gap_bucket"], last["actual_score"], tc))
    right_edge = max(x for x, _, _ in ends)
    # lines stopping early (rare time controls) would be labelled on top of others: the legend covers them
    _end_labels(fig, [p for p in ends if p[0] == right_edge], min_gap=0.035)
    fig.update_layout(
        xaxis=dict(title="Écart Elo (Blancs − Noirs), tranches de 50 points", dtick=100),
        yaxis=dict(title="Score des Blancs", tickformat=".0%", range=[0, 1]),
    )
    return _finish(fig, "Le classement prédit-il le résultat ?", "Score réel vs score attendu par la formule Elo")


def lost_on_time(df: pd.DataFrame, bands: list[str]) -> go.Figure:
    """Grouped bars of the share of games lost on time by time control and Elo band."""
    fig = go.Figure()
    for band in bands:
        sub = df[df["elo_band"] == band]
        fig.add_bar(
            x=sub["time_control"], y=sub["lost_on_time_rate"], name=f"Elo {band}", marker_color=BAND_COLORS[band],
            marker_line=dict(color=PAPER, width=2), text=[f"{v:.0%}" for v in sub["lost_on_time_rate"]],
            textposition="outside", textfont=dict(color=INK_2),
            hovertemplate=f"Elo {band}<br>%{{x}} : %{{y:.1%}} perdues au temps<extra></extra>",
        )  # fmt: skip
    order = [c for c in TC_COLORS if c in set(df["time_control"])]
    fig.update_layout(
        barmode="group",
        bargap=0.25,
        yaxis=dict(title="Part des parties perdues au temps", tickformat=".0%"),
        xaxis=dict(title="Cadence", categoryorder="array", categoryarray=order),
    )
    return _finish(
        fig, "Défaites au temps par cadence et niveau", "Part des parties terminées par une chute du drapeau"
    )


def time_used_deciles(df: pd.DataFrame) -> go.Figure:
    """Player score by decile of clock share used in the first 10 moves, per time control."""
    fig = make_subplots(
        rows=1, cols=2, subplot_titles=["Score du joueur", "Part des parties perdues au temps"], horizontal_spacing=0.12
    )
    ends: dict[int, list[tuple[float, float, str]]] = {1: [], 2: []}
    for tc, sub in df.groupby("time_control", sort=False):
        color = TC_COLORS.get(tc, INK)
        for col, metric in ((1, "score"), (2, "lost_on_time_rate")):
            fig.add_scatter(
                x=sub["decile"], y=sub[metric], name=tc, mode="lines+markers", legendgroup=tc, showlegend=col == 1,
                line=dict(color=color, width=2), marker=dict(size=8, line=dict(color=PAPER, width=2)),
                hovertemplate=f"{tc}<br>décile %{{x}} : %{{y:.1%}}<extra></extra>", row=1, col=col,
            )  # fmt: skip
            last = sub.iloc[-1]
            ends[col].append((last["decile"], last[metric], tc))
    for col, points in ends.items():
        span = max(p[1] for p in points) - min(p[1] for p in points)
        _end_labels(fig, points, min_gap=max(span, 0.1) * 0.08, row=1, col=col)
    fig.update_xaxes(
        title="Décile de temps consommé (1 = le plus rapide)", tickvals=list(range(1, 11)), range=[0.5, 11.8]
    )
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(legend=dict(y=-0.2, yanchor="top"), margin=dict(b=150))
    return _finish(
        fig,
        "Trop réfléchir dans l'ouverture coûte cher",
        "Joueurs classés par part de leur temps de base utilisée sur 10 coups",
    )


def activity_heatmap(df: pd.DataFrame) -> go.Figure:
    """Average games per day by weekday (rows) and UTC hour (columns)."""
    pivot = df.pivot(index="weekday", columns="hour", values="games_per_day")
    order = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    pivot = pivot.reindex([d for d in order if d in pivot.index])
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            colorscale=SEQUENTIAL,
            xgap=2,
            ygap=2,
            colorbar=dict(title="Parties<br>par jour"),
            hovertemplate="%{y} %{x}h<br>%{z:,.0f} parties par jour<extra></extra>",
        )  # fmt: skip
    )
    fig.update_layout(xaxis=dict(title="Heure (UTC)", dtick=1), yaxis=dict(title="", autorange="reversed"))
    return _finish(
        fig, "Quand joue-t-on ?", "Nombre moyen de parties de l'échantillon par jour, selon le jour et l'heure (UTC)"
    )


def results_by_hour(df: pd.DataFrame) -> go.Figure:
    """Two stacked panels sharing the hour axis (never a dual-axis chart): losses on time, White score."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
        subplot_titles=["Part des parties perdues au temps", "Score des Blancs (axe de 45 % à 55 %)"],
    )  # fmt: skip
    fig.add_scatter(
        x=df["hour"], y=df["lost_on_time_rate"], name="Perdues au temps", mode="lines+markers", showlegend=False,
        line=dict(color=DARK_SQUARE, width=2), marker=dict(size=8, line=dict(color=PAPER, width=2)),
        hovertemplate="%{x}h : %{y:.1%} perdues au temps<extra></extra>", row=1, col=1,
    )  # fmt: skip
    fig.add_scatter(
        x=df["hour"], y=df["white_score"], name="Score des Blancs", mode="lines+markers", showlegend=False,
        line=dict(color=WHITE_POLE, width=2), marker=dict(size=8, line=dict(color=PAPER, width=2)),
        hovertemplate="%{x}h : score des Blancs %{y:.1%}<extra></extra>", row=2, col=1,
    )  # fmt: skip
    low, high = df["lost_on_time_rate"].min(), df["lost_on_time_rate"].max()
    pad = (high - low) * 0.5
    fig.update_yaxes(tickformat=".0%", range=[low - pad, high + pad], row=1, col=1)
    fig.update_yaxes(tickformat=".0%", range=[0.45, 0.55], row=2, col=1)
    fig.update_xaxes(dtick=1, range=[-0.5, 23.5])
    fig.update_xaxes(title_text="Heure (UTC)", row=2, col=1)
    return _finish(
        fig, "Résultats selon l'heure de la partie",
        "Les défaites au temps augmentent la nuit ; le score des Blancs ne bouge pas (toutes cadences, UTC)",
    )  # fmt: skip


def cramers_v(df: pd.DataFrame) -> go.Figure:
    """Cramér's V (opening family x result) per Elo band."""
    fig = go.Figure(go.Bar(
        x=df["elo_band"], y=df["cramers_v"], marker_color=DARK_SQUARE, textfont=dict(color=INK_2),
        text=[f"V = {v:.3f}<br>p = {p:.1e}" for v, p in zip(df["cramers_v"], df["p_value"])], textposition="outside",
        hovertemplate="%{x}<br>V de Cramér %{y:.3f}<extra></extra>",
    ))  # fmt: skip
    fig.add_hline(
        y=0.1,
        line=dict(color=MUTED, dash="dot"),
        annotation_text="Seuil d'effet « faible » (0,1)",
        annotation_position="top left",
        annotation_font_color=INK_2,
    )
    fig.update_layout(
        bargap=0.45,
        yaxis=dict(title="V de Cramér", range=[0, max(0.12, df["cramers_v"].max() * 1.4)]),
        xaxis_title="Tranche Elo",
    )
    return _finish(
        fig,
        "L'ouverture influence-t-elle le résultat ?",
        "Test du khi² ouverture × résultat : significatif, mais effet très faible",
    )


def odds_ratios(df: pd.DataFrame) -> go.Figure:
    """Forest plot of the logistic regression odds ratios with 95 % confidence intervals."""
    df = df.iloc[::-1]
    fig = go.Figure(go.Scatter(
        x=df["odds_ratio"], y=df["label"], mode="markers",
        error_x=dict(type="data", symmetric=False, array=df["or_high"] - df["odds_ratio"],
                     arrayminus=df["odds_ratio"] - df["or_low"], color=INK_2, thickness=2),
        marker=dict(size=10, color=[WHITE_POLE if v > 1 else BLACK_POLE for v in df["odds_ratio"]],
                    line=dict(color=PAPER, width=2)),
        hovertemplate="%{y}<br>odds ratio %{x:.3f}<extra></extra>",
    ))  # fmt: skip
    fig.add_vline(x=1, line=dict(color=MUTED, dash="dash"))
    fig.update_layout(
        xaxis=dict(title="Odds ratio (échelle log) — > 1 : favorise une victoire des Blancs", type="log"),
        margin=dict(l=300),
    )
    return _finish(
        fig,
        "Ce qui fait gagner les Blancs (régression logistique)",
        "Parties décisives ; IC 95 % ; brun = favorise les Blancs, bleu = favorise les Noirs",
    )
