# Visual design

One visual system is shared by the Python charts (`src/eloscope/charts.py`), the Power BI theme
(`powerbi/theme.json`), the web dashboard (`site/`) and the Streamlit app (`app/`).

## Principle

The **chrome** carries the chessboard identity (cream surfaces, light-brown headers, warm ink).
The **data colours** follow a validated palette: each set was checked for lightness band,
chroma, colour-vision-deficiency (CVD) separation, normal-vision separation and contrast against
the chart surface before use. Colour is assigned by the job it does:

| Job | Data | Scheme | Colours |
|---|---|---|---|
| Identity (categorical) | Time controls, in speed order | Fixed slot order, never cycled | UltraBullet `#2a78d6`, Bullet `#eb6834`, Blitz `#1baf7a`, Rapide `#eda100`, Classique `#e87ba4` |
| Polarity (diverging) | Results, White's score around 50 % | Two poles + neutral midpoint | White `#c8732a` · draw / 50 % `#d3d1cb` (`#f0efec` on scales) · Black `#2a5a9a` |
| Order (ordinal) | Elo bands | One brown hue, light → dark | `#d2a679`, `#b07d4f`, `#86562d`, `#5a3518` |
| Magnitude (sequential) | Activity heatmap | One brown hue, light → dark | `#f7f1e8` → `#4a2b12` |

## Validation results (light surface)

| Palette | Result |
|---|---|
| Time controls (5 slots, adjacent pairs) | All checks pass: worst CVD ΔE 9.1 (target ≥ 8), worst normal-vision ΔE 19.6 (floor 15). Three slots are below 3:1 contrast, so lines carry **direct labels** and every web chart has a table view |
| Result poles | Pass: CVD ΔE 23.5, normal-vision ΔE 30.1, both ≥ 3:1 contrast |
| Elo band ramp (ordinal) | Pass: monotone lightness, every step ΔL ≥ 0.06, light end 2.16:1, single hue (10° spread) |

The previous palette (board brown, olive green, slate blue, near-black, cream) failed: brown and
green were indistinguishable for protanopes (ΔE 5.1) and the cream and near-black sat outside the
usable lightness band. Elo bands also moved from categorical colours to an ordinal ramp, because
bands are ordered.

## Rules applied

- **No dual-axis chart.** Two measures with different scales become two panels sharing the x
  axis (results by hour) or two separate visuals (Power BI hour page, opening popularity).
- Thin marks: 2 px lines, 8 px markers with a 2 px surface ring, 2 px gaps between bars and
  stacked segments.
- A legend for every chart with two or more series; lines that reach the right edge are also
  labelled directly. Text always uses ink colours, never the series colour.
- Narrow axes are only used when the subtitle says so (e.g. White's score shown on 45–55 %).
- Rates below the minimum sample (1,000 games) are hidden, never shown in a lighter colour.
