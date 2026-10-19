# Power BI — guide de construction (EloScope.pbip)

Ce guide permet d'ouvrir le projet, de le connecter aux données et de **reconstruire chaque
visuel à la main** si la mise en page PBIR ne s'affiche pas comme prévu.

- Rapport : `EloScope.Report/` (format PBIR, généré par `tools/generate_report.py`)
- Modèle sémantique : `EloScope.SemanticModel/` (format TMDL)
- Thème : `theme.json` (copié dans `EloScope.Report/StaticResources/RegisteredResources/EloScopeTheme.json`)
- Validation : `python tools/validate_pbip.py` (schémas JSON publiés par Microsoft + références
  de champs) et `dotnet run --project tools/TmdlValidate` (analyse du TMDL par la bibliothèque
  Microsoft Tabular Object Model)

## 0. Prérequis

1. Power BI Desktop (Windows), version récente avec **Fichier > Options > Fonctionnalités en
   préversion** : « Format de rapport Power BI Project (PBIR) » et « Format de modèle TMDL »
   activés (ils sont activés par défaut dans les versions récentes).
2. Les CSV gold générés : `python run.py all` (ou `python run.py model export` si la base DuckDB
   existe déjà). Le dossier `data/gold/` doit contenir les 7 fichiers CSV listés dans
   `data/gold/manifest.json`. `fact_games.csv` (~200 Mo) n'est pas versionné : il faut le
   régénérer localement.

## 1. Ouvrir le projet et régler `DataFolder`

1. Ouvrir `powerbi/EloScope.pbip`.
2. **Accueil > Transformer les données > Modifier les paramètres** : renseigner `DataFolder` avec
   le chemin **absolu** du dossier gold, par exemple `C:\Projets\64-Squares\data\gold\`
   (la barre oblique finale est ajoutée automatiquement si elle manque).
3. **Accueil > Actualiser**. Le chargement prend une à deux minutes (environ 2 millions de
   lignes dans `fact_games`).
4. Si l'actualisation échoue sur un fichier : vérifier le chemin, puis dans Power Query que
   l'étape `Typed` utilise bien la culture `en-US` (séparateur décimal « . »).

## 2. Modèle (à vérifier dans la vue Modèle)

| Table | Rôle | Clé |
|---|---|---|
| `fact_games` | faits, une ligne par partie | `date_key`, `opening_key`, `time_control_key`, `elo_band_key` |
| `agg_opening_band_tc` | agrégat ouverture × tranche × cadence × couleur | `opening_key`, `elo_band_key`, `time_control_key` |
| `agg_time_used_band_tc` | agrégat temps consommé × tranche × cadence × couleur | `elo_band_key`, `time_control_key` |
| `dim_date` | calendrier (**marquée comme table de dates** sur `date`) | `date_key` |
| `dim_opening` | ouvertures, hiérarchie **Ouverture** : Famille > Nom complet | `opening_key` |
| `dim_time_control` | cadences, `category_label` trié par `category_order` | `time_control_key` |
| `dim_elo_band` | tranches Elo, `elo_band` trié par `sort_order` | `elo_band_key` |
| `Min Parties` | paramètre de simulation (0 à 20 000, pas de 250) | — |
| `_Mesures` | toutes les mesures DAX | — |

Les 9 relations sont **plusieurs-à-un, filtrage dans un seul sens**, des tables de faits et
d'agrégats vers les dimensions. Si une relation manque : la recréer par glisser-déposer de la clé
de la table de faits vers la clé de la dimension (cardinalité *Plusieurs à un*, direction
*Unique*).

Mesures (dossier d'affichage) : `0. Paramètres` (Valeur Min Parties), `1. Volume`
(Nb Parties, Parties par Jour), `2. Résultats` (% Victoires Blancs, % Nulles, % Victoires Noirs, Score Moyen
Blancs), `3. Elo` (Score Attendu Elo, Écart Calibration), `4. Gestion du temps`
(% Défaites au Temps, Nb Parties Joueur, Score Joueur, % Perdues au Temps (Joueur)),
`5. Ouvertures` (Nb Parties Ouverture, % Popularité Ouverture, Rang Ouverture, Taux Victoire
Ouverture, Score Blancs Ouverture, Score vs Attendu Ouverture). Chaque mesure a une description
(infobulle dans le volet Données).

**Règle du minimum d'échantillon** : tous les taux renvoient BLANK quand le groupe compte moins
de parties que `[Valeur Min Parties]` (1 000 par défaut, modifiable avec le segment
« Min. parties par groupe » de la page 1).

## 3. Mise en forme commune

- Thème : **Affichage > Thèmes > Parcourir les thèmes** > `powerbi/theme.json` si le thème
  personnalisé n'est pas déjà appliqué (palette échiquier : brun `#B58863`, crème `#F0D9B5`,
  noir `#262421`, vert `#6D8B3A`, bleu `#3C6E91`, rouge `#B33A3A`).
- Taille de page : 1280 × 720, affichage « Ajuster à la page ».
- Chaque visuel a un **titre** (Format > Général > Titre) ; les positions ci-dessous sont en
  pixels (x, y, largeur, hauteur).
- Segments : style « Liste déroulante », sélection multiple autorisée.

## 4. Page 1 — Vue d'ensemble

| # | Visuel | Champs | Position | Titre / mise en forme |
|---|---|---|---|---|
| 1 | Segment | `dim_time_control[category_label]` | 20, 16, 300, 64 | « Cadence » |
| 2 | Segment | `dim_elo_band[elo_band]` | 336, 16, 300, 64 | « Tranche Elo » |
| 3 | Segment | `Min Parties[Min Parties]` | 652, 16, 300, 64 | « Min. parties par groupe » ; sélection unique, valeur 1 000 |
| 4 | Carte | `[Nb Parties]` | 20, 96, 300, 110 | « Parties analysées » ; étiquette de catégorie masquée |
| 5 | Carte | `[Score Moyen Blancs]` | 336, 96, 300, 110 | « Score moyen des Blancs » |
| 6 | Carte | `[% Nulles]` | 652, 96, 300, 110 | « Parties nulles » |
| 7 | Carte | `[% Défaites au Temps]` | 968, 96, 292, 110 | « Défaites au temps » |
| 8 | Graphique en anneau | Valeurs : `[% Victoires Blancs]`, `[% Nulles]`, `[% Victoires Noirs]` | 20, 222, 400, 478 | « Répartition des résultats » ; étiquettes de détail en % ; couleurs brun / gris / noir |
| 9 | Histogramme empilé | Axe X : `category_label` ; Légende : `elo_band` ; Axe Y : `[Nb Parties]` | 436, 222, 824, 230 | « Parties par cadence et tranche Elo » |
| 10 | Graphique à barres groupées | Axe Y : `elo_band` ; Axe X : `[Score Moyen Blancs]` | 436, 468, 824, 232 | « Score moyen des Blancs par tranche Elo » ; étiquettes de données activées ; ligne de référence constante 50 % (Analyse > Ligne constante) |

## 5. Page 2 — Explorateur d'ouvertures

| # | Visuel | Champs | Position | Titre / mise en forme |
|---|---|---|---|---|
| 1 | Segment | `dim_elo_band[elo_band]` | 20, 16, 300, 64 | « Tranche Elo » ; idéalement sélection unique |
| 2 | Segment | `dim_time_control[category_label]` | 336, 16, 300, 64 | « Cadence » |
| 3 | Segment | `agg_opening_band_tc[color]` | 652, 16, 300, 64 | « Camp (Blancs / Noirs) » ; sélection unique (sinon Blancs par défaut) |
| 4 | Graphique en courbes et histogramme groupé | Axe X : hiérarchie `dim_opening[Ouverture]` (Famille, Nom complet) ; Axe Y colonnes : `[Nb Parties Ouverture]` ; Axe Y ligne : `[Taux Victoire Ouverture]` | 20, 96, 740, 330 | « Top 10 des ouvertures : popularité et taux de victoire » ; tri décroissant sur Nb Parties Ouverture ; **filtre du visuel : `Rang Ouverture` inférieur ou égal à 10** ; forage activé (flèche ↓ puis clic sur une famille pour voir ses variantes) |
| 5 | Table | `dim_opening[family]`, `[Rang Ouverture]`, `[Nb Parties Ouverture]`, `[% Popularité Ouverture]`, `[Taux Victoire Ouverture]`, `[Score vs Attendu Ouverture]` | 776, 96, 484, 330 | « Classement des familles d'ouvertures » ; tri décroissant sur Nb Parties Ouverture ; mise en forme conditionnelle (échelle de couleurs) sur Score vs Attendu Ouverture |
| 6 | Matrice | Lignes : hiérarchie `dim_opening[Ouverture]` ; Colonnes : `dim_elo_band[elo_band]` ; Valeurs : `[Score Blancs Ouverture]` | 20, 442, 1240, 258 | « Score des Blancs par ouverture et tranche Elo » ; mise en forme conditionnelle > Couleur d'arrière-plan > Échelle de couleurs (min `#3C6E91`, centre 50 % `#F7F4EF`, max `#B58863`) ; les cellules vides = échantillon insuffisant |

## 6. Page 3 — Elo & gestion du temps

| # | Visuel | Champs | Position | Titre / mise en forme |
|---|---|---|---|---|
| 1 | Segment | `dim_time_control[category_label]` | 20, 16, 300, 64 | « Cadence » |
| 2 | Segment | `dim_elo_band[elo_band]` | 336, 16, 300, 64 | « Tranche Elo » |
| 3 | Carte | `[Écart Calibration]` | 652, 16, 300, 64 | « Écart calibration (réel − attendu) » |
| 4 | Graphique en courbes | Axe X : `fact_games[rating_gap_bucket]` (type d'axe *Continu*) ; Axe Y : `[Score Moyen Blancs]`, `[Score Attendu Elo]` | 20, 96, 740, 300 | « Calibration Elo : score réel vs score attendu » ; tri croissant sur l'axe ; Score Attendu en gris pointillé |
| 5 | Histogramme groupé | Axe X : `elo_band` ; Légende : `category_label` ; Axe Y : `[% Défaites au Temps]` | 776, 96, 484, 300 | « Défaites au temps par tranche Elo et cadence » |
| 6 | Graphique en courbes | Axe X : `agg_time_used_band_tc[time_used_bin_pct]` ; Légende : `category_label` ; Axe Y : `[Score Joueur]` | 20, 412, 1240, 288 | « Temps consommé sur les 10 premiers coups vs score du joueur » ; titre d'axe X : « Part du temps de base utilisée (%) » |

## 7. Page 4 — Quand joue-t-on ?

| # | Visuel | Champs | Position | Titre / mise en forme |
|---|---|---|---|---|
| 1 | Segment | `dim_time_control[category_label]` | 20, 16, 300, 64 | « Cadence » |
| 2 | Segment | `dim_elo_band[elo_band]` | 336, 16, 300, 64 | « Tranche Elo » |
| 3 | Matrice (carte de chaleur) | Lignes : `dim_date[weekday_name]` ; Colonnes : `fact_games[hour]` ; Valeurs : `[Parties par Jour]` | 20, 96, 1240, 330 | « Carte de chaleur : parties par jour et heure (UTC) » ; mise en forme conditionnelle > Couleur d'arrière-plan > Échelle de couleurs (`#FBF6EE` → `#5C3B22`) ; taille de police 9 ; totaux désactivés |
| 4 | Graphique en courbes et histogramme groupé | Axe X : `fact_games[hour]` ; Colonnes : `[% Défaites au Temps]` ; Ligne : `[Score Moyen Blancs]` | 20, 442, 1240, 258 | « Score des Blancs et défaites au temps selon l'heure (UTC) » ; tri croissant sur l'heure ; axe X de type *Catégoriel* |

## 8. Captures d'écran pour le README

Après actualisation, exporter chaque page (Fichier > Exporter > PDF, ou capture d'écran) et
enregistrer : `reports/figures/dashboard_overview.png`, `dashboard_openings.png`,
`dashboard_elo_time.png`, `dashboard_activity.png`.

## 9. Régénérer et valider les fichiers

```bash
python tools/generate_report.py          # réécrit EloScope.Report/definition
python tools/validate_pbip.py            # schémas JSON + références de champs
dotnet run --project tools/TmdlValidate  # analyse du TMDL (nécessite .NET 8)
```

Après une modification dans Power BI Desktop, enregistrer le projet : Desktop réécrit les
fichiers PBIR/TMDL (avec ses propres identifiants) ; ne plus relancer le générateur ensuite pour
ne pas écraser les modifications manuelles.
