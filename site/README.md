# Tableau de bord web

Version web du tableau de bord Power BI, consultable sans rien installer : 4 pages (vue
d'ensemble, ouvertures, Elo & temps, activité), filtres par cadence, tranche Elo et camp, seuil
d'échantillon réglable, mode clair et sombre, vue « Tableau » pour chaque graphique.

- `index.html`, `style.css`, `app.js` : la page (HTML, CSS et JavaScript sans dépendance de build ;
  Plotly.js chargé depuis jsDelivr).
- `data/dashboard.json` : comptes agrégés (jamais de taux précalculés : la page additionne les
  cellules filtrées puis calcule chaque taux, et masque ceux sous le seuil).
- `boards/*.svg` : position de référence de chaque famille d'ouverture.

Régénérer les données : `python run.py export`. Prévisualiser en local :

```bash
python -m http.server 8000 --directory site    # puis http://localhost:8000
```

**Publication** : le workflow `.github/workflows/pages.yml` publie ce dossier sur GitHub Pages à
chaque push sur `main` (à activer une fois : *Settings > Pages > Source : GitHub Actions*). Pour
le servir sur `oussama-essalehi.dev`, copier le dossier dans le site ou ajouter un domaine
personnalisé dans *Settings > Pages*.
