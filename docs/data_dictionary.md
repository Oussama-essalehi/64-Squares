# Data dictionary

All tables are produced by the pipeline (`python run.py all`). Ratings are Lichess (Glicko-2)
ratings at the start of the game. Times are UTC.

## 1. Sampled games — `data/sample/<month>/batch_*.parquet`

Output of `src/eloscope/ingest.py`. One row per sampled game, header values kept as raw strings
(typed and validated in the cleaning step).

| Column | Type | Description |
|---|---|---|
| `game_index` | int64 | Position of the game in the monthly file (0-based); makes the sample reproducible |
| `game_id` | string | Lichess game id, last segment of the `Site` URL |
| `event`, `site`, `utc_date`, `utc_time`, `result`, `white_elo`, `black_elo`, `white_rating_diff`, `black_rating_diff`, `white_title`, `black_title`, `eco`, `opening`, `time_control`, `termination`, `variant` | string | PGN headers `Event`, `Site`, `UTCDate`, `UTCTime`, `Result`, `WhiteElo`, `BlackElo`, `WhiteRatingDiff`, `BlackRatingDiff`, `WhiteTitle`, `BlackTitle`, `ECO`, `Opening`, `TimeControl`, `Termination`, `Variant` (null when absent) |
| `white_hash`, `black_hash` | string | Salted SHA-256 of the lower-cased username, first 16 hex characters. Clear usernames are never stored |
| `plies` | int32 | Number of half-moves |
| `n_clocks` | int32 | Number of `[%clk]` comments |
| `has_eval` | bool | The movetext contains `[%eval]` annotations (computer analysis) |
| `white_clk_start`, `black_clk_start` | float64 | Clock after each side's first move (s); equals the base time, or half of it after a tournament berserk |
| `white_clk_10`, `black_clk_10` | float64 | Clock left after each side's 10th move (s); null for shorter games or games without clocks |

## 2. Clean games — `data/processed/games_clean.parquet`

Output of `src/eloscope/clean.py` (rules in `docs/methodology.md`). Adds:

| Column | Type | Description |
|---|---|---|
| `date`, `hour`, `weekday` | date, int8, int8 | UTC date, hour (0–23) and weekday (0 = Monday) of the game start |
| `event_speed` | string | Speed word of the `Event` header (used as a consistency check) |
| `avg_elo` | float | (WhiteElo + BlackElo) / 2 |
| `elo_band` | string | `< 1200`, `1200-1599`, `1600-1999`, `2000+` from `avg_elo` |
| `rating_gap` | int | WhiteElo − BlackElo |
| `rating_gap_bucket` | int | Gap rounded to the nearest 50 points, capped at ±600 (bucket 0 = [−25, 25)) |
| `expected_score` | float | Elo expected score of White, 1 / (1 + 10^(−gap/400)) |
| `opening_family` | string | Text of `Opening` before `:` (`Unknown` when missing) |
| `opening_variation` | string | Text after `:` (null for a family root) |
| `opening_in_reference` | bool | The name exists in `lichess-org/chess-openings` |
| `tc_base`, `tc_increment`, `tc_estimated`, `tc_category` | int, int, int, string | Base and increment (s), estimated duration base + 40 × increment, Lichess category |
| `white_score` | float | 1 (White win), 0.5 (draw), 0 (Black win) |
| `winner` | string | `white`, `black`, `draw` |
| `lost_on_time`, `time_loser` | bool, string | Decisive game ended by `Time forfeit`, and which side flagged |
| `has_clock` | bool | One clock comment per ply |
| `white_time_used_10_s`, `black_time_used_10_s` | float | Seconds used over the first 10 moves: clk₁ + 9 × increment − clk₁₀ (increment ignored after berserk), floored at 0 |
| `white_time_used_10`, `black_time_used_10` | float | Same, as a share of the base time (of the halved base after berserk), capped at 1; null if base = 0 |
| `white_berserk`, `black_berserk` | bool | Start clock below 75 % of the base (tournament berserk) |

## 3. Star schema — `data/eloscope.duckdb`

Built by `sql/01_schema.sql`; views in `sql/02_views.sql`.

### `fact_games` (one row per game)

| Column | Description |
|---|---|
| `game_id` | Lichess game id (not exported to Power BI) |
| `date_key` → `dim_date` | YYYYMMDD |
| `hour` | UTC hour |
| `white_hash`, `black_hash` | Hashed players (not exported to Power BI) |
| `white_elo`, `black_elo`, `avg_elo`, `rating_gap`, `rating_gap_bucket`, `expected_score` | See above |
| `opening_key` → `dim_opening`, `time_control_key` → `dim_time_control`, `elo_band_key` → `dim_elo_band` | Foreign keys |
| `white_score`, `winner`, `termination`, `lost_on_time`, `time_loser`, `plies`, `has_clock`, `has_eval` | See above |
| `white_time_used_10`, `black_time_used_10` | Share of the base time used in the first 10 moves |
| `white_time_used_10_s`, `black_time_used_10_s`, `white_clk_10`, `black_clk_10` | Same in seconds, and clock left after move 10 |

### Dimensions

| Table | Grain | Columns |
|---|---|---|
| `dim_date` | one calendar day | `date_key`, `date`, `year`, `month`, `day`, `weekday_num` (1 = lundi), `weekday_name`, `weekday_short`, `is_weekend` |
| `dim_opening` | one (ECO, full name) | `opening_key`, `eco`, `family`, `full_name`, `variation`, `in_reference` |
| `dim_time_control` | one `base+increment` | `time_control_key`, `time_control`, `category`, `category_label` (French), `category_order`, `base_seconds`, `increment_seconds`, `estimated_seconds` |
| `dim_elo_band` | one band | `elo_band_key`, `elo_band`, `elo_min`, `elo_max`, `sort_order` |

### Views

| View | Description |
|---|---|
| `v_games` | `fact_games` joined with all dimensions, plus 0/1 flags `white_win`, `draw`, `black_win` |
| `v_player_games` | Two rows per game (one per colour) with `score`, `expected`, `win`, `draw`, `loss`, `lost_on_time`, `time_used_10`, `player_gap` from the player's point of view |

## 4. Gold files for Power BI — `data/gold/*.csv`

UTF-8, comma separator, `.` decimal separator, ISO dates (`YYYY-MM-DD`), booleans as 0/1.
`manifest.json` lists row counts and sizes. Files above 50 MB (only `fact_games.csv`) are
git-ignored and rebuilt by `python run.py model export`.

| File | Grain | Notes |
|---|---|---|
| `dim_*.csv` | as above | |
| `fact_games.csv` | one game | `game_key` surrogate key; no game id, no player hash |
| `agg_opening_band_tc.csv` | opening × Elo band × time control × colour (`Blancs` / `Noirs`) | `games`, `wins`, `draws`, `losses`, `points`, `expected_points`, `lost_on_time` from the point of view of `color` |
| `agg_time_used_band_tc.csv` | Elo band × time control × colour × 5-point bin of clock share used in 10 moves | `player_games`, `points`, `losses`, `lost_on_time` |
