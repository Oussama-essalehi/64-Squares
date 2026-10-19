"""64 Squares — « Analyse mes parties ».

Compare les parties d'un joueur Lichess avec 2 millions de parties classées (septembre 2026),
au même niveau, à la même cadence et avec la même couleur.

Lancer : ``streamlit run app/streamlit_app.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eloscope import charts  # noqa: E402  (registers the shared plotly template)
from eloscope.boards import board_svg  # noqa: E402
from eloscope.player import (  # noqa: E402
    MIN_PLAYER_GAMES,
    PERF_TYPES,
    TC_LABELS,
    Baseline,
    LichessError,
    build_report,
    fetch_user_games,
    player_games,
)
from eloscope.settings import load_config  # noqa: E402

DATA = ROOT / "app" / "data"
DEMO_NAME = "JoueurDemo"
PROJECT_URL = "https://github.com/Oussama-essalehi/64-Squares"
PERF_LABELS = dict(zip(PERF_TYPES, ["UltraBullet", "Bullet", "Blitz", "Rapide", "Classique"]))
YOU, PEERS = charts.SERIES[0], charts.SERIES[1]  # two identity colours, fixed for the whole app

st.set_page_config(page_title="Analyse mes parties · 64 Squares", page_icon="♟", layout="wide")
st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 1200px;}
      [data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
      .hero {background: #f7f1e8; border: 1px solid #e9e4dc; border-radius: 10px; padding: 1rem 1.25rem;}
      .hero h1 {font-size: 1.9rem; margin: 0 0 .25rem 0;}
      .muted {color: #5c574f; font-size: .92rem;}
      .board svg {max-width: 220px; height: auto;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def baseline() -> Baseline:
    return Baseline.load(DATA)


@st.cache_resource
def opening_roots() -> pd.DataFrame:
    return pd.read_csv(DATA / "opening_roots.csv").set_index("family")


@st.cache_data(ttl=900, show_spinner=False)
def download(username: str, max_games: int, perfs: tuple[str, ...]) -> str:
    return fetch_user_games(username, max_games, perfs)


def pct(value: float, signed: bool = False) -> str:
    if pd.isna(value):
        return "—"
    text = f"{value * 100:+.1f} pts" if signed else f"{value * 100:.1f} %"
    return text.replace(".", ",")


def delta_pts(value: float, suffix: str = " vs ton niveau") -> str:
    return "—" if pd.isna(value) else f"{value * 100:+.1f} pts{suffix}".replace(".", ",")


def compare_bars(df: pd.DataFrame, you: str, peers: str, title: str, fmt: str = ".0%") -> go.Figure:
    """Grouped bars: the player vs players of the same level (one axis, two identity colours)."""
    fig = go.Figure()
    for col, name, color in ((you, "Toi", YOU), (peers, "Joueurs de ton niveau", PEERS)):
        fig.add_bar(
            x=df["tc_label"], y=df[col], name=name, marker_color=color, marker_line=dict(color="#ffffff", width=2),
            text=[f"{v:{fmt}}" for v in df[col]], textposition="outside", textfont=dict(color=charts.INK_2),
            hovertemplate=f"{name}<br>%{{x}} : %{{y:{fmt}}}<extra></extra>",
        )  # fmt: skip
    fig.update_layout(
        title=dict(text=f"<b>{title}</b>"), barmode="group", bargap=0.3, height=360,
        yaxis=dict(tickformat=fmt, range=[0, float(df[[you, peers]].max().max()) * 1.18]),
        margin=dict(l=60, r=20, t=90, b=40),
        template="eloscope",
    )  # fmt: skip
    return fig


# --------------------------------------------------------------------------------------
# Header and input
# --------------------------------------------------------------------------------------
st.markdown(
    f"""
    <div class="hero">
      <h1>♟ Analyse mes parties</h1>
      <div class="muted">Compare tes parties Lichess avec <b>1 958 145 parties classées</b> (septembre 2026),
      au même niveau, à la même cadence et avec la même couleur. Projet
      <a href="{PROJECT_URL}">64 Squares</a>.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Tes parties")
    mode = st.radio("Source", ["Pseudo Lichess", "Fichier PGN", "Profil de démonstration"], index=0)
    username, pgn_text = "", None
    if mode == "Pseudo Lichess":
        username = st.text_input("Pseudo Lichess", placeholder="ex. MonPseudo")
        max_games = st.slider("Nombre de parties récentes", 50, 500, 200, step=50)
        perfs = st.multiselect(
            "Cadences", list(PERF_TYPES), default=["bullet", "blitz", "rapid"], format_func=PERF_LABELS.get
        )
    elif mode == "Fichier PGN":
        st.caption("Sur Lichess : profil > Exporter les parties (PGN, avec les horloges).")
        upload = st.file_uploader("Fichier .pgn", type=["pgn", "txt"])
        username = st.text_input("Ton pseudo dans ce fichier")
        if upload is not None:
            pgn_text = upload.getvalue()
    else:
        st.caption(
            "Profil composite et anonyme : 300 parties aléatoires de l'échantillon où un joueur classé "
            "1500–1600 tient le rôle de « JoueurDemo »."
        )
        username = DEMO_NAME
        pgn_text = (DATA / "demo_games.pgn").read_bytes()
    run = st.button("Analyser", type="primary", use_container_width=True)
    st.divider()
    st.caption(
        "Rien n'est enregistré : les parties sont analysées en mémoire puis oubliées. "
        "Les comparaisons utilisent uniquement des agrégats (au moins 1 000 parties par groupe)."
    )

if run:
    try:
        if mode == "Pseudo Lichess":
            if not perfs:
                st.warning("Choisis au moins une cadence.")
                st.stop()
            with st.spinner("Téléchargement des parties depuis Lichess…"):
                pgn_text = download(username, max_games, tuple(perfs))
        if not pgn_text or not username.strip():
            st.warning("Indique un pseudo et une source de parties.")
            st.stop()
        games = player_games(pgn_text, username, load_config())
    except LichessError as exc:
        st.error(str(exc))
        st.stop()
    if len(games) < MIN_PLAYER_GAMES:
        st.warning(
            f"Seulement {len(games)} partie(s) classée(s) exploitable(s) pour « {username} » : il en faut au moins "
            f"{MIN_PLAYER_GAMES} (parties standard classées, terminées normalement ou au temps, 10 demi-coups minimum)."
        )
        st.stop()
    st.session_state["games"], st.session_state["who"] = games, username.strip()

if "games" not in st.session_state:
    st.info("Choisis une source dans le panneau de gauche, puis clique sur **Analyser**. Pas de compte Lichess ? "
            "Essaie le **profil de démonstration**.")  # fmt: skip
    c1, c2, c3 = st.columns(3)
    c1.markdown("**Résultats**  \nTon score et tes défaites au temps face aux joueurs de ton niveau, par cadence.")
    c2.markdown("**Pendule**  \nLe temps que tu prends sur tes 10 premiers coups, comparé à la distribution.")
    c3.markdown("**Ouvertures**  \nTes ouvertures, ton score par rapport à ton classement, et des conseils.")
    st.stop()

games: pd.DataFrame = st.session_state["games"]
report = build_report(games, baseline())
s = report.summary

# --------------------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------------------
st.subheader(f"{st.session_state['who']} · {report.games} parties · niveau {report.main_band} (Elo moyen des parties)")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Ton score", pct(s["score"]), delta_pts(s["score"] - s["ref_score"]))
k2.metric(
    "Score vs classement", pct(s["performance"], signed=True), help="Score réel − score attendu par la formule Elo"
)
k3.metric(
    "Défaites au temps",
    pct(s["lost_on_time"]),
    delta_pts(s["lost_on_time"] - s["ref_lost_on_time"]),
    delta_color="inverse",
)
k4.metric("Classement (dernière partie)", f"{s['rating']:.0f}")

with st.container(border=True):
    st.markdown("#### Conseils")
    for tip in report.advice:
        st.markdown(f"- {tip}")
    st.caption(
        f"Un conseil n'apparaît que sur au moins {MIN_PLAYER_GAMES} parties et si l'écart dépasse la marge "
        "d'erreur à 95 %."
    )

tab_res, tab_clock, tab_open, tab_time, tab_data = st.tabs(
    ["Résultats par cadence", "Pendule", "Ouvertures", "Heure de jeu", "Tes parties"]
)

with tab_res:
    shown = report.by_tc[report.by_tc["games"] >= MIN_PLAYER_GAMES]
    if shown.empty:
        st.info(f"Aucune cadence avec au moins {MIN_PLAYER_GAMES} parties.")
    else:
        c1, c2 = st.columns(2)
        c1.plotly_chart(compare_bars(shown, "score", "ref_score", "Score"), use_container_width=True, theme=None)
        c2.plotly_chart(
            compare_bars(shown, "lost_on_time", "ref_lost_on_time", "Part des parties perdues au temps"),
            use_container_width=True,
            theme=None,
        )
        table = shown.rename(
            columns={"tc_label": "Cadence", "games": "Parties", "score": "Ton score", "ref_score": "Score du niveau",
                     "lost_on_time": "Tes défaites au temps", "ref_lost_on_time": "Défaites au temps du niveau"}
        ).drop(columns="tc_category")  # fmt: skip
        st.dataframe(table, hide_index=True, use_container_width=True, column_config={
            c: st.column_config.NumberColumn(format="percent") for c in table.columns if c not in ("Cadence", "Parties")
        })  # fmt: skip
    st.caption(
        "« Joueurs de ton niveau » = même tranche Elo, même cadence et même couleur, pondérés comme tes parties."
    )

with tab_clock:
    clock = report.clock[report.clock["games"] >= MIN_PLAYER_GAMES]
    if clock.empty:
        st.info("Pas assez de parties avec les horloges sur 10 coups.")
    else:
        tc = st.selectbox("Cadence", clock["tc_category"].tolist(), format_func=TC_LABELS.get, key="clock_tc")
        row = clock.set_index("tc_category").loc[tc]
        curve = baseline().time_used[baseline().time_used["tc_category"] == tc]
        fig = go.Figure()
        fig.add_scatter(
            x=curve["bin_pct"] + 2.5, y=curve["score"], mode="lines+markers", name="Score des joueurs (2 M de parties)",
            line=dict(color=PEERS, width=2), marker=dict(size=8, line=dict(color="#ffffff", width=2)),
            hovertemplate="%{x:.0f} % du temps utilisé<br>score %{y:.1%}<extra></extra>",
        )  # fmt: skip
        fig.add_vline(
            x=row["median_share"] * 100, line=dict(color=YOU, width=2),
            annotation_text=f"Toi : {row['median_share']:.0%}", annotation_font_color=charts.INK,
        )  # fmt: skip
        fig.update_layout(
            title=dict(text=f"<b>{TC_LABELS[tc]} : temps consommé sur les 10 premiers coups et score</b>"),
            xaxis=dict(title="Part du temps de base utilisée (%)", ticksuffix=" %"),
            yaxis=dict(title="Score moyen", tickformat=".0%"), height=420, margin=dict(l=60, r=20, t=90, b=60),
            template="eloscope",
        )  # fmt: skip
        st.plotly_chart(fig, use_container_width=True, theme=None)
        st.markdown(
            f"Sur **{int(row['games'])} parties**, tu utilises en médiane **{row['median_share']:.0%}** de ton temps "
            f"sur tes 10 premiers coups. C'est plus que **{row['percentile']:.0f} %** des joueurs "
            f"(médiane de tous les joueurs : {row['ref_median_share']:.0%})."
        )

with tab_open:
    fam = report.openings[report.openings["games"] >= 3].copy()
    if fam.empty:
        st.info("Pas assez de parties par ouverture.")
    else:
        top = fam.iloc[0]
        c1, c2 = st.columns([1, 2.4])
        with c1:
            st.markdown(f"**Ton ouverture la plus jouée**  \n{top['opening_family']} "
                        f"({'Blancs' if top['color'] == 'white' else 'Noirs'}, {top['games']} parties)")  # fmt: skip
            roots = opening_roots()
            if top["opening_family"] in roots.index:
                moves = roots.loc[top["opening_family"], "moves"]
                st.markdown(f'<div class="board">{board_svg(moves, 220)}</div>', unsafe_allow_html=True)
                st.caption(
                    f"Position de référence : `{moves}` (choix des {roots.loc[top['opening_family'], 'chosen_by']})"
                )
        with c2:
            fam["Couleur"] = fam["color"].map({"white": "Blancs", "black": "Noirs"})
            view = fam[["Couleur", "opening_family", "games", "score", "score_vs_expected", "ref_score",
                        "ref_score_vs_expected"]].rename(columns={  # fmt: skip
                "opening_family": "Ouverture", "games": "Parties", "score": "Ton score",
                "score_vs_expected": "Toi vs classement", "ref_score": "Score du niveau",
                "ref_score_vs_expected": "Niveau vs classement",
            })  # fmt: skip
            st.dataframe(view, hide_index=True, use_container_width=True, height=420, column_config={
                c: st.column_config.NumberColumn(format="percent") for c in
                ("Ton score", "Toi vs classement", "Score du niveau", "Niveau vs classement")
            })  # fmt: skip
        st.caption(
            "« vs classement » = score réel − score attendu par la formule Elo. Avec peu de parties, un écart peut "
            "être dû au hasard : les conseils ne retiennent que les écarts au-delà de la marge d'erreur."
        )

with tab_time:
    per = report.periods.groupby("period", sort=False).apply(
        lambda d: pd.Series({
            "games": d["games"].sum(),
            "lost_on_time": (d["lost_on_time"] * d["games"]).sum() / d["games"].sum(),
            "ref_lost_on_time": (d["ref_lost_on_time"] * d["games"]).sum() / d["games"].sum(),
        }),
        include_groups=False,
    ).reindex(["nuit", "matin", "après-midi", "soir"]).dropna().reset_index()  # fmt: skip
    per = per[per["games"] >= MIN_PLAYER_GAMES]
    if per.empty:
        st.info(f"Pas assez de parties par moment de la journée (minimum {MIN_PLAYER_GAMES}).")
    else:
        per["tc_label"] = per["period"].str.capitalize() + " (" + per["games"].astype(int).astype(str) + ")"
        st.plotly_chart(
            compare_bars(per, "lost_on_time", "ref_lost_on_time", "Défaites au temps selon le moment (UTC)"),
            use_container_width=True,
            theme=None,
        )
        st.caption(
            "Nuit 0h–5h, matin 6h–11h, après-midi 12h–17h, soir 18h–23h (heure UTC). Entre parenthèses : tes parties."
        )

with tab_data:
    view = games.assign(
        Résultat=games["score"].map({1.0: "Victoire", 0.5: "Nulle", 0.0: "Défaite"}),
        Couleur=games["color"].map({"white": "Blancs", "black": "Noirs"}),
    )[["date", "tc_label", "Couleur", "player_elo", "opponent_elo", "Résultat", "termination", "opening"]]
    st.dataframe(
        view.rename(columns={"date": "Date", "tc_label": "Cadence", "player_elo": "Ton Elo",
                             "opponent_elo": "Elo adverse", "termination": "Fin", "opening": "Ouverture"}),
        hide_index=True, use_container_width=True,
    )  # fmt: skip

st.divider()
st.caption(
    f"Méthodologie, code et limites : [{PROJECT_URL}]({PROJECT_URL}). Données de référence : base ouverte Lichess "
    "(CC0), échantillon aléatoire de septembre 2026. Corrélation ≠ causalité."
)
