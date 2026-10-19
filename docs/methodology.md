# Methodology

## 1. Source

- **Lichess open database**, standard rated games, month **2026-09** (the most recent complete
  month at build time): `lichess_db_standard_rated_2026-09.pgn.zst`, **29.2 GB compressed,
  89,616,462 games** (`counts.txt`). License CC0.
- **`lichess-org/chess-openings`** (files `a.tsv` … `e.tsv`: ECO, name, moves; 3,865 lines), used
  to cross-check opening names and families.

PGN headers were checked on the first 12,094 games of the month before writing the parser.
Two facts differ from the initial brief and are handled explicitly:

| Observation | Handling |
|---|---|
| `Termination` has values `Normal`, `Time forfeit`, `Abandoned`, `Rules infraction`, but also `Insufficient material` (timeout against a lone king, scored as a draw) and `Unterminated` | Whitelist: only `Normal` and `Time forfeit` are kept (rule 2) |
| Swiss tournament games read `Blitz swiss https://lichess.org/swiss/…`, without the `Rated` prefix used by arena and casual pairing | They come from the *rated* monthly file, so they are rated: kept by rule 1 (9,383 games in the sample) |

## 2. Streaming and sampling (`src/eloscope/ingest.py`)

The full file is never written to disk (it would also exceed the available disk space).

1. **Download as parallel HTTP range requests** (4 workers × 16 MB). A single long-lived
   connection was throttled to 4–7 MB/s; independent range requests sustain ~20–25 MB/s. Ranges
   are reassembled in order, each is length-checked and retried on failure.
2. **Streaming decompression** with `zstandard.decompressobj(read_across_frames=True)`.
3. **Game splitting** on the byte sequence `"\n\n[Event "`, a C-level `bytes.split`: the
   ~200 GB of decompressed text are scanned at about 350 MB/s without parsing anything.
4. **Bernoulli sampling**: each game *i* receives one uniform draw from
   `numpy.random.default_rng(seed=42)` in file order and is kept if *u<sub>i</sub>* < *p*, with
   *p* = 2,000,000 / 89,616,462 = 0.0223. Because exactly one draw is consumed per game in file
   order, the selection does not depend on how the bytes are chunked (tested). Expected sample
   size 2,000,000 ± 1,400; obtained **2,000,201**.
   Bernoulli sampling was preferred over reservoir sampling because the month's game count is
   published in advance, it needs no memory for a reservoir and it lets each batch be written
   immediately.
5. **Parsing of the selected games only**, with a fast regex parser: headers, ply count (SAN
   tokens once comments, move numbers and results are removed), `[%clk h:mm:ss]` clocks and the
   presence of `[%eval]`. The ply count is checked against a full `python-chess` parse on the
   24 fixture games (tests).
6. **Privacy**: usernames are replaced by `sha256(salt + lower(username))[:16]`, the salt
   being read from the git-ignored `.env`. Clear usernames are never stored outside the raw
   cache, and nothing below the aggregate level is exported to Power BI.
7. **Batches and resume**: every ~100,000 sampled games, a Parquet batch, a zstd copy of the
   raw sampled PGN (`data/raw/sample_2026-09/`, 0.8 GB, the "download cache") and a checkpoint
   are written atomically. A rerun skips finished batches; once the cache is complete, the
   pipeline no longer uses the network and rebuilds the Parquet batches in parallel.

All 89,616,462 games announced by `counts.txt` were scanned (exact match). Full run: about 28
minutes of streaming; a rerun from the cache: 3 minutes end to end.

## 3. Cleaning rules (`src/eloscope/clean.py`)

Rules are applied in this order; counts are from `data/processed/cleaning_report.json`.

| # | Rule | Rows before | Rows after | Removed |
|---|---|---:|---:|---:|
| R0 | Duplicate game ids | 2,000,201 | 2,000,201 | 0 |
| R1 | Rated standard games only (no variant, no casual) — `Event` speed in UltraBullet/Bullet/Blitz/Rapid/Classical/Correspondence, no `Variant` header | 2,000,201 | 2,000,201 | 0 |
| R2 | `Termination` ∈ {Normal, Time forfeit} and a valid result (removes 9,425 Abandoned, 552 Unterminated, 302 Insufficient material, 54 Rules infraction) | 2,000,201 | 1,989,868 | 10,333 |
| R3 | At least 10 plies (5 moves each) | 1,989,868 | 1,968,850 | 21,018 |
| R4 | No `BOT` title on either side | 1,968,850 | 1,959,293 | 9,557 |
| R5 | Both ratings present, numeric and within 400–3200 | 1,959,293 | 1,959,167 | 126 |
| R6 | Valid `base+increment` time control — correspondence (`-`) excluded | 1,959,167 | 1,958,145 | 1,022 |
| | **Clean table** | | **1,958,145** | **97.9 % kept** |

R1 removes nothing because the monthly file only contains rated standard games; the rule is kept
(and tested on synthetic variant and casual games) so the pipeline stays correct on other inputs.

Derived columns:

7. **Time control category** from `TimeControl` = `base+increment` with Lichess's rule on the
   estimated duration *base + 40 × increment* (seconds): < 30 ultrabullet, < 180 bullet,
   < 480 blitz, < 1500 rapid, otherwise classical. The category matches the speed written in
   the `Event` header for **100 %** of games.
8. **Elo band** from the average rating of both players: < 1200, 1200–1599, 1600–1999, 2000+.
   **Rating gap** = White − Black, bucketed to the nearest 50 points (bucket 0 = [−25, 25)) and
   capped at ±600 (0.68 % of games have |gap| > 600).
9. **Opening family** = text of `Opening` before `:`; the full name is kept. 99.87 % of names
   exist in the `lichess-org/chess-openings` reference; families are derived from the name in
   all cases. 146 families, 2,756 full names.
10. **Results**: `white_score` (1 / 0.5 / 0), `winner` (white/black/draw), `lost_on_time`
    (decisive game ended by `Time forfeit`) and `time_loser`.
11. **Clock features** (only with one clock comment per ply — 100 % of clean games): time used
    by each side over its first 10 moves = clk₁ + 9 × increment − clk₁₀ (on Lichess the first
    move neither consumes time nor adds the increment), floored at 0, divided by the base time
    and capped at 1. Under a tournament **berserk** (start clock below 75 % of the base, 1.6 % of
    games) the increment is removed and the share is computed on the halved clock. Not available
    for games shorter than 20 plies or with a zero base time: **3.2 %** of games.
12. Output: `data/processed/games_clean.parquet` (47 columns, see `docs/data_dictionary.md`).

## 4. Data model (`sql/`)

DuckDB star schema (`data/eloscope.duckdb`): `fact_games` (1,958,145 rows) and the dimensions
`dim_opening` (2,905 ECO × name pairs), `dim_time_control` (538 time controls), `dim_elo_band` (4)
and `dim_date` (30 days). Integrity checks after the build: no row lost in the joins, no
duplicate game id, no orphan date. Views: `v_games` (fact + dimensions) and `v_player_games`
(two rows per game, one per colour).

## 5. Statistical methods (`src/eloscope/analyze.py`)

- **Minimum sample rule**: every rate shown (SQL `HAVING COUNT(*) >= min_games`, Python, Power BI
  measures) requires **1,000 games** per group (`config.yaml: analysis.min_games`).
- **Wilson 95 % confidence intervals** for win, draw and loss rates
  (`statsmodels.proportion_confint(method="wilson")`); normal interval for mean scores.
- **Chi-square test of independence**, opening family (families with ≥ 1,000 games) × result
  (white / draw / black), per Elo band, with **Cramér's V** = √(χ² / (n · (min(r, c) − 1))). With
  hundreds of thousands of games every p-value is tiny, so the effect size is what is
  interpreted (V < 0.1 = negligible).
- **Elo calibration**: per rating-gap bucket and time control, mean expected score
  *E* = 1 / (1 + 10^(−gap/400)) computed game by game vs mean actual score; **mean absolute
  calibration error** weighted by games. A colour-neutral version from the favourite's point
  of view separates calibration from White's first-move advantage.
- **Logistic regression** (statsmodels `logit`) of a White win on decisive games with clock
  data (1,815,315 games): rating gap (per 100 points), time control (reference blitz), Elo band
  (reference 1600–1999) and the clock share used by each side in its first 10 moves (per 10
  points). Coefficients are reported as odds ratios with 95 % intervals.
- **Opening recommendations** use the score of the side minus its Elo expected score, so that
  an opening is not credited for being played by stronger players.

## 6. Opening families: who chooses them

Each family is drawn at its defining position: the shortest entry of the reference dataset named
exactly like the family. The side that played the last move of that line chose the opening (odd
number of plies = White, even = Black): Sicilian `1. e4 c5` → Black, Italian
`1. e4 e5 2. Nf3 Nc6 3. Bc4` → White. The rule was checked by hand on the 90 families with at
least 2,000 games; three roots ending with a move of the other side are corrected explicitly
(King's Indian `1. d4 Nf6 2. c4 g6`, Old Indian `1. d4 Nf6 2. c4 d6`, Rat Defense: Black).

## 7. Personal analysis (app)

The app downloads a player's recent rated games (Lichess API, with clocks) or reads an exported
PGN, runs the same parser and cleaning rules, and compares the player with the baseline of the
**same Elo band, time control and colour**, weighted by the player's own mix of games. A tip is
shown only with at least 10 games of the player and when the gap exceeds the 95 % sampling margin
(1.96 · √(p(1−p)/n)). The demo profile is a composite of 300 random sample games where one side
rated 1500–1600 is renamed, so it describes no real person. Nothing is stored.

## 8. Quality checks

- 140 unit and integration tests (`pytest`): header and clock parsing, ply count vs
  `python-chess`, chunk-independent splitting and sampling, resume after a crash, raw-cache
  rebuild, every cleaning rule on the fixture games, time-control edge values, Elo bands and
  gap buckets, opening families, statistical helpers, the star schema and every SQL query, the
  choosing side of openings, the personal analysis (API errors, PGN formats, noise-aware advice)
  and the integrity of the web dashboard data.
- **SQL vs Python cross-check** (`reports/tables/cross_check.csv`): White's score per Elo band
  recomputed in pandas from the Parquet file and the top-3 opening families of the `< 1200` and
  `2000+` bands — **6/6 identical** (e.g. White's score < 1200 = 0.515481 in both; top-3 2000+
  = Sicilian Defense, Queen's Pawn Game, French Defense in both).
- Weekday activity is divided by the number of calendar days of each weekday: September 2026
  has five Tuesdays and Wednesdays but four of every other day, which would otherwise inflate
  those two days by 25 %.
- Power BI: PBIR files validated against the published Microsoft JSON schemas, every field
  reference checked against the model, TMDL parsed by the Tabular Object Model serializer.

## 9. Limitations

- **One month only** (September 2026): seasonality and rating inflation over time are not
  covered.
- **Online players are not representative** of all chess players (younger, faster time
  controls, anonymous accounts); Lichess ratings (Glicko-2) are not FIDE ratings.
- **Sampling**: 2.2 % of the month; rates carry the intervals shown, rare openings and the
  classical time control have small groups (hidden below 1,000 games).
- **Clock data**: missing for 3.2 % of games (fewer than 20 plies or zero base time).
- **Correlation is not causation**: a player who spends a long time on the first moves may
  already be in a difficult or unfamiliar position; the opening family reflects the choices of
  both players.
- Opening families come from Lichess naming (text before `:`): e.g. "Queen's Pawn Game" groups
  1.d4 d5 lines without 2.c4.
