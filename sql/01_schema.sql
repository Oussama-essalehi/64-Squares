-- =====================================================================================
-- 64 Squares / EloScope - star schema (DuckDB)
--
-- Input (registered by src/eloscope/model.py):
--   stg_games      clean games read from data/processed/games_clean.parquet
--   cfg_elo_bands  Elo bands from config.yaml (label, lower bound, upper bound, order)
--
-- Output: one fact table (one row per game) and four dimensions.
--   fact_games  -> dim_date (date_key), dim_opening (opening_key),
--                  dim_time_control (time_control_key), dim_elo_band (elo_band_key)
-- =====================================================================================

-- -------------------------------------------------------------------------------------
-- dim_elo_band: average rating of both players, 4 bands
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE dim_elo_band AS
SELECT
    band_order                         AS elo_band_key,
    label                              AS elo_band,
    lower_bound                        AS elo_min,
    upper_bound - 1                    AS elo_max,
    band_order                         AS sort_order
FROM cfg_elo_bands
ORDER BY band_order;

-- -------------------------------------------------------------------------------------
-- dim_time_control: one row per "base+increment" value, with its Lichess category
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE dim_time_control AS
WITH tc AS (
    SELECT DISTINCT time_control, tc_base, tc_increment, tc_estimated, tc_category
    FROM stg_games
)
SELECT
    ROW_NUMBER() OVER (ORDER BY tc_estimated, tc_base, tc_increment)::INTEGER AS time_control_key,
    time_control,
    tc_category                                                             AS category,
    CASE tc_category
        WHEN 'ultrabullet' THEN 'UltraBullet'
        WHEN 'bullet'      THEN 'Bullet'
        WHEN 'blitz'       THEN 'Blitz'
        WHEN 'rapid'       THEN 'Rapide'
        WHEN 'classical'   THEN 'Classique'
    END                                                                     AS category_label,
    CASE tc_category
        WHEN 'ultrabullet' THEN 1 WHEN 'bullet' THEN 2 WHEN 'blitz' THEN 3
        WHEN 'rapid' THEN 4 WHEN 'classical' THEN 5
    END                                                                     AS category_order,
    tc_base                                                                 AS base_seconds,
    tc_increment                                                            AS increment_seconds,
    tc_estimated                                                            AS estimated_seconds
FROM tc;

-- -------------------------------------------------------------------------------------
-- dim_opening: one row per (ECO, full opening name); family = text before ':'
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE dim_opening AS
WITH o AS (
    SELECT
        eco,
        opening                    AS full_name,
        ANY_VALUE(opening_family)  AS family,
        ANY_VALUE(opening_variation) AS variation,
        BOOL_OR(opening_in_reference) AS in_reference
    FROM stg_games
    GROUP BY eco, opening
)
SELECT
    ROW_NUMBER() OVER (ORDER BY eco, full_name)::INTEGER AS opening_key,
    eco,
    family,
    full_name,
    variation,
    in_reference
FROM o;

-- -------------------------------------------------------------------------------------
-- dim_date: every calendar day of the analysed period
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE dim_date AS
WITH bounds AS (SELECT MIN(date) AS d0, MAX(date) AS d1 FROM stg_games),
days AS (
    SELECT CAST(d AS DATE) AS date
    FROM bounds, generate_series(bounds.d0, bounds.d1, INTERVAL 1 DAY) AS g(d)
)
SELECT
    CAST(strftime(date, '%Y%m%d') AS INTEGER)             AS date_key,
    date,
    year(date)                                            AS year,
    month(date)                                           AS month,
    day(date)                                             AS day,
    isodow(date)                                          AS weekday_num,      -- 1 = lundi
    ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'][isodow(date)] AS weekday_name,
    ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'][isodow(date)]                         AS weekday_short,
    isodow(date) >= 6                                     AS is_weekend
FROM days;

-- -------------------------------------------------------------------------------------
-- fact_games: one row per clean game
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE fact_games AS
SELECT
    g.game_id,
    CAST(strftime(g.date, '%Y%m%d') AS INTEGER)  AS date_key,
    g.hour::TINYINT                              AS hour,
    g.white_hash,
    g.black_hash,
    g.white_elo::SMALLINT                        AS white_elo,
    g.black_elo::SMALLINT                        AS black_elo,
    g.avg_elo,
    g.rating_gap::SMALLINT                       AS rating_gap,
    g.rating_gap_bucket::SMALLINT                AS rating_gap_bucket,
    g.expected_score,
    o.opening_key,
    t.time_control_key,
    b.elo_band_key,
    g.white_score,
    g.winner,
    g.termination,
    g.lost_on_time,
    g.time_loser,
    g.plies::SMALLINT                            AS plies,
    g.has_clock,
    g.has_eval,
    g.white_time_used_10,
    g.black_time_used_10,
    g.white_time_used_10_s,
    g.black_time_used_10_s,
    g.white_clk_10,
    g.black_clk_10
FROM stg_games g
JOIN dim_opening      o ON o.eco = g.eco AND o.full_name = g.opening
JOIN dim_time_control t ON t.time_control = g.time_control
JOIN dim_elo_band     b ON b.elo_band = g.elo_band;
