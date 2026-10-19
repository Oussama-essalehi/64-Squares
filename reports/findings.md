# Résultats — qu'est-ce qui fait vraiment gagner aux échecs ?

**Données** : 1 958 145 parties classées standard de Lichess (septembre 2026), issues d'un
échantillon aléatoire de 2 000 201 parties tirées parmi les 89 616 462 du mois, après nettoyage
(`docs/methodology.md`). 897 800 joueurs distincts (identifiants hachés).
**Règle** : aucun taux n'est publié pour un groupe de moins de 1 000 parties. Toutes les valeurs
ci-dessous proviennent des tables de `reports/tables/` (une table par requête de
`sql/03_analysis_queries.sql`, plus les tables `py_*` calculées en Python) et de
`reports/metrics.json`.

> Score = victoire 1, nulle 0,5, défaite 0. « Points » = points de pourcentage.

## En une phrase

**Le classement explique l'essentiel, la gestion de la pendule vient juste après, la couleur
donne un petit avantage constant, et le choix de l'ouverture pèse très peu** — sauf quelques
lignes qui rapportent nettement plus que l'attendu à certains niveaux.

## Les constats

### 1. L'écart de classement est le premier facteur… mais la formule Elo surestime les favoris

- Dans la régression logistique (1 815 315 parties décisives avec données d'horloge), **+100 points
  d'écart multiplient les chances de victoire des Blancs par 1,44** (IC 95 % : 1,43–1,44) : c'est
  de loin l'effet le plus fort du modèle (`py_logit_white_win.csv`).
- Mais le favori gagne **moins** que ce que promet la formule E = 1 / (1 + 10^(−écart/400)) :
  en blitz, un joueur mieux classé de 200 points devrait marquer 75,7 % et marque 67,9 %
  (−7,8 points) ; à 400 points d'écart, 90,8 % attendus contre 80,9 % réels
  (`q3_favourite_calibration.csv`). Le phénomène est identique en bullet et en rapide.
- Erreur absolue moyenne de calibration (pondérée par le nombre de parties) : **2,8 points en
  bullet, 2,9 en blitz, 3,1 en rapide** (`q3_calibration_error.csv`). Dans 100 % des tranches
  d'écart ≥ 200 points de ces trois cadences, les Blancs favoris font moins bien que la formule.
- Lecture : Lichess utilise Glicko-2 et la formule Elo ne tient pas compte de l'incertitude des
  classements (comptes récents, joueurs en progression) ; l'outsider est sous-coté.

### 2. Trop réfléchir dans l'ouverture coûte cher, et l'incrément protège

- Les joueurs sont classés en déciles selon la part de leur temps de base utilisée sur leurs
  10 premiers coups (`q4_time_used_deciles.csv`). **En blitz, le décile le plus lent (≥ 23 % du
  temps) marque 43,6 % contre 52,3 % pour le plus rapide (≤ 4,4 %)**, et perd au temps
  **21,4 % de ses parties contre 7,1 %** (×3). En bullet : 39,4 % contre 55,1 % de score,
  42,3 % contre 16,9 % de défaites au temps. L'écart de classement moyen de ces déciles reste
  faible (−5,6 et −10,3 points), ce n'est donc pas un simple effet de niveau.
- La régression le confirme à écart Elo et cadence égaux : **chaque tranche de 10 points de
  temps consommé par les Blancs réduit leurs chances de victoire de 26 %** (odds ratio 0,74) ;
  la même chose côté Noirs augmente celles des Blancs (odds ratio 1,33).
- **31,5 % des parties se terminent au temps** ; 52 % en bullet, 23 % en blitz, 10 % en rapide
  (`q4_time_losses.csv`). Avec incrément, la part tombe de 55,3 % à 40,4 % en bullet et de 24,1 %
  à 19,9 % en blitz (`q4_increment_effect.csv`).
- En bullet, la défaite au temps baisse avec le niveau : **61 % des parties sous 1200 Elo contre
  46 % à 2000+**. En blitz et en rapide, elle est quasi identique à tous les niveaux (22–24 % et
  10–11 %).

### 3. Les Blancs ont un avantage petit, constant, qui grandit un peu avec le niveau

- Toutes parties confondues, les Blancs marquent **51,6 %** (49,7 % de victoires, 3,7 % de
  nulles, 46,5 % de défaites ; IC 95 % du score ± 0,07 point), soit **+1,6 point au-delà de ce
  que prédit l'écart de classement** (`q2_white_advantage.csv`).
- Le score des Blancs passe de **51,5 % sous 1200 à 51,9 % à 2000+** (avantage net de
  l'écart Elo : +1,5 → +1,9 point). Le maximum est atteint en **blitz 2000+ (52,3 %)**, le
  minimum en **bullet sous 1200 (50,9 %)** : plus la partie est rapide et le niveau faible, plus
  le trait compte peu face aux erreurs (`fig03_white_score_band_tc.png`).
- Les nulles augmentent avec le niveau : 3,4 % sous 1200, 4,9 % à 2000+ (6,0 % en blitz 2000+).

### 4. Le répertoire change beaucoup avec le niveau

- La **Sicilienne** passe de 4,8 % des parties sous 1200 (6e) à **12,8 % à 2000+ (1re)**.
  À l'inverse, le **King's Pawn Game** (1.e4 e5 sans suite théorique) tombe de 7,8 % (2e) à
  0,6 % (34e), l'**Italienne** de 6,1 % (4e) à 1,8 % (15e), la **Bishop's Opening** de 3,0 % à
  0,45 % (`q1_repertoire_shift.csv`).
- Les ouvertures de flanc montent : **Anglaise** 1,6 % (19e) → 4,7 % (5e), **Zukertort**
  2,4 % → 3,7 %, **Nimzo-Larsen** 0,8 % → 2,8 %. Le **Queen's Pawn Game** reste 1er ou 2e à tous
  les niveaux.
- Concentration : les 10 familles les plus jouées couvrent 52,9 % à 54,8 % des parties de chaque
  tranche (`q1_top_openings_by_band.csv`) ; 146 familles et 2 756 variantes au total.

### 5. L'ouverture influence le résultat… très faiblement

- Le test du khi² (famille d'ouverture × résultat) est **significatif dans toutes les tranches
  (p < 10⁻³⁸)** mais le **V de Cramér ne dépasse pas 0,030** (0,024 à 0,030), bien en dessous du
  seuil d'effet « faible » de 0,1 (`py_chi_square_by_band.csv`, `fig09_cramers_v.png`).
- Avec près de 2 millions de parties, n'importe quelle différence devient « significative » :
  c'est la taille d'effet qui compte. Le choix de l'ouverture explique une part infime de la
  variance des résultats, même si certaines lignes s'écartent de quelques points (constat 6).

### 6. Quelques ouvertures rapportent nettement plus que l'attendu

Mesure : score du camp moins score attendu Elo (corrige l'écart de classement), parmi les
20 familles les plus jouées de chaque tranche, avec IC 95 % (`q6_best_openings_per_band.csv`).
Attention : une « famille » désigne la position atteinte, choisie par l'un **ou** l'autre camp.

| Tranche | Pour les Blancs (score − attendu) | Côté Noirs |
|---|---|---|
| < 1200 | Partie écossaise **+4,8 pts** ± 1,2 (6 688 parties) ; Italienne +2,8 pts (16 541) | Sicilienne +1,1 ± 0,9 ; contre la défense Nimzowitsch (1…Cc6), les Blancs font +4,0 ± 1,4 |
| 1200–1599 | Écossaise **+4,4** ± 0,8 ; contre le Gambit dame refusé, les Blancs font **+4,3** ± 0,8 ; Anglaise +2,7 ± 0,8 | Aucune défense ne dépasse significativement l'attendu (meilleure : gambit Englund +0,6 ± 1,0) ; Caro-Kann et Sicilienne ≈ 0 |
| 1600–1999 | Écossaise **+3,9** ± 0,8 ; Gambit dame refusé +3,3 ± 0,6 ; Espagnole +2,5 ± 0,9 | Scandinave, Caro-Kann, Française : −0,2 à −0,6 pt (≈ 0) |
| 2000+ | Systèmes 1.d4 sans c4 (*Queen's Pawn Game*) **+3,0** ± 0,6 (27 876) ; *Indian Defense* (1.d4 Cf6 sans c4) +3,5 ± 0,9 ; contre la Slave +3,9 ± 1,2 | Scandinave −0,3 ± 0,8 (≈ 0) |

### 7. On joue l'après-midi (UTC), et la nuit coûte des défaites au temps

- Pic d'activité : **16h–18h UTC** (jusqu'à 4 058 parties de l'échantillon par jour et par heure le
  lundi), creux : **1h–3h UTC** (≈ 1 390) — un facteur 2,9 (`q5_activity_heatmap.csv`). Une fois
  rapporté au nombre de jours calendaires (septembre 2026 compte cinq mardis et cinq mercredis),
  l'activité varie peu selon le jour : de 63 171 parties par jour (samedi) à 66 206 (mardi).
- La part de parties perdues au temps monte la nuit : **33,7 % à 4h contre 30,3 % à 16h UTC**
  (`q5_results_by_hour.csv`). À cadence égale l'effet persiste : en bullet 53,9 % la nuit
  (0h–5h) contre 50,9 % l'après-midi, en blitz 24,4 % contre 22,1 % (`q5_night_vs_day.csv`).
- Le score des Blancs, lui, ne bouge pas avec l'heure (51,3 % à 52,0 % selon l'heure).

## Recommandations par niveau

**Moins de 1200**
- Priorité à la pendule : en bullet, 61 % des parties se finissent au temps. Jouer surtout du
  blitz ou du rapide **avec incrément** (la défaite au temps baisse de 1,5 à 15 points selon la cadence).
- Blancs : la **partie écossaise** (1.e4 e5 2.Cf3 Cc6 3.d4) et l'**italienne** rapportent
  2,8 à 4,8 points de plus que l'attendu. Noirs : la **Sicilienne** est la défense la plus
  rentable ; éviter 1…Cc6 contre 1.e4 (défense Nimzowitsch).

**1200–1599**
- Garder un rythme d'ouverture : rester sous ~10 % du temps de base sur les 10 premiers coups
  (décile médian en blitz, toutes tranches) ; au-delà de 23 %, le score est inférieur de
  8,7 points à celui des joueurs les plus rapides.
- Blancs : **écossaise** et **gambit dame** (1.d4 d5 2.c4) — face au gambit dame refusé, les
  Blancs marquent +4,3 points. Noirs : Caro-Kann ou Sicilienne, qui tiennent l'attendu.

**1600–1999**
- Les mêmes armes blanches restent rentables (écossaise +3,9, gambit dame refusé +3,3,
  espagnole +2,5). Côté Noirs, aucune défense ne bat l'attendu : choisir une défense solide et
  bien connue (Caro-Kann, Française, Scandinave) pour **jouer vite** l'ouverture.

**2000+**
- La Sicilienne domine (12,8 % des parties) mais ne surperforme pas ; les **systèmes 1.d4 sans
  c4** et l'**Anglaise** rapportent 2,8 à 3,5 points de plus que l'attendu aux Blancs.
- Le gain se fait au temps et à l'écart réel de niveau : en blitz, l'avantage du trait atteint
  52,3 % ; ne pas compter sur la formule Elo pour estimer ses chances contre un plus faible
  (−8 à −10 points par rapport à la formule à 200–400 points d'écart).

**Pour tous** : éviter les longues sessions de nuit en bullet et en blitz (+2 à +3 points de
défaites au temps à cadence égale, contre moins d'un point en rapide).

## Limites

Un seul mois de données ; joueurs en ligne non représentatifs de tous les joueurs ; échantillon
aléatoire de 2,2 % (marges d'erreur indiquées) ; données d'horloge sur 10 coups absentes pour
3,2 % des parties (parties de moins de 20 demi-coups, base de 0 seconde) ; corrélation ≠
causalité (un joueur qui réfléchit longtemps peut être déjà en difficulté). Détail dans
`docs/methodology.md`.
