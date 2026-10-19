"""Generate the Power BI report definition (PBIR) of ``powerbi/EloScope.Report``.

The four pages and their visuals are declared below as data; running the script rewrites the
report folder so the layout stays reviewable and reproducible. Field names must match the
semantic model (``powerbi/EloScope.SemanticModel``); ``tools/validate_pbip.py`` checks both
the JSON schemas and every field reference.

Usage: ``python tools/generate_report.py``
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POWERBI = ROOT / "powerbi"
REPORT = POWERBI / "EloScope.Report"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
VISUAL_SCHEMA = f"{SCHEMA}/item/report/definition/visualContainer/2.13.0/schema.json"
PAGE_SCHEMA = f"{SCHEMA}/item/report/definition/page/2.1.0/schema.json"
THEME_FILE = "EloScopeTheme.json"
M = "_Mesures"


# --------------------------------------------------------------------------------------
# Small builders for the PBIR JSON vocabulary
# --------------------------------------------------------------------------------------
def lit(value: Any) -> dict[str, Any]:
    """Literal expression: strings are single-quoted, integers end with L, booleans as is."""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, int):
        text = f"{value}L"
    elif isinstance(value, float):
        text = f"{value}D"
    else:
        text = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": text}}}


def measure(name: str, entity: str = M) -> dict[str, Any]:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": name}}


def column(entity: str, name: str) -> dict[str, Any]:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": name}}


def level(entity: str, hierarchy: str, name: str) -> dict[str, Any]:
    return {
        "HierarchyLevel": {
            "Expression": {"Hierarchy": {"Expression": {"SourceRef": {"Entity": entity}}, "Hierarchy": hierarchy}},
            "Level": name,
        }
    }


def ref_of(field: dict[str, Any]) -> tuple[str, str]:
    """queryRef and nativeQueryRef of a field."""
    kind, body = next(iter(field.items()))
    if kind == "HierarchyLevel":
        h = body["Expression"]["Hierarchy"]
        entity = h["Expression"]["SourceRef"]["Entity"]
        return f"{entity}.{h['Hierarchy']}.{body['Level']}", body["Level"]
    entity = body["Expression"]["SourceRef"]["Entity"]
    return f"{entity}.{body['Property']}", body["Property"]


def projection(field: dict[str, Any], active: bool | None = None) -> dict[str, Any]:
    query_ref, native = ref_of(field)
    proj: dict[str, Any] = {"field": field, "queryRef": query_ref, "nativeQueryRef": native}
    if active is not None:
        proj["active"] = active
    return proj


def visual(
    name: str,
    visual_type: str,
    pos: tuple[int, int, int, int],
    roles: dict[str, list[dict[str, Any]]],
    title: str,
    z: int,
    objects: dict[str, Any] | None = None,
    sort: tuple[dict[str, Any], str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    subtitle: str | None = None,
) -> dict[str, Any]:
    x, y, w, h = pos
    query: dict[str, Any] = {"queryState": {role: {"projections": projs} for role, projs in roles.items()}}
    if sort:
        query["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": True}
    container_objects: dict[str, Any] = {"title": [{"properties": {"show": lit(True), "text": lit(title)}}]}
    if subtitle:
        container_objects["subTitle"] = [{"properties": {"show": lit(True), "text": lit(subtitle)}}]
    body: dict[str, Any] = {
        "$schema": VISUAL_SCHEMA,
        "name": name,
        "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z},
        "visual": {
            "visualType": visual_type,
            "query": query,
            "visualContainerObjects": container_objects,
            "drillFilterOtherVisuals": True,
        },
    }
    if objects:
        body["visual"]["objects"] = objects
    if filters:
        body["filterConfig"] = {"filters": filters}
    return body


def slicer(name: str, pos: tuple[int, int, int, int], field: dict[str, Any], title: str, z: int) -> dict[str, Any]:
    objects = {"data": [{"properties": {"mode": lit("Dropdown")}}]}
    return visual(name, "slicer", pos, {"Values": [projection(field)]}, title, z, objects=objects)


def card(name: str, pos: tuple[int, int, int, int], measure_name: str, title: str, z: int) -> dict[str, Any]:
    objects = {"categoryLabels": [{"properties": {"show": lit(False)}}]}
    return visual(name, "card", pos, {"Values": [projection(measure(measure_name))]}, title, z, objects=objects)


def measure_filter(name: str, measure_name: str, kind: int, value: int) -> dict[str, Any]:
    """Visual-level filter on a measure. ComparisonKind: 0 =, 1 >, 2 >=, 3 <, 4 <=."""
    return {
        "name": name,
        "field": measure(measure_name),
        "type": "Advanced",
        "filter": {
            "Version": 2,
            "From": [{"Name": "m", "Entity": M, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "Comparison": {
                            "ComparisonKind": kind,
                            "Left": {
                                "Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": measure_name}
                            },
                            "Right": {"Literal": {"Value": f"{value}L"}},
                        }
                    }
                }
            ],
        },
    }


# --------------------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------------------
TC = column("dim_time_control", "category_label")
BAND = column("dim_elo_band", "elo_band")
FAMILY = level("dim_opening", "Ouverture", "Famille")
FULL_NAME = level("dim_opening", "Ouverture", "Nom complet")


def page_overview() -> list[dict[str, Any]]:
    return [
        slicer("slicerCadence", (20, 16, 300, 64), TC, "Cadence", 1),
        slicer("slicerElo", (336, 16, 300, 64), BAND, "Tranche Elo", 2),
        slicer(
            "slicerMinParties", (652, 16, 300, 64), column("Min Parties", "Min Parties"), "Min. parties par groupe", 3
        ),
        card("kpiParties", (20, 96, 300, 110), "Nb Parties", "Parties analysées", 4),
        card("kpiScoreBlancs", (336, 96, 300, 110), "Score Moyen Blancs", "Score moyen des Blancs", 5),
        card("kpiNulles", (652, 96, 300, 110), "% Nulles", "Parties nulles", 6),
        card("kpiTemps", (968, 96, 292, 110), "% Défaites au Temps", "Défaites au temps", 7),
        visual(
            "donutResultats",
            "donutChart",
            (20, 222, 400, 478),
            {"Y": [projection(measure(m)) for m in ("% Victoires Blancs", "% Nulles", "% Victoires Noirs")]},
            "Répartition des résultats",
            8,
            subtitle="Victoires Blancs, nulles et victoires Noirs",
        ),  # fmt: skip
        visual(
            "colPartiesCadence",
            "columnChart",
            (436, 222, 824, 230),
            {"Category": [projection(TC)], "Series": [projection(BAND)], "Y": [projection(measure("Nb Parties"))]},
            "Parties par cadence et tranche Elo",
            9,
        ),  # fmt: skip
        visual(
            "barScoreTranche",
            "clusteredBarChart",
            (436, 468, 824, 232),
            {"Category": [projection(BAND)], "Y": [projection(measure("Score Moyen Blancs"))]},
            "Score moyen des Blancs par tranche Elo",
            10,
            objects={"labels": [{"properties": {"show": lit(True)}}]},
        ),  # fmt: skip
    ]


def page_openings() -> list[dict[str, Any]]:
    return [
        slicer("slicerElo", (20, 16, 300, 64), BAND, "Tranche Elo", 1),
        slicer("slicerCadence", (336, 16, 300, 64), TC, "Cadence", 2),
        slicer("slicerCouleur", (652, 16, 300, 64), column("agg_opening_band_tc", "color"), "Camp (Blancs / Noirs)", 3),
        visual(
            "comboTopOuvertures",
            "lineClusteredColumnComboChart",
            (20, 96, 740, 330),
            {
                "Category": [projection(FAMILY, active=True), projection(FULL_NAME, active=False)],
                "Y": [projection(measure("Nb Parties Ouverture"))],
                "Y2": [projection(measure("Taux Victoire Ouverture"))],
            },
            "Top 10 des ouvertures : popularité et taux de victoire",
            4,
            sort=(measure("Nb Parties Ouverture"), "Descending"),
            filters=[measure_filter("filtreTop10", "Rang Ouverture", 4, 10)],
            subtitle="Colonnes : nombre de parties ; ligne : taux de victoire du camp choisi. Explorer : famille > variante",
        ),  # fmt: skip
        visual(
            "tableClassement",
            "tableEx",
            (776, 96, 484, 330),
            {
                "Values": [projection(column("dim_opening", "family"))]
                + [
                    projection(measure(m))
                    for m in (
                        "Rang Ouverture",
                        "Nb Parties Ouverture",
                        "% Popularité Ouverture",
                        "Taux Victoire Ouverture",
                        "Score vs Attendu Ouverture",
                    )
                ]
            },
            "Classement des familles d'ouvertures",
            5,
            sort=(measure("Nb Parties Ouverture"), "Descending"),
        ),  # fmt: skip
        visual(
            "matrixScoreTranche",
            "pivotTable",
            (20, 442, 1240, 258),
            {
                "Rows": [projection(FAMILY, active=True), projection(FULL_NAME, active=False)],
                "Columns": [projection(BAND)],
                "Values": [projection(measure("Score Blancs Ouverture"))],
            },
            "Score des Blancs par ouverture et tranche Elo",
            6,
            sort=(measure("Score Blancs Ouverture"), "Descending"),
            subtitle="Vide = moins de parties que le minimum requis",
        ),  # fmt: skip
    ]


def page_elo_time() -> list[dict[str, Any]]:
    return [
        slicer("slicerCadence", (20, 16, 300, 64), TC, "Cadence", 1),
        slicer("slicerElo", (336, 16, 300, 64), BAND, "Tranche Elo", 2),
        card("kpiCalibration", (652, 16, 300, 64), "Écart Calibration", "Écart calibration (réel − attendu)", 3),
        visual(
            "lineCalibration",
            "lineChart",
            (20, 96, 740, 300),
            {
                "Category": [projection(column("fact_games", "rating_gap_bucket"))],
                "Y": [projection(measure("Score Moyen Blancs")), projection(measure("Score Attendu Elo"))],
            },
            "Calibration Elo : score réel vs score attendu",
            4,
            sort=(column("fact_games", "rating_gap_bucket"), "Ascending"),
            subtitle="Par écart de classement (Blancs − Noirs), tranches de 50 points",
        ),  # fmt: skip
        visual(
            "colDefaitesTemps",
            "clusteredColumnChart",
            (776, 96, 484, 300),
            {
                "Category": [projection(BAND)],
                "Series": [projection(TC)],
                "Y": [projection(measure("% Défaites au Temps"))],
            },
            "Défaites au temps par tranche Elo et cadence",
            5,
        ),  # fmt: skip
        visual(
            "lineTempsOuverture",
            "lineChart",
            (20, 412, 1240, 288),
            {
                "Category": [projection(column("agg_time_used_band_tc", "time_used_bin_pct"))],
                "Series": [projection(TC)],
                "Y": [projection(measure("Score Joueur"))],
            },
            "Temps consommé sur les 10 premiers coups vs score du joueur",
            6,
            sort=(column("agg_time_used_band_tc", "time_used_bin_pct"), "Ascending"),
            subtitle="Axe : part du temps de base utilisée (tranches de 5 %)",
        ),  # fmt: skip
    ]


def page_activity() -> list[dict[str, Any]]:
    return [
        slicer("slicerCadence", (20, 16, 300, 64), TC, "Cadence", 1),
        slicer("slicerElo", (336, 16, 300, 64), BAND, "Tranche Elo", 2),
        visual(
            "matrixHeatmap",
            "pivotTable",
            (20, 96, 1240, 330),
            {
                "Rows": [projection(column("dim_date", "weekday_name"))],
                "Columns": [projection(column("fact_games", "hour"))],
                "Values": [projection(measure("Parties par Jour"))],
            },
            "Carte de chaleur : parties par jour et heure (UTC)",
            3,
            subtitle="Nombre moyen de parties par jour calendaire ; couleur de fond = intensité",
        ),  # fmt: skip
        visual(
            "comboHeure",
            "lineClusteredColumnComboChart",
            (20, 442, 1240, 258),
            {
                "Category": [projection(column("fact_games", "hour"))],
                "Y": [projection(measure("% Défaites au Temps"))],
                "Y2": [projection(measure("Score Moyen Blancs"))],
            },
            "Score des Blancs et défaites au temps selon l'heure (UTC)",
            4,
            sort=(column("fact_games", "hour"), "Ascending"),
        ),  # fmt: skip
    ]


PAGES = [
    ("vue_ensemble", "Vue d'ensemble", page_overview),
    ("ouvertures", "Explorateur d'ouvertures", page_openings),
    ("elo_temps", "Elo & gestion du temps", page_elo_time),
    ("quand_joue_t_on", "Quand joue-t-on ?", page_activity),
]


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    definition = REPORT / "definition"
    if definition.exists():
        shutil.rmtree(definition)

    write_json(POWERBI / "EloScope.pbip", {
        "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": "EloScope.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })  # fmt: skip
    write_json(REPORT / "definition.pbir", {
        "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": "../EloScope.SemanticModel"}},
    })  # fmt: skip
    write_json(definition / "version.json", {
        "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    })  # fmt: skip
    versions = {"visual": "2.13.0", "page": "2.1.0", "report": "3.3.0"}
    write_json(definition / "report.json", {
        "$schema": f"{SCHEMA}/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {"customTheme": {"name": THEME_FILE, "reportVersionAtImport": versions, "type": "RegisteredResources"}},
        "resourcePackages": [{
            "name": "RegisteredResources",
            "type": "RegisteredResources",
            "items": [{"name": THEME_FILE, "path": THEME_FILE, "type": "CustomTheme"}],
        }],
        "settings": {
            "useStylableVisualContainerHeader": True,
            "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True,
            "useEnhancedTooltips": True,
        },
    })  # fmt: skip
    write_json(definition / "pages" / "pages.json", {
        "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [name for name, _, _ in PAGES],
        "activePageName": PAGES[0][0],
    })  # fmt: skip
    for name, display, builder in PAGES:
        page_dir = definition / "pages" / name
        write_json(page_dir / "page.json", {
            "$schema": PAGE_SCHEMA, "name": name, "displayName": display,
            "displayOption": "FitToPage", "height": 720, "width": 1280,
        })  # fmt: skip
        for vis in builder():
            write_json(page_dir / "visuals" / vis["name"] / "visual.json", vis)

    theme_target = REPORT / "StaticResources" / "RegisteredResources" / THEME_FILE
    theme_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(POWERBI / "theme.json", theme_target)
    print(f"report written to {REPORT.relative_to(ROOT)} ({len(PAGES)} pages)")


if __name__ == "__main__":
    main()
