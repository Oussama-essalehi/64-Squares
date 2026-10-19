"""Plotly chart builders with one consistent, chessboard-inspired visual style (French labels)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

# Palette shared with powerbi/theme.json
INK = "#262421"  # near-black (Black pieces / text)
DARK_SQUARE = "#B58863"  # Lichess dark square
LIGHT_SQUARE = "#F0D9B5"  # Lichess light square
GREEN = "#6D8B3A"  # accent
GREY = "#9E9A94"  # draws
RED = "#B33A3A"  # losses on time / alerts
BLUE = "#3C6E91"  # secondary series
PAPER = "#FFFFFF"
GRID = "#E9E4DC"

RESULT_COLORS = {"Victoire Blancs": DARK_SQUARE, "Nulle": GREY, "Victoire Noirs": INK}
TC_COLORS = {"UltraBullet": RED, "Bullet": DARK_SQUARE, "Blitz": GREEN, "Rapide": BLUE, "Classique": INK}
BAND_COLORS = {"< 1200": LIGHT_SQUARE, "1200-1599": DARK_SQUARE, "1600-1999": GREEN, "2000+": INK}
SEQUENTIAL = [[0.0, "#FBF6EE"], [0.35, LIGHT_SQUARE], [0.7, DARK_SQUARE], [1.0, "#5C3B22"]]
DIVERGING = [[0.0, BLUE], [0.5, "#F7F4EF"], [1.0, DARK_SQUARE]]

pio.templates["eloscope"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family="Segoe UI, Helvetica Neue, Arial, sans-serif", size=13, color=INK),
        title=dict(font=dict(size=18, color=INK), x=0.01, xanchor="left"),
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        colorway=[DARK_SQUARE, INK, GREEN, BLUE, RED, GREY],
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
            text=[f"{v:.1%}" for v in df[col]], textposition="inside",
            insidetextfont=dict(color="white" if label != "Nulle" else INK),
        )  # fmt: skip
    fig.update_layout(
        barmode="stack", yaxis=dict(tickformat=".0%", title="Part des parties"), xaxis_title="Tranche Elo"
    )
    return _finish(fig, "Répartition des résultats par niveau", "Les Blancs gagnent plus souvent à tous les niveaux")


def top_openings(df: pd.DataFrame, bands: list[str], top: int = 10) -> go.Figure:
    """Top opening families per band: popularity (bar length) coloured by White's score."""
    fig = make_subplots(
        rows=2, cols=2, subplot_titles=[f"Elo {b}" for b in bands], horizontal_spacing=0.3, vertical_spacing=0.1
    )
    vmin, vmax = df["white_score"].min(), df["white_score"].max()
    for i, band in enumerate(bands):
        sub = df[df["elo_band"] == band].nsmallest(top, "popularity_rank").iloc[::-1]
        fig.add_bar(
            x=sub["share_of_band"], y=sub["opening_family"], orientation="h", row=i // 2 + 1, col=i % 2 + 1,
            marker=dict(color=sub["white_score"], colorscale=SEQUENTIAL, cmin=vmin, cmax=vmax,
                        colorbar=dict(title="Score<br>Blancs", tickformat=".0%") if i == 0 else None,
                        showscale=i == 0),
            text=[f"{s:.1%}" for s in sub["share_of_band"]], textposition="outside", showlegend=False,
            hovertemplate="%{y}<br>%{x:.1%} des parties<extra></extra>",
        )  # fmt: skip
    fig.update_xaxes(
        tickformat=".0%", showgrid=False, showticklabels=False, range=[0, df["share_of_band"].max() * 1.22]
    )
    fig.update_yaxes(tickfont=dict(size=11), automargin=True)
    fig.update_layout(margin=dict(l=190))
    return _finish(
        fig,
        "Ouvertures les plus jouées par niveau",
        "Longueur = part des parties de la tranche ; couleur = score des Blancs",
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
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=pivot.columns,
            y=pivot.index,
            text=text,
            texttemplate="%{text}",
            textfont=dict(size=14),
            colorscale=DIVERGING,
            zmid=0.5,
            colorbar=dict(title="Score", tickformat=".0%"),
            xgap=2,
            ygap=2,
        )  # fmt: skip
    )
    fig.update_layout(xaxis_title="Cadence", yaxis=dict(title=dict(text="Tranche Elo", standoff=18), automargin=True))
    return _finish(
        fig,
        "Score moyen des Blancs par niveau et cadence",
        "50 % = pas d'avantage ; cellules sous le minimum d'échantillon masquées",
    )


def calibration(df: pd.DataFrame) -> go.Figure:
    """Expected (Elo formula) vs actual White score by rating-gap bucket, one line per time control."""
    fig = go.Figure()
    gaps = np.arange(-600, 601, 10)
    fig.add_scatter(
        x=gaps, y=1 / (1 + 10 ** (-gaps / 400)), name="Formule Elo (attendu)", mode="lines",
        line=dict(color=GREY, dash="dash", width=2),
    )  # fmt: skip
    for tc, sub in df.groupby("time_control", sort=False):
        fig.add_scatter(
            x=sub["rating_gap_bucket"], y=sub["actual_score"], name=tc, mode="lines+markers",
            line=dict(color=TC_COLORS.get(tc, INK), width=2.5), marker=dict(size=6),
        )  # fmt: skip
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
            marker_line=dict(color=INK, width=0.6), text=[f"{v:.0%}" for v in sub["lost_on_time_rate"]],
            textposition="outside",
        )  # fmt: skip
    order = [c for c in TC_COLORS if c in set(df["time_control"])]
    fig.update_layout(
        barmode="group",
        yaxis=dict(title="Part des parties perdues au temps", tickformat=".0%"),
        xaxis=dict(title="Cadence", categoryorder="array", categoryarray=order),
    )
    return _finish(
        fig, "Défaites au temps par cadence et niveau", "Part des parties terminées par une chute du drapeau"
    )


def time_used_deciles(df: pd.DataFrame) -> go.Figure:
    """Player score by decile of clock share used in the first 10 moves, per time control."""
    fig = make_subplots(
        rows=1, cols=2, subplot_titles=["Score du joueur", "Part des parties perdues au temps"], horizontal_spacing=0.1
    )
    for tc, sub in df.groupby("time_control", sort=False):
        color = TC_COLORS.get(tc, INK)
        fig.add_scatter(
            x=sub["decile"],
            y=sub["score"],
            name=tc,
            mode="lines+markers",
            line=dict(color=color, width=2.5),
            row=1,
            col=1,
        )
        fig.add_scatter(
            x=sub["decile"], y=sub["lost_on_time_rate"], name=tc, mode="lines+markers",
            line=dict(color=color, width=2.5), showlegend=False, row=1, col=2,
        )  # fmt: skip
    fig.update_xaxes(title="Décile de temps consommé (1 = le plus rapide)", dtick=1)
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
            colorbar=dict(title="Parties<br>par jour"),
        )
    )
    fig.update_layout(xaxis=dict(title="Heure (UTC)", dtick=1), yaxis=dict(title="", autorange="reversed"))
    return _finish(
        fig, "Quand joue-t-on ?", "Nombre moyen de parties de l'échantillon par jour, selon le jour et l'heure (UTC)"
    )


def results_by_hour(df: pd.DataFrame) -> go.Figure:
    """Lost-on-time rate (left axis) and White score (right axis, deliberately wide range) by UTC hour."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_scatter(
        x=df["hour"], y=df["lost_on_time_rate"], name="Parties perdues au temps", mode="lines+markers",
        line=dict(color=RED, width=3), marker=dict(size=7),
    )  # fmt: skip
    fig.add_scatter(
        x=df["hour"], y=df["white_score"], name="Score des Blancs (axe de droite)", mode="lines+markers",
        line=dict(color=INK, width=2, dash="dot"), secondary_y=True,
    )  # fmt: skip
    low, high = df["lost_on_time_rate"].min(), df["lost_on_time_rate"].max()
    pad = (high - low) * 0.6
    fig.update_yaxes(title_text="Perdues au temps", tickformat=".0%", range=[low - pad, high + pad], secondary_y=False)
    fig.update_yaxes(
        title_text="Score des Blancs", tickformat=".0%", range=[0.45, 0.55], secondary_y=True, showgrid=False
    )
    fig.update_xaxes(title_text="Heure (UTC)", dtick=1, range=[-0.5, 23.5])
    return _finish(
        fig, "Résultats selon l'heure de la partie",
        "Les défaites au temps augmentent la nuit ; le score des Blancs ne bouge pas (toutes cadences, UTC)",
    )  # fmt: skip


def cramers_v(df: pd.DataFrame) -> go.Figure:
    """Cramér's V (opening family x result) per Elo band."""
    fig = go.Figure(go.Bar(
        x=df["elo_band"], y=df["cramers_v"], marker_color=DARK_SQUARE,
        text=[f"V = {v:.3f}<br>p = {p:.1e}" for v, p in zip(df["cramers_v"], df["p_value"])], textposition="outside",
    ))  # fmt: skip
    fig.add_hline(
        y=0.1,
        line=dict(color=RED, dash="dot"),
        annotation_text="Seuil d'effet « faible » (0,1)",
        annotation_position="top left",
    )
    fig.update_layout(
        yaxis=dict(title="V de Cramér", range=[0, max(0.12, df["cramers_v"].max() * 1.4)]), xaxis_title="Tranche Elo"
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
                     arrayminus=df["odds_ratio"] - df["or_low"], color=INK, thickness=1.5),
        marker=dict(size=10, color=[GREEN if v > 1 else RED for v in df["odds_ratio"]]),
    ))  # fmt: skip
    fig.add_vline(x=1, line=dict(color=GREY, dash="dash"))
    fig.update_layout(
        xaxis=dict(title="Odds ratio (échelle log) — > 1 : favorise une victoire des Blancs", type="log"),
        margin=dict(l=300),
    )
    return _finish(fig, "Ce qui fait gagner les Blancs (régression logistique)", "Parties décisives ; IC 95 %")
