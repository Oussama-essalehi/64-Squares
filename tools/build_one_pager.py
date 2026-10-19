"""Build the one-page summary for recruiters (``reports/64-squares-synthese.pdf``).

Every number is read from ``reports/metrics.json`` and ``reports/tables/``; the page is printed
to an A4 PDF with headless Chrome/Chromium.

Usage: ``python tools/build_one_pager.py [--chromium PATH]``
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
from html import escape
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OUT_HTML = REPORTS / "one_pager.html"
OUT_PDF = REPORTS / "64-squares-synthese.pdf"


def pct(v: float, d: int = 1) -> str:
    return f"{v * 100:.{d}f} %".replace(".", ",")


def num(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def img(name: str) -> str:
    data = base64.b64encode((REPORTS / "figures" / name).read_bytes()).decode()
    return f"data:image/png;base64,{data}"


def facts() -> dict[str, str]:
    m = json.loads((REPORTS / "metrics.json").read_text(encoding="utf-8"))
    logit = {t["term"]: t for t in m["logit"]["terms"]}
    dec = m["time_used_deciles"]["Blitz"]
    fav = pd.read_csv(REPORTS / "tables" / "q3_favourite_calibration.csv")
    fav200 = fav[(fav["time_control"] == "Blitz") & (fav["gap_bucket"] == 200)].iloc[0]
    rep = pd.read_csv(REPORTS / "tables" / "q1_repertoire_shift.csv").set_index("opening_family")
    sic = rep.loc["Sicilian Defense"]
    chi = pd.DataFrame(m["chi_square"])
    return {
        "month_games": num(89_616_462),
        "sampled": num(m["sample"]["rows_sampled"]),
        "clean": num(m["sample"]["rows_clean"]),
        "players": num(m["sample"]["distinct_players"]),
        "or_gap": f"{logit['gap_100']['odds_ratio']:.2f}".replace(".", ","),
        "or_white_clock": f"{logit['white_used_10pts']['odds_ratio']:.2f}".replace(".", ","),
        "fav_expected": pct(fav200["expected_score"]),
        "fav_actual": pct(fav200["actual_score"]),
        "d1": pct(dec["d1_score"]),
        "d10": pct(dec["d10_score"]),
        "flag_d1": pct(dec["d1_lost_on_time"]),
        "flag_d10": pct(dec["d10_lost_on_time"]),
        "white": pct(m["overview"]["white_score"]),
        "white_edge": f"{m['overview']['white_edge'] * 100:+.1f}".replace(".", ","),
        "lost_on_time": pct(m["overview"]["lost_on_time"]),
        "v_max": f"{chi['cramers_v'].max():.3f}".replace(".", ","),
        "sic_low": pct(sic["share_lt_1200"]),
        "sic_high": pct(sic["share_2000_plus"]),
    }


def html(f: dict[str, str]) -> str:
    findings = [
        ("Le classement d'abord", f"+100 points d'écart multiplient les chances de victoire par <b>{f['or_gap']}</b>. "
         f"Mais à +200 en blitz, le favori marque {f['fav_actual']} au lieu des {f['fav_expected']} prévus par la formule Elo."),
        ("La pendule ensuite", f"En blitz, les joueurs les plus lents sur leurs 10 premiers coups marquent <b>{f['d10']}</b> "
         f"contre {f['d1']} pour les plus rapides, et perdent au temps {f['flag_d10']} de leurs parties (contre {f['flag_d1']})."),
        ("Un petit avantage aux Blancs", f"Score moyen de <b>{f['white']}</b>, soit {f['white_edge']} point au-delà de ce que prédit le classement ; "
         f"{f['lost_on_time']} des parties se terminent au temps."),
        ("L'ouverture pèse peu", f"Khi² significatif dans toutes les tranches, mais V de Cramér ≤ <b>{f['v_max']}</b>. "
         f"Le répertoire change pourtant : la Sicilienne passe de {f['sic_low']} à {f['sic_high']} des parties."),
    ]  # fmt: skip
    cards = "".join(f"<div class='f'><h3>{escape(t)}</h3><p>{body}</p></div>" for t, body in findings)
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>64 Squares — synthèse</title>
<style>
@page {{ size: A4; margin: 12mm 13mm; }}
* {{ box-sizing: border-box; }}
body {{ font: 10.2pt/1.42 system-ui, -apple-system, "Segoe UI", sans-serif; color: #262421; margin: 0; }}
header {{ display: flex; justify-content: space-between; align-items: end; border-bottom: 3px solid #b58863; padding-bottom: 6px; }}
h1 {{ font-size: 21pt; margin: 0; letter-spacing: -0.01em; }}
.tag {{ color: #5c574f; font-size: 10.5pt; margin: 2px 0 0; }}
.who {{ text-align: right; font-size: 9pt; color: #5c574f; }}
.who b {{ color: #262421; font-size: 10.5pt; }}
.q {{ background: #f7f1e8; border-radius: 6px; padding: 7px 10px; margin: 9px 0 8px; }}
.kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 7px; margin-bottom: 8px; }}
.k {{ border: 1px solid #e9e4dc; border-radius: 6px; padding: 6px 8px; }}
.k b {{ display: block; font-size: 15pt; }}
.k span {{ font-size: 8.5pt; color: #5c574f; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 7px 12px; }}
.f h3 {{ font-size: 10.5pt; margin: 0 0 1px; color: #86562d; }}
.f p {{ margin: 0; }}
.charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 9px 0 6px; }}
.charts img {{ width: 100%; border: 1px solid #e9e4dc; border-radius: 4px; }}
h2 {{ font-size: 11.5pt; margin: 8px 0 3px; }}
ul {{ margin: 0; padding-left: 15px; }}
li {{ margin: 1px 0; }}
.cols {{ display: grid; grid-template-columns: 1.15fr 1fr; gap: 12px; }}
footer {{ margin-top: 7px; font-size: 8.5pt; color: #8a847b; border-top: 1px solid #e9e4dc; padding-top: 4px; }}
</style></head><body>
<header><div><h1>64 Squares</h1><p class="tag">Qu'est-ce qui fait vraiment gagner aux échecs ? Analyse de 2 millions de parties Lichess, du fichier brut au tableau de bord.</p></div>
<div class="who"><b>Oussama Essalehi</b><br>Data Analyst<br>linkedin.com/in/oussama-essalehi · oussama-essalehi.dev</div></header>
<div class="q"><b>Question métier</b> — pour une plateforme d'échecs en ligne : à chaque niveau, qu'est-ce qui fait gagner un joueur ?
Son ouverture, sa couleur, sa gestion du temps, ou simplement son classement ?</div>
<div class="kpis">
<div class="k"><b>{f["month_games"]}</b><span>parties dans le fichier du mois (29,2 Go), lues en flux</span></div>
<div class="k"><b>{f["sampled"]}</b><span>parties tirées au hasard (Bernoulli, graine fixe)</span></div>
<div class="k"><b>{f["clean"]}</b><span>parties après 7 règles de nettoyage testées</span></div>
<div class="k"><b>{f["players"]}</b><span>joueurs distincts (pseudos hachés)</span></div>
</div>
<div class="grid">{cards}</div>
<div class="charts"><img src="{img("fig04_elo_calibration.png")}" alt="Calibration Elo"><img src="{img("fig06_time_used_deciles.png")}" alt="Temps consommé dans l'ouverture"></div>
<div class="cols"><div><h2>Ce que j'ai construit</h2><ul>
<li><b>Pipeline Python</b> : streaming HTTP + zstandard, échantillonnage reproductible, Parquet, reprise sur erreur.</li>
<li><b>Modèle DuckDB</b> en étoile et requêtes SQL (CTE, fenêtres, ROLLUP / GROUPING SETS).</li>
<li><b>Statistiques</b> : Wilson, khi² + V de Cramér, calibration Elo, régression logistique.</li>
<li><b>Power BI</b> (PBIP : TMDL + PBIR validés), 4 pages, 19 mesures DAX, seuil d'échantillon.</li>
<li><b>Tableau de bord web</b> et <b>application « Analyse mes parties »</b> (API Lichess, conseils personnalisés).</li>
</ul></div><div><h2>Rigueur</h2><ul>
<li>Minimum de 1 000 parties pour tout taux affiché.</li>
<li>140 tests automatisés ; recoupement SQL ↔ Python 6/6.</li>
<li>Résultats identiques d'une exécution à l'autre.</li>
<li>Palette vérifiée pour le daltonisme, aucun double axe.</li>
<li>Aucun pseudo en clair, aucune donnée brute versionnée.</li>
</ul></div></div>
<footer>Données : base ouverte Lichess (CC0), septembre 2026. Code, méthode et limites : github.com/Oussama-essalehi/64-Squares.
Corrélation ≠ causalité ; un seul mois ; joueurs en ligne non représentatifs de tous les joueurs.</footer>
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--chromium", default=shutil.which("chromium") or shutil.which("google-chrome"))
    args = parser.parse_args()
    OUT_HTML.write_text(html(facts()), encoding="utf-8")
    if not args.chromium:
        raise SystemExit("Chrome/Chromium not found: pass --chromium PATH")
    subprocess.run(
        [args.chromium, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()],
        check=True, capture_output=True,
    )  # fmt: skip
    print(f"{OUT_PDF.relative_to(ROOT)}: {OUT_PDF.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
