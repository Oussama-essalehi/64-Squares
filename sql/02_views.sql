-- =====================================================================================
-- 64 Squares / EloScope - analytical views
-- =====================================================================================

-- -------------------------------------------------------------------------------------
-- v_games: the fact table with every dimension attribute (one row per game)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_games AS
SELECT
    f.*,
    d.date,
    d.weekday_num,
    d.weekday_name,
    d.weekday_short,
    d.is_weekend,
    o.eco,
    o.family          AS opening_family,
    o.full_name       AS opening_name,
    t.time_control,
    t.category        AS tc_category,
    t.category_label  AS tc_label,
    t.category_order  AS tc_order,
    t.base_seconds,
    t.increment_seconds,
    b.elo_band,
    b.sort_order      AS elo_band_order,
    (f.winner = 'white')::INTEGER AS white_win,
    (f.winner = 'draw')::INTEGER  AS draw,
    (f.winner = 'black')::INTEGER AS black_win
FROM fact_games f
JOIN dim_date         d USING (date_key)
JOIN dim_opening      o USING (opening_key)
JOIN dim_time_control t USING (time_control_key)
JOIN dim_elo_band     b USING (elo_band_key);

-- -------------------------------------------------------------------------------------
-- v_player_games: two rows per game, one from each player's point of view.
-- Used for colour-neutral questions (time management, opening choice per colour).
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_player_games AS
SELECT
    game_id, 'white' AS color, elo_band, elo_band_order, tc_category, tc_label, tc_order,
    opening_family, opening_name, hour, weekday_num,
    white_elo AS player_elo, black_elo AS opponent_elo, rating_gap AS player_gap,
    white_score AS score,
    expected_score AS expected,
    (winner = 'white')::INTEGER AS win,
    (winner = 'draw')::INTEGER AS draw,
    (winner = 'black')::INTEGER AS loss,
    COALESCE(time_loser = 'white', FALSE)::INTEGER AS lost_on_time,  -- time_loser is NULL if nobody flagged
    white_time_used_10 AS time_used_10,
    black_time_used_10 AS opponent_time_used_10
FROM v_games
UNION ALL
SELECT
    game_id, 'black' AS color, elo_band, elo_band_order, tc_category, tc_label, tc_order,
    opening_family, opening_name, hour, weekday_num,
    black_elo, white_elo, -rating_gap,
    1 - white_score,
    1 - expected_score,
    (winner = 'black')::INTEGER,
    (winner = 'draw')::INTEGER,
    (winner = 'white')::INTEGER,
    COALESCE(time_loser = 'black', FALSE)::INTEGER,
    black_time_used_10,
    white_time_used_10
FROM v_games;
