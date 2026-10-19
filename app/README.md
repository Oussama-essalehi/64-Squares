# « Analyse mes parties » — application Streamlit

Compare les parties d'un joueur Lichess avec les 1 958 145 parties de l'échantillon de
septembre 2026, au même niveau (tranche Elo), à la même cadence et avec la même couleur.

## Ce que fait l'application

1. Récupère les parties classées récentes d'un pseudo via l'API publique Lichess
   (`/api/games/user/{pseudo}`, avec les horloges), ou lit un fichier PGN exporté depuis Lichess,
   ou charge le **profil de démonstration** (300 parties anonymes, joueur composite 1500–1600).
2. Applique exactement les règles de nettoyage du projet (`src/eloscope/clean.py`).
3. Compare le joueur avec des tables de référence agrégées (`app/data/baseline_*.csv`, au moins
   1 000 parties par groupe) : score, défaites au temps, temps consommé sur 10 coups, ouvertures,
   heure de jeu.
4. Affiche des conseils uniquement quand l'écart dépasse la marge d'erreur à 95 % (au moins
   10 parties du joueur).

Rien n'est stocké : les parties sont analysées en mémoire. Le pseudo n'est utilisé que pour
retrouver la couleur du joueur dans chaque partie.

## Lancer en local

```bash
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

## Déployer gratuitement (Streamlit Community Cloud)

1. Se connecter sur <https://share.streamlit.io> avec le compte GitHub qui possède le dépôt.
2. *Create app* → dépôt `Oussama-essalehi/64-Squares`, branche `main`, fichier
   `app/streamlit_app.py`.
3. *Advanced settings* : Python 3.11 ou plus récent. Les dépendances sont lues dans
   `app/requirements.txt`, le thème dans `.streamlit/config.toml`.
4. Déployer, puis copier l'URL publique dans le README principal (section « Essayer »).

Si l'API Lichess refuse les requêtes depuis le serveur d'hébergement, l'application l'indique et
propose l'import d'un fichier PGN, qui fonctionne partout.

## Mettre à jour les tables de référence

`python run.py export` régénère `app/data/baseline_*.csv` et `opening_roots.csv` depuis la base
DuckDB. Le profil de démonstration se reconstruit avec `python tools/build_demo_pgn.py`.
