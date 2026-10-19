-- =====================================================================================
-- 64 Squares / EloScope - analysis queries (DuckDB)
--
-- Each query starts with "-- name: <id>" (used by src/eloscope/analyze.py to run it) and a
-- comment stating the business question it answers.
-- Variables set before running:
--   min_games     minimum number of games for any rate to be shown (config: 1000)
--   top_openings  number of opening families listed per Elo band (config: 10)
-- =====================================================================================


-- name: q0_overview
-- Context: how many games, by time control and Elo band (with subtotals)?
SELECT
    COALESCE(tc_label, 'Total')   AS time_control,
    COALESCE(elo_band, 'Total')   AS elo_band,
    COUNT(*)                      AS games,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) FILTER (WHERE GROUPING(tc_label, elo_band) = 0) OVER (), 2) AS pct_of_games,
    ROUND(AVG(white_score), 4)    AS white_score,
    GROUPING(tc_label, elo_band)  AS grouping_level
FROM v_games
GROUP BY GROUPING SETS ((tc_label, tc_order, elo_band, elo_band_order), (tc_label, tc_order), (elo_band, elo_band_order), ())
ORDER BY grouping_level, MIN(tc_order), MIN(elo_band_order);


-- name: q1_top_openings_by_band
-- Q1. Which opening families are played most at each Elo band, and how do they score?
--     Popularity rank, share of the band's games, running (cumulative) share and
--     win / draw / loss rates. Families below the minimum sample size are not ranked.
WITH band_totals AS (
    SELECT elo_band, COUNT(*) AS band_games FROM v_games GROUP BY elo_band
),
by_family AS (
    SELECT
        elo_band,
        elo_band_order,
        opening_family,
        COUNT(*)                               AS games,
        AVG(white_win)                         AS white_win_rate,
        AVG(draw)                              AS draw_rate,
        AVG(black_win)                         AS black_win_rate,
        AVG(white_score)                       AS white_score,
        AVG(white_score - expected_score)      AS white_score_vs_expected
    FROM v_games
    GROUP BY elo_band, elo_band_order, opening_family
    HAVING COUNT(*) >= getvariable('min_games')
),
ranked AS (
    SELECT
        f.*,
        f.games / t.band_games                                                     AS share_of_band,
        RANK() OVER (PARTITION BY f.elo_band ORDER BY f.games DESC)                AS popularity_rank,
        SUM(f.games) OVER (PARTITION BY f.elo_band ORDER BY f.games DESC
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            / t.band_games                                                         AS cumulative_share
    FROM by_family f
    JOIN band_totals t USING (elo_band)
)
SELECT
    elo_band, popularity_rank, opening_family, games,
    ROUND(share_of_band, 4)          AS share_of_band,
    ROUND(cumulative_share, 4)       AS cumulative_share,
    ROUND(white_win_rate, 4)         AS white_win_rate,
    ROUND(draw_rate, 4)              AS draw_rate,
    ROUND(black_win_rate, 4)         AS black_win_rate,
    ROUND(white_score, 4)            AS white_score,
    ROUND(white_score_vs_expected, 4) AS white_score_vs_expected
FROM ranked
WHERE popularity_rank <= getvariable('top_openings')
ORDER BY elo_band_order, popularity_rank;


-- name: q1_repertoire_shift
-- Q1. Does the repertoire change with level? Popularity rank of the most played families
--     in each band, side by side (NULL = below the minimum sample size in that band).
WITH counts AS (
    SELECT
        opening_family,
        elo_band,
        COUNT(*)                                                   AS games,
        COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY elo_band)      AS share   -- share of all band games
    FROM v_games
    GROUP BY opening_family, elo_band
),
ranks AS (
    SELECT *, RANK() OVER (PARTITION BY elo_band ORDER BY games DESC) AS rnk
    FROM counts
    WHERE games >= getvariable('min_games')
),
top_overall AS (
    SELECT opening_family FROM ranks GROUP BY opening_family HAVING MIN(rnk) <= getvariable('top_openings')
)
SELECT
    opening_family,
    MAX(CASE WHEN elo_band = '< 1200'    THEN rnk END)               AS rank_lt_1200,
    MAX(CASE WHEN elo_band = '1200-1599' THEN rnk END)               AS rank_1200_1599,
    MAX(CASE WHEN elo_band = '1600-1999' THEN rnk END)               AS rank_1600_1999,
    MAX(CASE WHEN elo_band = '2000+'     THEN rnk END)               AS rank_2000_plus,
    ROUND(MAX(CASE WHEN elo_band = '< 1200' THEN share END), 4)      AS share_lt_1200,
    ROUND(MAX(CASE WHEN elo_band = '2000+'  THEN share END), 4)      AS share_2000_plus
FROM ranks
WHERE opening_family IN (SELECT opening_family FROM top_overall)
GROUP BY opening_family
ORDER BY COALESCE(rank_lt_1200, 999), opening_family;


-- name: q1_family_subtotals
-- Q1. Result split per opening family with band subtotals and a grand total (GROUPING SETS).
SELECT
    COALESCE(elo_band, 'Toutes')          AS elo_band,
    COALESCE(opening_family, 'Toutes')    AS opening_family,
    COUNT(*)                              AS games,
    ROUND(AVG(white_win), 4)              AS white_win_rate,
    ROUND(AVG(draw), 4)                   AS draw_rate,
    ROUND(AVG(black_win), 4)              AS black_win_rate,
    GROUPING(elo_band, opening_family)    AS grouping_level
FROM v_games
GROUP BY GROUPING SETS ((elo_band, opening_family), (elo_band), ())
HAVING COUNT(*) >= getvariable('min_games')
ORDER BY grouping_level DESC, elo_band, games DESC;


-- name: q2_white_advantage
-- Q2. White's advantage: White's score by Elo band and time control, with ROLLUP
--     subtotals. "white_edge" removes the rating gap effect (actual - Elo expected score).
SELECT
    COALESCE(elo_band, 'Toutes')        AS elo_band,
    COALESCE(tc_label, 'Toutes')        AS time_control,
    COUNT(*)                            AS games,
    ROUND(AVG(white_win), 4)            AS white_win_rate,
    ROUND(AVG(draw), 4)                 AS draw_rate,
    ROUND(AVG(black_win), 4)            AS black_win_rate,
    ROUND(AVG(white_score), 4)          AS white_score,
    ROUND(AVG(expected_score), 4)       AS expected_score,
    ROUND(AVG(white_score - expected_score), 4) AS white_edge,
    GROUPING(elo_band, tc_label)        AS grouping_level
FROM v_games
GROUP BY ROLLUP ((elo_band, elo_band_order), (tc_label, tc_order))
HAVING COUNT(*) >= getvariable('min_games')
ORDER BY MIN(elo_band_order) NULLS LAST, MIN(tc_order) NULLS LAST;


-- name: q3_calibration
-- Q3. Rating vs reality: does the rating gap predict the result as the Elo formula says?
--     Expected score E = 1 / (1 + 10^(-gap/400)) vs actual White score, per gap bucket
--     (50 points, capped at +/-600) and time control.
SELECT
    tc_label                              AS time_control,
    tc_order,
    rating_gap_bucket,
    COUNT(*)                              AS games,
    ROUND(AVG(expected_score), 4)         AS expected_score,
    ROUND(AVG(white_score), 4)            AS actual_score,
    ROUND(AVG(white_score) - AVG(expected_score), 4) AS calibration_gap
FROM v_games
GROUP BY tc_label, tc_order, rating_gap_bucket
HAVING COUNT(*) >= getvariable('min_games')
ORDER BY tc_order, rating_gap_bucket;


-- name: q3_calibration_error
-- Q3. Mean absolute calibration error per time control (game-weighted over the buckets
--     that pass the minimum sample size), and the share of buckets where the favourite
--     under-performs the formula.
WITH buckets AS (
    SELECT
        tc_label, tc_order, rating_gap_bucket,
        COUNT(*)                                  AS games,
        AVG(white_score) - AVG(expected_score)    AS gap
    FROM v_games
    GROUP BY tc_label, tc_order, rating_gap_bucket
    HAVING COUNT(*) >= getvariable('min_games')
)
SELECT
    tc_label                                                  AS time_control,
    COUNT(*)                                                  AS buckets,
    SUM(games)                                                AS games,
    ROUND(SUM(ABS(gap) * games) / SUM(games), 4)              AS mean_abs_calibration_error,
    ROUND(MAX(ABS(gap)), 4)                                   AS max_abs_gap,
    ROUND(AVG(CASE WHEN rating_gap_bucket >= 200 THEN (gap < 0)::INTEGER END), 4)  AS share_buckets_200plus_below_formula
FROM buckets
GROUP BY tc_label, tc_order
ORDER BY tc_order;


-- name: q3_favourite_calibration
-- Q3. Colour-neutral view: score of the higher-rated player vs the Elo expectation, by
--     absolute gap bucket (removes White's first-move advantage from the comparison).
WITH fav AS (
    SELECT
        tc_label, tc_order,
        (50 * FLOOR(LEAST(player_gap, 600) / 50.0 + 0.5))::INTEGER AS gap_bucket,
        score, expected
    FROM v_player_games
    WHERE player_gap > 0
)
SELECT
    tc_label AS time_control, gap_bucket, COUNT(*) AS games,
    ROUND(AVG(expected), 4) AS expected_score,
    ROUND(AVG(score), 4)    AS actual_score,
    ROUND(AVG(score) - AVG(expected), 4) AS calibration_gap
FROM fav
GROUP BY tc_label, tc_order, gap_bucket
HAVING COUNT(*) >= getvariable('min_games')
ORDER BY tc_order, gap_bucket;


-- name: q4_time_losses
-- Q4. Time management: share of games lost on time by time control and Elo band
--     (ROLLUP subtotals), and that share among decisive games only.
SELECT
    COALESCE(tc_label, 'Toutes')                         AS time_control,
    COALESCE(elo_band, 'Toutes')                         AS elo_band,
    COUNT(*)                                             AS games,
    ROUND(AVG(lost_on_time::INTEGER), 4)                 AS lost_on_time_rate,
    ROUND(SUM(lost_on_time::INTEGER) / NULLIF(SUM((winner <> 'draw')::INTEGER), 0), 4) AS share_of_decisive_on_time,
    GROUPING(tc_label, elo_band)                         AS grouping_level
FROM v_games
GROUP BY ROLLUP ((tc_label, tc_order), (elo_band, elo_band_order))
HAVING COUNT(*) >= getvariable('min_games')
ORDER BY MIN(tc_order) NULLS LAST, MIN(elo_band_order) NULLS LAST;


-- name: q4_time_used_deciles
-- Q4. Do players who spend a larger share of their clock in the first 10 moves lose more?
--     Player-level rows (both colours), deciles of time used within each time control.
WITH p AS (
    SELECT
        tc_label, tc_order, score, win, loss, lost_on_time, player_gap, time_used_10,
        NTILE(10) OVER (PARTITION BY tc_label ORDER BY time_used_10) AS decile
    FROM v_player_games
    WHERE time_used_10 IS NOT NULL
)
SELECT
    tc_label                          AS time_control,
    decile,
    COUNT(*)                          AS player_games,
    ROUND(MIN(time_used_10), 4)       AS min_share_used,
    ROUND(MAX(time_used_10), 4)       AS max_share_used,
    ROUND(AVG(time_used_10), 4)       AS avg_share_used,
    ROUND(AVG(score), 4)              AS score,
    ROUND(AVG(loss), 4)               AS loss_rate,
    ROUND(AVG(lost_on_time), 4)       AS lost_on_time_rate,
    ROUND(AVG(player_gap), 1)         AS avg_rating_gap
FROM p
GROUP BY tc_label, tc_order, decile
HAVING COUNT(*) >= getvariable('min_games')
ORDER BY tc_order, decile;


-- name: q5_activity_heatmap
-- Q5. Activity patterns: number of games by weekday and hour (UTC), share of all games.
SELECT
    weekday_num, weekday_short AS weekday, hour,
    COUNT(*)                                          AS games,
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER (), 5)        AS share_of_games,
    ROUND(COUNT(*) / AVG(COUNT(*)) OVER (), 3)        AS index_vs_average
FROM v_games
GROUP BY weekday_num, weekday_short, hour
ORDER BY weekday_num, hour;


-- name: q5_results_by_hour
-- Q5. Do results or losses on time change with the hour (UTC)? Compared with the daily
--     average through window functions.
WITH h AS (
    SELECT
        hour,
        COUNT(*)                       AS games,
        AVG(white_score)               AS white_score,
        AVG(draw)                      AS draw_rate,
        AVG(lost_on_time::INTEGER)     AS lost_on_time_rate,
        AVG(avg_elo)                   AS avg_elo,
        AVG((tc_category IN ('bullet', 'ultrabullet'))::INTEGER) AS bullet_share
    FROM v_games
    GROUP BY hour
    HAVING COUNT(*) >= getvariable('min_games')
)
SELECT
    hour, games,
    ROUND(white_score, 4)                                              AS white_score,
    ROUND(draw_rate, 4)                                                AS draw_rate,
    ROUND(lost_on_time_rate, 4)                                        AS lost_on_time_rate,
    ROUND(lost_on_time_rate - SUM(lost_on_time_rate * games) OVER () / SUM(games) OVER (), 4) AS lost_on_time_vs_avg,
    ROUND(avg_elo, 0)                                                  AS avg_elo,
    ROUND(bullet_share, 4)                                             AS bullet_share
FROM h
ORDER BY hour;


-- name: q5_night_vs_day
-- Q5. Late-night play (00h-05h UTC) vs the rest of the day, within each time control so
--     that the time-control mix does not drive the comparison.
SELECT
    tc_label                                                AS time_control,
    CASE WHEN hour BETWEEN 0 AND 5 THEN 'Nuit (0h-5h)'
         WHEN hour BETWEEN 6 AND 11 THEN 'Matin (6h-11h)'
         WHEN hour BETWEEN 12 AND 17 THEN 'Après-midi (12h-17h)'
         ELSE 'Soir (18h-23h)' END                          AS period,
    COUNT(*)                                                AS games,
    ROUND(AVG(white_score), 4)                              AS white_score,
    ROUND(AVG(draw), 4)                                     AS draw_rate,
    ROUND(AVG(lost_on_time::INTEGER), 4)                    AS lost_on_time_rate,
    ROUND(AVG(avg_elo), 0)                                  AS avg_elo
FROM v_games
GROUP BY tc_label, tc_order, period
HAVING COUNT(*) >= getvariable('min_games')
ORDER BY tc_order, MIN(hour);


-- name: q6_best_openings_per_band
-- Q6. Recommendations: among the most played families of each band, which ones give
--     the best score to the side that plays them (White or Black)? Ranked by score above
--     the Elo expectation so that rating differences do not bias the ranking.
WITH stats AS (
    SELECT
        elo_band, elo_band_order, color, opening_family,
        COUNT(*)                     AS games,
        AVG(score)                   AS score,
        AVG(score - expected)        AS score_vs_expected,
        AVG(win)                     AS win_rate
    FROM v_player_games
    GROUP BY elo_band, elo_band_order, color, opening_family
    HAVING COUNT(*) >= getvariable('min_games')
),
popular AS (
    SELECT *, RANK() OVER (PARTITION BY elo_band, color ORDER BY games DESC) AS popularity_rank
    FROM stats
),
best AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY elo_band, color ORDER BY score_vs_expected DESC) AS rn
    FROM popular
    WHERE popularity_rank <= 2 * getvariable('top_openings')
)
SELECT
    elo_band, color, rn AS recommendation_rank, opening_family, games, popularity_rank,
    ROUND(score, 4)               AS score,
    ROUND(score_vs_expected, 4)   AS score_vs_expected,
    ROUND(win_rate, 4)            AS win_rate
FROM best
WHERE rn <= 3
ORDER BY elo_band_order, color DESC, rn;


-- name: qc_white_score_by_band
-- Cross-check with Python: White's average score per Elo band.
SELECT elo_band, COUNT(*) AS games, ROUND(AVG(white_score), 6) AS white_score
FROM v_games
GROUP BY elo_band, elo_band_order
ORDER BY elo_band_order;
