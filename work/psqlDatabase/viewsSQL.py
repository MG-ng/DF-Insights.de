from typing import Literal

from Helper import FilterTranslations, TABLE_NAME_SMARD, FILTER, WIND_SOLAR_SHARE_ID, RE_SHARE_ID, ELEC_IMPORT_ID, \
	ELEC_PRICE_CHANGE_ABS_ID, ELEC_PRICE_CHANGE_REL_ID, VIEW_NAME_RE_SHARE_EXT_TRADE, TABLE_NAME_OPEN_METEO, \
	VIEW_NAME_HISTORICAL_WEATHER_AGG, TABLE_NAME_FORECASTS, WIND_SOLAR_ID, FLAG

# Share of the renewable load as a test for the postgresql view
## Calculating a virtual percentage/max_share line of (wind+solar) on total demand if resLoad + gridLoad are available
# TODO: Fix not forecasted electricity import
re_share_import_view_sql = f"""
        SELECT  t.unix_timestamp_ms, t.region, t.resolution, 
        	( t.electricity_production_photovoltaics 
        		+ t.electricity_production_wind_onshore 
        		+ t.electricity_production_wind_offshore 
        	)::DECIMAL(12, 2) AS {FilterTranslations[FILTER.inverse[WIND_SOLAR_ID]]}, 
            
            1- ((t.power_consumption_residual_load) / t.power_consumption_total)::DECIMAL(6, 5) 
            AS {FilterTranslations[FILTER.inverse[WIND_SOLAR_SHARE_ID]]}, 
            
            1- ((t.power_consumption_residual_load 
            - t.electricity_production_hydropower 
            - t.electricity_production_other_renewables 
            - t.electricity_production_biomass 
            - t.electricity_production_pumped_storage
            + t.electricity_consumption_pumped_storage) 
             / t.power_consumption_total)::DECIMAL(6, 5) 
            AS {FilterTranslations[FILTER.inverse[RE_SHARE_ID]]}, 
            -- "Nur der importierte Strom stammt aus eigenen Berechnungen und entspricht der Differenz von Neztlast und Erzeugung." ~ SMC
            (t.power_consumption_total - t.total_production)::DECIMAL(12, 2) 
            AS {FilterTranslations[FILTER.inverse[ELEC_IMPORT_ID]]}
        FROM ( 
            SELECT *, ( 
                electricity_production_lignite 
                + electricity_production_nuclear_energy 
                + electricity_production_wind_offshore 
                + electricity_production_hydropower 
                + electricity_production_other_conventional 
                + electricity_production_other_renewables 
                + electricity_production_biomass 
                + electricity_production_wind_onshore 
                + electricity_production_photovoltaics 
                + electricity_production_hard_coal 
                + electricity_production_pumped_storage 
                - electricity_consumption_pumped_storage
                + electricity_production_natural_gas
            )::DECIMAL(12, 2) AS total_production 
            FROM {TABLE_NAME_SMARD} d
            ORDER BY unix_timestamp_ms ASC 
             ) t
        WHERE t.power_consumption_residual_load is not null 
                and t.power_consumption_total is not null 
                and t.power_consumption_total != 0 
                AND t.electricity_production_photovoltaics <> {FLAG} 
                AND t.electricity_production_wind_onshore <> {FLAG} 
                AND t.electricity_production_wind_offshore <> {FLAG} 
                -- NULL is automatically filtered out by these comparisons
        """


# correctly traceable
price_change_view_sql = f"""
WITH ger_lux_prices AS (SELECT unix_timestamp_ms,
                               region,
                               resolution,
                               market_price_ger_lux AS current_price,
                               LAG(market_price_ger_lux, 1) OVER (
                                   PARTITION BY region, resolution
                                   ORDER BY unix_timestamp_ms ASC
                                   )                as last_price,
                               LAG(unix_timestamp_ms, 1) OVER (
                                   PARTITION BY region, resolution
                                   ORDER BY unix_timestamp_ms ASC
                                   )                as last_time
                        FROM {TABLE_NAME_SMARD})
SELECT unix_timestamp_ms,
       region,
       resolution,
       current_price,
       last_time,
       last_price,
       (current_price - last_price)::DECIMAL(7, 3)       as {FilterTranslations[FILTER.inverse[ELEC_PRICE_CHANGE_ABS_ID]]},
       ((current_price / last_price) - 1.0)::DECIMAL(7, 3) as {FilterTranslations[FILTER.inverse[ELEC_PRICE_CHANGE_REL_ID]]}
FROM ger_lux_prices tmp
WHERE current_price IS NOT NULL
  AND last_price IS NOT NULL
  AND last_price != 0
  AND CASE resolution
          WHEN 'quarterhour' THEN unix_timestamp_ms - last_time = 1000 * 60 * 15 -- 15 min in milliseconds
          WHEN 'hour' THEN unix_timestamp_ms - last_time = 1000 * 60 * 15 * 4
          WHEN 'day' THEN unix_timestamp_ms - last_time = 1000 * 60 * 15 * 4 * 24
          WHEN 'week' THEN unix_timestamp_ms - last_time = 1000 * 60 * 15 * 4 * 24 * 7
          ELSE FALSE
    END
ORDER BY region, unix_timestamp_ms
"""


# Filter quicker dunkelflauten via WHERE duration> on view
# TODO: Add only solar and wind production?
# TODO: Add peak price during Dunkelflaute?
preserve_highlighting = f""
def dunkelflauten_stats_view_sql( threshold=0.3 ):
        return f"""
WITH prices AS (
    SELECT sdc.unix_timestamp_ms, sdc.region, sdc.resolution, sdc.market_price_ger_lux AS ger_lux,
           sdc.power_consumption_residual_load AS res_load, sdc.power_consumption_total,
           CASE WHEN sdc.resolution='quarterhour' THEN sdc.power_consumption_residual_load * 4
               ELSE sdc.power_consumption_residual_load END AS res_load_power
        FROM {TABLE_NAME_SMARD} sdc
        WHERE sdc.resolution = 'quarterhour'
          AND sdc.region = 'DE'
          AND sdc.market_price_ger_lux IS NOT NULL -- Prices are null up to 1.10.2018
    -- Without throwing out NULL rows: 25 seconds with t.resolution='day'
    -- With IS NOT NULL: 12 seconds
),
     share_categories AS (
        SELECT t.unix_timestamp_ms, t.region, t.resolution, t.share_of_renewable_energies_computed,
        CASE
        WHEN t.share_of_renewable_energies_computed <= {threshold} THEN 'LOW'
        ELSE 'HIGH' END AS current_share
        FROM {VIEW_NAME_RE_SHARE_EXT_TRADE} t
        WHERE t.region = 'DE'
        AND t.resolution = 'quarterhour'
        AND t.unix_timestamp_ms > 1538344800000 -- only dunkelflauten after Monday, 1. October 2018 00:00:00 GMT+2
         -- 7 rows (32 s) versus 28 rows with null (1m27s) @0.22 threshold
    ), events AS (
        SELECT s.unix_timestamp_ms, s.region, s.resolution,
           (CASE /* Guaranteed that a START is at the beginning of a period but not that an END is at the finish */
                WHEN (LAG(current_share, 1, 'HIGH') OVER w = 'HIGH' AND current_share = 'LOW') THEN 'START'
                WHEN (LAG(current_share, 1, 'HIGH') OVER w = 'LOW' AND current_share = 'HIGH') THEN 'END'
                ELSE 'nothing' END) AS event_bucket
        FROM share_categories s
        WINDOW w AS ( ORDER BY s.unix_timestamp_ms ASC )),
     cleaned AS (
            SELECT *
                FROM events
                WHERE event_bucket != 'nothing'),
     start_end AS (
        SELECT *,
           LEAD(c.unix_timestamp_ms, 1, ( SELECT max(latest.unix_timestamp_ms) FROM cleaned latest ))
           OVER (ORDER BY c.unix_timestamp_ms ASC
           ) AS end_time
        FROM cleaned c),
     matches AS (
        SELECT *, se.unix_timestamp_ms AS start_time, se.end_time - se.unix_timestamp_ms AS duration
        FROM start_end se
        WHERE se.end_time - se.unix_timestamp_ms >= 1000 * 60 * 60 * 24 * 1::BIGINT
          AND se.event_bucket = 'START'),
     dunkelflauten AS ( -- 1 sec for this table
        SELECT start_time, end_time, duration
        FROM matches
    ), res_load AS ( -- 17 seconds for this table
        SELECT pd.*,
            (
               SELECT round( SUM(p.res_load) / (pd.duration/(1000*60*60::BIGINT)), 2)  -- MW
                   FROM prices p
                   WHERE p.unix_timestamp_ms BETWEEN pd.start_time AND pd.end_time) AS avg_res_load_power_during_df,
           (
               SELECT SUM(p.res_load)
                   FROM prices p
                   WHERE p.unix_timestamp_ms
                   BETWEEN pd.start_time - 1000 *60 *60 *24 *7::BIGINT AND pd.start_time) AS res_load_week_before,  -- MWh
           (
               SELECT SUM(p.res_load)
                   FROM prices p
                   WHERE p.unix_timestamp_ms
                   BETWEEN pd.end_time AND pd.end_time + 1000 *60 *60 *24 *7::BIGINT) AS res_load_week_after,  -- MWh
           (
               SELECT CASE WHEN p.resolution='quarterhour'
                            THEN peak * 4 ELSE peak * 1 END  -- MWh in MW conversion
                   FROM (SELECT resolution, MAX(res_load) as peak
                            FROM prices
                            WHERE unix_timestamp_ms
                                BETWEEN pd.start_time AND pd.end_time
                            GROUP BY resolution
                             ) p
                   ) AS peak_res_load_power_during_df,
           (
               SELECT SUM(p.power_consumption_total)
                   FROM prices p
                   WHERE p.unix_timestamp_ms
                   BETWEEN pd.start_time AND pd.end_time) AS electric_energy_consumption_during_df
                FROM dunkelflauten pd

        ), dunkelflauten_prices AS ( --38 secs for this table
            SELECT rl.*,
                round( (rl.res_load_week_before + rl.res_load_week_after) / (2 *7*24), 2) AS avg_res_load_power_before_after,
                (
                    SELECT round( SUM(p.power_consumption_total * p.ger_lux) / SUM(p.power_consumption_total), 2)
                       FROM prices p
                       WHERE p.unix_timestamp_ms
                       BETWEEN rl.start_time AND rl.end_time) AS avg_weighted_price_during_df,
                (
                    SELECT SUM(p.power_consumption_total * p.ger_lux) / SUM(p.power_consumption_total)
                       FROM prices p
                       WHERE p.unix_timestamp_ms
                       BETWEEN rl.start_time - 1000 *60 *60 *24 *7::BIGINT AND rl.start_time) AS avg_weighted_price_week_before_df,
                (
                    SELECT SUM(p.power_consumption_total * p.ger_lux) / SUM(p.power_consumption_total)
                       FROM prices p
                       WHERE p.unix_timestamp_ms
                       BETWEEN rl.end_time AND rl.end_time + 1000 *60 *60 *24 *7::BIGINT) AS avg_weighted_price_week_after_df,
                (
                    SELECT AVG(during_df.ger_lux)
                        FROM prices during_df
                        WHERE during_df.unix_timestamp_ms
                        BETWEEN rl.start_time AND rl.end_time -- <=> value >= low AND value <= high
                )::DECIMAL(6, 2) AS avg_price_during_dunkelflaute,
                (
                    SELECT AVG(week_before_df.ger_lux)
                       FROM prices week_before_df
                       WHERE week_before_df.unix_timestamp_ms
                                 BETWEEN rl.start_time - 1000 * 60 * 60 * 24 * 7::BIGINT AND rl.start_time -- <=> value >= low AND value <= high
                )::DECIMAL(6, 2) AS avg_price_week_before_dunkelflaute,
                (
                   SELECT AVG(week_after_df.ger_lux)
                       FROM prices week_after_df
                       WHERE week_after_df.unix_timestamp_ms
                                 -- 1 or 7 days because in between those it takes the other more expensive Dunkelflauten periods into account too
                                 BETWEEN rl.end_time AND rl.end_time + 1000 * 60 * 60 * 24 * 7::BIGINT
                )::DECIMAL(6, 2)  AS avg_price_week_after_dunkelflaute
            FROM res_load rl

        ), price_delta AS ( --1 min 3 s for this table
            SELECT dp.*,
                (
                   SELECT SUM((during_df.res_load - (dp.avg_res_load_power_before_after/4)))  -- assuming quarterhour resolution for res_load energy! 
                       FROM prices during_df
                       WHERE during_df.unix_timestamp_ms
                           BETWEEN dp.start_time AND dp.end_time
                               AND (during_df.res_load - (dp.avg_res_load_power_before_after/4)) > 0
                )::DECIMAL(15, 2)  AS extent,
                (
                   SELECT SUM((during_df.res_load - (dp.avg_res_load_power_before_after/4)) * during_df.ger_lux) -- assuming quarterhour resolution! 
                       FROM prices during_df
                       WHERE during_df.unix_timestamp_ms
                           BETWEEN dp.start_time AND dp.end_time
                               AND (during_df.res_load - (dp.avg_res_load_power_before_after/4)) > 0
                )::DECIMAL(15, 2)  AS storage_made_electricity_value,
               dp.avg_price_during_dunkelflaute
                   - (dp.avg_price_week_before_dunkelflaute + dp.avg_price_week_after_dunkelflaute) / 2
                   ::DECIMAL(7, 3) AS price_increase_during_df,
               round(((dp.avg_price_during_dunkelflaute
                   / ((dp.avg_price_week_before_dunkelflaute + dp.avg_price_week_after_dunkelflaute) / 2))
                   -1)*100)
                   ::DECIMAL(7, 3) AS relative_price_increase_during_df,
               round(dp.avg_weighted_price_during_df
                   - (dp.avg_weighted_price_week_before_df + dp.avg_weighted_price_week_after_df) / 2, 2)
                   AS price_increase_during_df_weighted,
               round(((dp.avg_weighted_price_during_df
                   / ((dp.avg_weighted_price_week_before_df + dp.avg_weighted_price_week_after_df) / 2))
                   -1)*100)
                   ::DECIMAL(7, 3) AS relative_price_increase_during_df_weighted,
               dp.avg_weighted_price_during_df
                   > LEAST(dp.avg_weighted_price_week_before_df, dp.avg_weighted_price_week_after_df)
                   AND dp.avg_weighted_price_during_df
                           < GREATEST(dp.avg_weighted_price_week_before_df, dp.avg_weighted_price_week_after_df)
                   AS dp_in_before_after_range
            FROM dunkelflauten_prices dp

        ) SELECT *,
                 round(electric_energy_consumption_during_df * price_increase_during_df, 2) ::DECIMAL(14, 2) AS dunkelflauten_cost,
                 round(electric_energy_consumption_during_df * price_increase_during_df_weighted, 2) ::DECIMAL(14, 2) AS dunkelflauten_cost_weighted,
                 extract(ISODOW FROM (to_timestamp((start_time + end_time) / 2 / 1000)
                    AT TIME ZONE 'Europe/Berlin')) AS day_of_week,
                 extract(DAY FROM (to_timestamp((start_time + end_time) / 2 / 1000)
                    AT TIME ZONE 'Europe/Berlin')) AS day_of_month,
                 extract(MONTH FROM (to_timestamp((start_time + end_time) / 2 / 1000)
                    AT TIME ZONE 'Europe/Berlin')) AS month,
                 extract(YEAR FROM (to_timestamp((start_time + end_time) / 2 / 1000)
                    AT TIME ZONE 'Europe/Berlin')) AS year,
                 duration as duration_ms,
                 (duration / (1000*60*60*24.0))::Decimal(5, 2) AS duration_days, 
                 (SELECT round(avg(weather.repi_power1avg), 2) FROM {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
                 	WHERE weather.date>to_timestamp(price_delta.start_time /1000) 
                 	AND weather.date<to_timestamp(price_delta.end_time /1000) AND resolution='hour')
                 	AS repi_power1avg,
                 (SELECT round(avg(weather.repi_power1avg2), 2) FROM {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
                 	WHERE weather.date>to_timestamp(price_delta.start_time /1000) 
                 	AND weather.date<to_timestamp(price_delta.end_time /1000) AND resolution='hour')
                 	AS repi_power1avg2,
                 (SELECT round(avg(weather.repi_power_exp), 2) FROM {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
                 	WHERE weather.date>to_timestamp(price_delta.start_time /1000) 
                 	AND weather.date<to_timestamp(price_delta.end_time /1000) AND resolution='hour')
                 	AS repi_power_exp_avg,
                 (SELECT round(max(weather.repi_power_exp), 2) FROM {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
                 	WHERE weather.date>to_timestamp(price_delta.start_time /1000) 
                 	AND weather.date<to_timestamp(price_delta.end_time /1000) AND resolution='hour')
                 	AS repi_power_exp_max,
                 (SELECT round(min(weather.repi_power_exp), 2) FROM {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
                 	WHERE weather.date>to_timestamp(price_delta.start_time /1000) 
                 	AND weather.date<to_timestamp(price_delta.end_time /1000) AND resolution='hour')
                 	AS repi_power_exp_min,
                (SELECT round(avg(weather.wind_speed_100_avg), 2) FROM {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
                 	WHERE weather.date>to_timestamp(price_delta.start_time /1000) 
                 	AND weather.date<to_timestamp(price_delta.end_time /1000) AND resolution='hour')
                 	AS wind_speed_100_avg,
                (SELECT round(avg(weather.diffuse_radiation_avg), 2) FROM {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
                 	WHERE weather.date>to_timestamp(price_delta.start_time /1000) 
                 	AND weather.date<to_timestamp(price_delta.end_time /1000) AND resolution='hour')
                 	AS diffuse_radiation_avg,
                (SELECT round(avg(weather.direct_radiation_avg), 2) FROM {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
                 	WHERE weather.date>to_timestamp(price_delta.start_time /1000) 
                 	AND weather.date<to_timestamp(price_delta.end_time /1000) AND resolution='hour')
                 	AS direct_radiation_avg
        FROM price_delta
"""


# Total: 4 rows, 3 columns as a grid over Germany
#     47.97890853881836,7.176079750061035
#     47.97890853881836,10.01661205291748
#     47.97890853881836,13.006645202636719
#     50.017574310302734,7.068062782287598
#     50.017574310302734,10.052355766296387
#     50.017574310302734,12.8795804977417
#     51.985939025878906,6.935780048370361
#     51.985939025878906,10.073394775390625
#     51.985939025878906,13.04587173461914
#     Only the 3 southern rows for radiation (PV Solar)
#
#     51.985939025878906,6.935780048370361
#     51.985939025878906,10.073394775390625
#     51.985939025878906,13.04587173461914
#     54.02460479736328,6.976743698120117
#     54.02460479736328,9.94186019897461
#     54.02460479736328,13.081395149230957
#     Only the 2 northern rows for wind
historical_weather_agg_view_sql = f""" -- # Unfortunately inserting into a view is not possible
WITH radiation AS (
    SELECT weather.date AS date,
           min(direct_radiation) AS direct_radiation_min,
           avg(direct_radiation)::DECIMAL(6, 3) AS direct_radiation_avg,
           max(direct_radiation) AS direct_radiation_max,
           min(diffuse_radiation) AS diffuse_radiation_min,
           avg(diffuse_radiation)::DECIMAL(6, 3) AS diffuse_radiation_avg,
           max(diffuse_radiation) AS diffuse_radiation_max,
           min(temperature_2m) AS temp2m_min,
           avg(temperature_2m)::DECIMAL(6, 3) AS temp2m_avg,
           max(temperature_2m) AS temp2m_max
    FROM {TABLE_NAME_OPEN_METEO} weather
    WHERE weather.lat < 52
    GROUP BY weather.date
), wind_dir_count AS ( -- count 12 locations by 8 weather direction
    SELECT COUNT(*) FILTER (WHERE 337.5 < wind_direction_100m AND wind_direction_100m <= 22.5) AS N,
           COUNT(*) FILTER (WHERE 22.5 < wind_direction_100m AND wind_direction_100m <= 67.5) AS NE,
           COUNT(*) FILTER (WHERE 67.5 < wind_direction_100m AND wind_direction_100m <= 112.5) AS E,
           COUNT(*) FILTER (WHERE 112.5 < wind_direction_100m AND wind_direction_100m <= 157.5) AS SE,
           COUNT(*) FILTER (WHERE 157.5 < wind_direction_100m AND wind_direction_100m <= 202.5) AS S,
           COUNT(*) FILTER (WHERE 202.5 < wind_direction_100m AND wind_direction_100m <= 247.5) AS SW,
           COUNT(*) FILTER (WHERE 247.5 < wind_direction_100m AND wind_direction_100m <= 292.5) AS W,
           COUNT(*) FILTER (WHERE 292.5 < wind_direction_100m AND wind_direction_100m <= 337.5) AS NW,
           weather.date AS date
        FROM {TABLE_NAME_OPEN_METEO} weather
        GROUP BY weather.date
), wind_dir AS (
    SELECT date, CASE
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = n THEN 'north'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = ne THEN 'north_east'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = e THEN 'east'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = se THEN 'south_east'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = s THEN 'south'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = sw THEN 'south_west'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = w THEN 'west'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = nw THEN 'north_west'
        ELSE 'unknown' END AS wind_direction,
        round(
        	GREATEST(n, ne, e, se, s, sw, w, nw) /12.0
        	, 2
        )::DECIMAL(3, 2) AS wind_dir_uniformity
    FROM wind_dir_count
), wind AS (
    SELECT weather.date AS date,
           min(wind_speed_10m) AS wind_speed_10_min,
           avg(wind_speed_10m)::DECIMAL(6, 3) AS wind_speed_10_avg,
           max(wind_speed_10m) AS wind_speed_10_max,
           min(wind_speed_100m) AS wind_speed_100_min,
           avg(wind_speed_100m)::DECIMAL(6, 3) AS wind_speed_100_avg,
           max(wind_speed_100m) AS wind_speed_100_max
    FROM {TABLE_NAME_OPEN_METEO} weather
    WHERE weather.lat > 51
    GROUP BY weather.date
), 

-- code duplication to avoid a whole table (but recommended in the future) (f-string didn't work because of that)
radiation_daily AS (
    SELECT DATE_TRUNC('day', weather.date) AS date,
           min(direct_radiation) AS direct_radiation_min,
           avg(direct_radiation)::DECIMAL(6, 3) AS direct_radiation_avg,
           max(direct_radiation) AS direct_radiation_max,
           min(diffuse_radiation) AS diffuse_radiation_min,
           avg(diffuse_radiation)::DECIMAL(6, 3) AS diffuse_radiation_avg,
           max(diffuse_radiation) AS diffuse_radiation_max,
           min(temperature_2m) AS temp2m_min,
           avg(temperature_2m)::DECIMAL(6, 3) AS temp2m_avg,
           max(temperature_2m) AS temp2m_max
    FROM {TABLE_NAME_OPEN_METEO} weather
    WHERE weather.lat < 52
    GROUP BY DATE_TRUNC('day', weather.date)
), wind_dir_count_daily AS ( -- count 12 locations by 8 weather direction
    SELECT COUNT(*) FILTER (WHERE 337.5 < wind_direction_100m AND wind_direction_100m <= 22.5) AS N,
           COUNT(*) FILTER (WHERE 22.5 < wind_direction_100m AND wind_direction_100m <= 67.5) AS NE,
           COUNT(*) FILTER (WHERE 67.5 < wind_direction_100m AND wind_direction_100m <= 112.5) AS E,
           COUNT(*) FILTER (WHERE 112.5 < wind_direction_100m AND wind_direction_100m <= 157.5) AS SE,
           COUNT(*) FILTER (WHERE 157.5 < wind_direction_100m AND wind_direction_100m <= 202.5) AS S,
           COUNT(*) FILTER (WHERE 202.5 < wind_direction_100m AND wind_direction_100m <= 247.5) AS SW,
           COUNT(*) FILTER (WHERE 247.5 < wind_direction_100m AND wind_direction_100m <= 292.5) AS W,
           COUNT(*) FILTER (WHERE 292.5 < wind_direction_100m AND wind_direction_100m <= 337.5) AS NW,
           DATE_TRUNC('day', weather.date) AS date
        FROM {TABLE_NAME_OPEN_METEO} weather
        GROUP BY DATE_TRUNC('day', weather.date)
), wind_dir_daily AS (
    SELECT date, CASE
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = n THEN 'north'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = ne THEN 'north_east'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = e THEN 'east'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = se THEN 'south_east'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = s THEN 'south'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = sw THEN 'south_west'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = w THEN 'west'
        WHEN GREATEST(n, ne, e, se, s, sw, w, nw) = nw THEN 'north_west'
        ELSE 'unknown' END AS wind_direction,
        round(
        	GREATEST(n, ne, e, se, s, sw, w, nw) /(12.0*24), 2
        )::DECIMAL(3, 2) AS wind_dir_uniformity
    FROM wind_dir_count_daily
), wind_daily AS (
    SELECT DATE_TRUNC('day', weather.date) AS date,
           min(wind_speed_10m) AS wind_speed_10_min,
           avg(wind_speed_10m)::DECIMAL(6, 3) AS wind_speed_10_avg,
           max(wind_speed_10m) AS wind_speed_10_max,
           min(wind_speed_100m) AS wind_speed_100_min,
           avg(wind_speed_100m)::DECIMAL(6, 3) AS wind_speed_100_avg,
           max(wind_speed_100m) AS wind_speed_100_max
    FROM {TABLE_NAME_OPEN_METEO} weather
    WHERE weather.lat > 51
    GROUP BY DATE_TRUNC('day', weather.date)
)

SELECT *, 'hour' AS resolution, -- renewable energy production index
		round( ( wind.wind_speed_100_max 
			+ ( radiation.direct_radiation_avg )/30
			+ ( radiation.diffuse_radiation_avg )/30
		)::Decimal(8, 4), 2 ) AS repi_30mix,
		round( ( least(wind.wind_speed_100_avg, 11)^3  	-- wind energy is scaling with the energy to the cube,
			+ ( radiation.direct_radiation_avg )		-- max power is reached at about 11m/s
			+ ( radiation.diffuse_radiation_avg )
		)::Decimal(8, 4), 2 ) AS repi_power1avg,
		round( ( least(wind.wind_speed_100_avg, 11)^3 
			+ radiation.direct_radiation_avg *2
			+ radiation.diffuse_radiation_avg *2
		)::Decimal(8, 4), 2 ) AS repi_power1avg2,
		round( ( 1550 * (1- exp(-0.001 * pow(wind.wind_speed_100_avg, 3)))  -- adjusted for a smooth limit, cuts x^3 at x=9.8
                   + radiation.direct_radiation_avg *1.4
                   + radiation.diffuse_radiation_avg *1.4
        )::Decimal(8, 4), 2 ) AS repi_power_exp,
/*		round( ( least(wind.wind_speed_100_avg, 11)^3 -- reflects more efficient converting of direct vs diffuse radiation
			+ ( radiation.direct_radiation_avg ) *3   -- check the 2025/02/12 to 2025/02/17 (diffuse radiation was overrated)
			+ ( radiation.diffuse_radiation_avg ) *1  -- But => correlation matrix shows worse performance
		)::Decimal(8, 4), 2 ) AS repi_power1avg3_1,*/
		round( ( least(wind.wind_speed_100_avg, 11)^2
			+ ( radiation.direct_radiation_avg )
			+ ( radiation.diffuse_radiation_avg )
		)::Decimal(8, 4), 2 ) AS repi_square1avg
FROM radiation
NATURAL JOIN wind
NATURAL JOIN wind_dir

UNION ALL 

SELECT *, 'day' AS resolution, 
		-- solar: 101 GW, wind: 75 GW   => 101/176 = 57%
		-- max /40: 20.21,19.75, 8.83           => (19.75+8.83)/(20.21+19.75+8.83) ≈ 58.6%
		-- avg /20:  6.87, 4.08, 2.75   
		-- => solar has a lower capacity factor but more installed capacity (hard to account for)
		round( ( wind_daily.wind_speed_100_max
			+ ( radiation_daily.direct_radiation_avg )/30
			+ ( radiation_daily.diffuse_radiation_avg )/30
		)::Decimal(8, 4), 2 ) AS repi_30mix,
		round( ( least(wind_daily.wind_speed_100_avg, 11)^3  	-- wind energy is scaling with the energy to the cube,
			+ ( radiation_daily.direct_radiation_avg )		-- max power is reached at about 11m/s
			+ ( radiation_daily.diffuse_radiation_avg )
		)::Decimal(8, 4), 2 ) AS repi_power1avg,
		round( ( least(wind_daily.wind_speed_100_avg, 11)^3 
			+ ( radiation_daily.direct_radiation_avg ) *2
			+ ( radiation_daily.diffuse_radiation_avg ) *2
		)::Decimal(8, 4), 2 ) AS repi_power1avg2,
		round( ( 1550 * (1- exp(-0.001 * pow(wind_daily.wind_speed_100_avg, 3)))  -- adjusted for a smooth limit, cuts x^3 at x=9.8
                   + radiation_daily.direct_radiation_avg *1.4
                   + radiation_daily.diffuse_radiation_avg *1.4
        )::Decimal(8, 4), 2 ) AS repi_power_exp,
		round( ( least(wind_daily.wind_speed_100_avg, 11)^2
			+ ( radiation_daily.direct_radiation_avg )
			+ ( radiation_daily.diffuse_radiation_avg )
		)::Decimal(8, 4), 2 ) AS repi_square1avg
FROM radiation_daily
NATURAL JOIN wind_daily
NATURAL JOIN wind_dir_daily
"""




historical_weather_forecasts_agg_view_sql = f"""-- # Unfortunately inserting into a view is not possible
WITH radiation AS (
    SELECT forecast.timestamp_s, forecast.model, forecast.temporal_resolution, 
           min(direct_radiation) AS direct_radiation_min,
           avg(direct_radiation)::DECIMAL(6, 3) AS direct_radiation_avg,
           avg(direct_radiation_previous_day1)::DECIMAL(6, 3) AS direct_radiation_avg_previous_day1,
           avg(direct_radiation_previous_day2)::DECIMAL(6, 3) AS direct_radiation_avg_previous_day2,
           avg(direct_radiation_previous_day3)::DECIMAL(6, 3) AS direct_radiation_avg_previous_day3,
           max(direct_radiation) AS direct_radiation_max,
           min(diffuse_radiation) AS diffuse_radiation_min,
           avg(diffuse_radiation)::DECIMAL(6, 3) AS diffuse_radiation_avg,
           avg(diffuse_radiation_previous_day1)::DECIMAL(6, 3) AS diffuse_radiation_avg_previous_day1,
           avg(diffuse_radiation_previous_day2)::DECIMAL(6, 3) AS diffuse_radiation_avg_previous_day2,
           avg(diffuse_radiation_previous_day3)::DECIMAL(6, 3) AS diffuse_radiation_avg_previous_day3,
           max(diffuse_radiation) AS diffuse_radiation_max,
           min(temperature_2m) AS temp2m_min,
           avg(temperature_2m)::DECIMAL(6, 3) AS temp2m_avg,
           avg(temperature_2m_previous_day1)::DECIMAL(6, 3) AS temperature_2m_avg_previous_day1,
           avg(temperature_2m_previous_day2)::DECIMAL(6, 3) AS temperature_2m_avg_previous_day2,
           avg(temperature_2m_previous_day3)::DECIMAL(6, 3) AS temperature_2m_avg_previous_day3,
           max(temperature_2m) AS temp2m_max
    FROM {TABLE_NAME_FORECASTS} forecast
    WHERE forecast.lat < 52
    GROUP BY forecast.model, forecast.timestamp_s, forecast.temporal_resolution
), wind AS (
    SELECT forecast.timestamp_s, forecast.model, forecast.temporal_resolution, 
           avg(wind_speed_80m) AS wind_speed_80m_avg,
           avg(wind_speed_80m_previous_day1)::DECIMAL(6, 3) AS wind_speed_80m_avg_previous_day1,
           avg(wind_speed_80m_previous_day2)::DECIMAL(6, 3) AS wind_speed_80m_avg_previous_day2,
           avg(wind_speed_80m_previous_day3)::DECIMAL(6, 3) AS wind_speed_80m_avg_previous_day3,
           avg(wind_speed_120m) AS wind_speed_120m_avg,
           avg(wind_speed_120m_previous_day1)::DECIMAL(6, 3) AS wind_speed_120m_avg_previous_day1,
           avg(wind_speed_120m_previous_day2)::DECIMAL(6, 3) AS wind_speed_120m_avg_previous_day2,
           avg(wind_speed_120m_previous_day3)::DECIMAL(6, 3) AS wind_speed_120m_avg_previous_day3,
           avg(wind_speed_180m) AS wind_speed_180m_avg,
           avg(wind_speed_180m_previous_day1)::DECIMAL(6, 3) AS wind_speed_180m_avg_previous_day1,
           avg(wind_speed_180m_previous_day2)::DECIMAL(6, 3) AS wind_speed_180m_avg_previous_day2,
           avg(wind_speed_180m_previous_day3)::DECIMAL(6, 3) AS wind_speed_180m_avg_previous_day3,
           (avg(wind_speed_80m) * POWER(100.0/80.0, LN(avg(wind_speed_120m)/avg(wind_speed_80m))
            		/ LN(120.0/80.0)))::DECIMAL(6, 3) as wind_100m_log,
           (avg(wind_speed_80m_previous_day1) * POWER(100.0/80.0, LN(avg(wind_speed_120m_previous_day1)/avg(wind_speed_80m_previous_day1))
            		/ LN(120.0/80.0)))::DECIMAL(6, 3) as wind_100m_log_previous_day1,
           (avg(wind_speed_80m_previous_day2) * POWER(100.0/80.0, LN(avg(wind_speed_120m_previous_day2)/avg(wind_speed_80m_previous_day2))
            		/ LN(120.0/80.0)))::DECIMAL(6, 3) as wind_100m_log_previous_day2,
           (avg(wind_speed_80m_previous_day3) * POWER(100.0/80.0, LN(avg(wind_speed_120m_previous_day3)/avg(wind_speed_80m_previous_day3))
            		/ LN(120.0/80.0)))::DECIMAL(6, 3) as wind_100m_log_previous_day3
    FROM {TABLE_NAME_FORECASTS} forecast
    WHERE forecast.lat > 51
    GROUP BY forecast.model, forecast.timestamp_s, forecast.temporal_resolution
)
-- wind energy is scaling with the energy to the cube,
-- max power is reached at about 11m/s
SELECT *, -- renewable energy production index
		round( ( least(wind.wind_100m_log, 11)^3 
			+ ( radiation.direct_radiation_avg ) *2 
			+ ( radiation.diffuse_radiation_avg ) *2 
		)::Decimal(8, 4), 2 ) AS repi_power1avg2, 
		
		round( ( least(wind.wind_100m_log_previous_day1, 11)^3 
			+ ( radiation.direct_radiation_avg_previous_day1 ) *2 
			+ ( radiation.diffuse_radiation_avg_previous_day1 ) *2 
		)::Decimal(8, 4), 2 ) AS repi_power1avg2_previous_day1, 
		
		round( ( least(wind.wind_100m_log_previous_day2, 11)^3 
			+ ( radiation.direct_radiation_avg_previous_day2 ) *2 
			+ ( radiation.diffuse_radiation_avg_previous_day2 ) *2 
		)::Decimal(8, 4), 2 ) AS repi_power1avg2_previous_day2, 
		
		round( ( least(wind.wind_100m_log_previous_day3, 11)^3 
			+ ( radiation.direct_radiation_avg_previous_day3 ) *2 
			+ ( radiation.diffuse_radiation_avg_previous_day3 ) *2 
		)::Decimal(8, 4), 2 ) AS repi_power1avg2_previous_day3,


		round( ( 1550 * (1- exp(-0.001 * pow(wind.wind_100m_log, 3)))  -- adjusted for a smooth limit, cuts x^3 at x=9.8
                   + radiation.direct_radiation_avg *1.4
                   + radiation.diffuse_radiation_avg *1.4
        )::Decimal(8, 4), 2 ) AS repi_power_exp,
        
		round( ( 1550 * (1- exp(-0.001 * pow(wind.wind_100m_log_previous_day1, 3)))  -- adjusted for a smooth limit, cuts x^3 at x=9.8
                   + radiation.direct_radiation_avg_previous_day1 *1.4
                   + radiation.diffuse_radiation_avg_previous_day1 *1.4
        )::Decimal(8, 4), 2 ) AS repi_power_exp_previous_day1,
        
		round( ( 1550 * (1- exp(-0.001 * pow(wind.wind_100m_log_previous_day2, 3)))  -- adjusted for a smooth limit, cuts x^3 at x=9.8
                   + radiation.direct_radiation_avg_previous_day2 *1.4
                   + radiation.diffuse_radiation_avg_previous_day2 *1.4
        )::Decimal(8, 4), 2 ) AS repi_power_exp_previous_day2,
        
		round( ( 1550 * (1- exp(-0.001 * pow(wind.wind_100m_log_previous_day3, 3)))  -- adjusted for a smooth limit, cuts x^3 at x=9.8
                   + radiation.direct_radiation_avg_previous_day3 *1.4
                   + radiation.diffuse_radiation_avg_previous_day3 *1.4
        )::Decimal(8, 4), 2 ) AS repi_power_exp_previous_day3
		
FROM radiation
NATURAL JOIN wind
"""



"""
-- temporal price distribution

SELECT series2019.price2019, series2020.price2020, series2021.price2021, series2022.price2022,
       series2023.price2023, series2024.price2024, series2019.t2019_days
FROM
    (SELECT t2019.market_price_ger_lux as price2019,
            ROW_NUMBER() OVER (ORDER BY t2019.market_price_ger_lux DESC) AS t2019_days
     FROM smard_data_collection t2019
     WHERE t2019.market_price_ger_lux IS NOT NULL
     AND t2019.region = 'DE'
     AND t2019.resolution = 'day'
     AND extract(YEAR FROM to_timestamp(t2019.unix_timestamp_ms / 1000)) = 2019
     ORDER BY t2019.market_price_ger_lux DESC ) series2019,

    (SELECT t2020.market_price_ger_lux as price2020,
            ROW_NUMBER() OVER (ORDER BY t2020.market_price_ger_lux DESC) AS t2020_days
     FROM smard_data_collection t2020
     WHERE t2020.market_price_ger_lux IS NOT NULL
     AND t2020.region = 'DE'
     AND t2020.resolution = 'day'
     AND extract(YEAR FROM to_timestamp(t2020.unix_timestamp_ms / 1000)) = 2020
     ORDER BY t2020.market_price_ger_lux DESC ) series2020,

    (SELECT t2021.market_price_ger_lux as price2021,
            ROW_NUMBER() OVER (ORDER BY t2021.market_price_ger_lux DESC) AS t2021_days
     FROM smard_data_collection t2021
     WHERE t2021.market_price_ger_lux IS NOT NULL
     AND t2021.region = 'DE'
     AND t2021.resolution = 'day'
     AND extract(YEAR FROM to_timestamp(t2021.unix_timestamp_ms / 1000)) = 2021
     ORDER BY t2021.market_price_ger_lux DESC ) series2021,

    (SELECT t2022.market_price_ger_lux as price2022,
            ROW_NUMBER() OVER (ORDER BY t2022.market_price_ger_lux DESC) AS t2022_days
     FROM smard_data_collection t2022
     WHERE t2022.market_price_ger_lux IS NOT NULL
     AND t2022.region = 'DE'
     AND t2022.resolution = 'day'
     AND extract(YEAR FROM to_timestamp(t2022.unix_timestamp_ms / 1000)) = 2022
     ORDER BY t2022.market_price_ger_lux DESC ) series2022,

    (SELECT t2023.market_price_ger_lux as price2023,
            ROW_NUMBER() OVER (ORDER BY t2023.market_price_ger_lux DESC) AS t2023_days
     FROM smard_data_collection t2023
     WHERE t2023.market_price_ger_lux IS NOT NULL
     AND t2023.region = 'DE'
     AND t2023.resolution = 'day'
     AND extract(YEAR FROM to_timestamp(t2023.unix_timestamp_ms / 1000)) = 2023
     ORDER BY t2023.market_price_ger_lux DESC ) series2023,

    (SELECT t2024.market_price_ger_lux as price2024,
            ROW_NUMBER() OVER (ORDER BY t2024.market_price_ger_lux DESC) AS t2024_days
     FROM smard_data_collection t2024
     WHERE t2024.market_price_ger_lux IS NOT NULL
     AND t2024.region = 'DE'
     AND t2024.resolution = 'day'
     AND extract(YEAR FROM to_timestamp(t2024.unix_timestamp_ms / 1000)) = 2024
     ORDER BY t2024.market_price_ger_lux DESC ) series2024

WHERE series2019.t2019_days = series2020.t2020_days
    AND series2020.t2020_days = series2021.t2021_days
    AND series2021.t2021_days = series2022.t2022_days
    AND series2022.t2022_days = series2023.t2023_days
    AND series2023.t2023_days = series2024.t2024_days
"""


"""
-- META STATS of data
    
SELECT count(t.unix_timestamp_ms), TO_CHAR(
        to_timestamp(min(t.unix_timestamp_ms)/1000) AT TIME ZONE 'Europe/Berlin',
        'YYYY/MM/DD HH24:MI' ) AS min, TO_CHAR(
        to_timestamp(max(t.unix_timestamp_ms)/1000) AT TIME ZONE 'Europe/Berlin',
        'YYYY/MM/DD HH24:MI' ) AS max
    FROM smard_data_collection t
    WHERE resolution = 'quarterhour'
      AND region = 'DE'
UNION ALL
    SELECT count(t.unix_timestamp_ms), TO_CHAR(
        to_timestamp(min(t.unix_timestamp_ms)/1000) AT TIME ZONE 'Europe/Berlin',
        'YYYY/MM/DD HH24:MI' ) AS min, TO_CHAR(
        to_timestamp(max(t.unix_timestamp_ms)/1000) AT TIME ZONE 'Europe/Berlin',
        'YYYY/MM/DD HH24:MI' ) AS max
    FROM smard_data_collection t
    WHERE resolution = 'quarterhour'
      AND region = 'DE' AND t.market_price_ger_lux IS NOT NULL    
-- count: 370268, min: 2014/12/29 00:00, max: 2025/07/20 23:45
-- count: 237984, min: 2018/10/01 00:00, max: 2025/07/14 23:45
    
-- 370272 /4/24 = 3857 days of record
-- 3857 /365 = 10 years 207 days
"""


"""
-- price during filtered for 100% R.E. supply

SELECT t.unix_timestamp_ms, sdc.market_price_ger_lux, TO_CHAR(
        to_timestamp(t.unix_timestamp_ms/1000) AT TIME ZONE 'Europe/Berlin',
        'MM/DD HH24:MI'
    ) AS date, ROW_NUMBER() OVER (ORDER BY market_price_ger_lux DESC) as hour, 2024 as year,
               t.share_of_photovoltaic_wind_onshore_offshore_computed as size
FROM computed_data_re_share_and_external_trade t
JOIN public.smard_data_collection sdc
    ON t.unix_timestamp_ms = sdc.unix_timestamp_ms AND t.region = sdc.region AND t.resolution = sdc.resolution
WHERE t.share_of_photovoltaic_wind_onshore_offshore_computed >= 1
AND t.resolution = 'hour'
AND t.region = 'DE'
AND extract(YEAR FROM to_timestamp(t.unix_timestamp_ms / 1000)) = 2024
AND sdc.market_price_ger_lux IS NOT NULL

UNION ALL

SELECT t.unix_timestamp_ms, sdc.market_price_ger_lux, TO_CHAR(
        to_timestamp(t.unix_timestamp_ms/1000) AT TIME ZONE 'Europe/Berlin',
        'MM/DD HH24:MI'
    ) AS date, ROW_NUMBER() OVER (ORDER BY market_price_ger_lux DESC) as hour, 2023 as year,
               t.share_of_photovoltaic_wind_onshore_offshore_computed as size
FROM computed_data_re_share_and_external_trade t
JOIN public.smard_data_collection sdc
    ON t.unix_timestamp_ms = sdc.unix_timestamp_ms AND t.region = sdc.region AND t.resolution = sdc.resolution
WHERE t.share_of_photovoltaic_wind_onshore_offshore_computed >= 1
AND t.resolution = 'hour'
AND t.region = 'DE'
AND extract(YEAR FROM to_timestamp(t.unix_timestamp_ms / 1000)) = 2023
AND sdc.market_price_ger_lux IS NOT NULL

UNION ALL

SELECT t.unix_timestamp_ms, sdc.market_price_ger_lux, TO_CHAR(
        to_timestamp(t.unix_timestamp_ms/1000) AT TIME ZONE 'Europe/Berlin',
        'MM/DD HH24:MI'
    ) AS date, ROW_NUMBER() OVER (ORDER BY market_price_ger_lux DESC) as hour, 2025 as year,
               t.share_of_photovoltaic_wind_onshore_offshore_computed as size
FROM computed_data_re_share_and_external_trade t
JOIN public.smard_data_collection sdc
    ON t.unix_timestamp_ms = sdc.unix_timestamp_ms AND t.region = sdc.region AND t.resolution = sdc.resolution
WHERE t.share_of_photovoltaic_wind_onshore_offshore_computed >= 1
AND t.resolution = 'hour'
AND t.region = 'DE'
AND extract(YEAR FROM to_timestamp(t.unix_timestamp_ms / 1000)) = 2025
AND sdc.market_price_ger_lux IS NOT NULL

UNION ALL

SELECT t.unix_timestamp_ms, sdc.market_price_ger_lux, TO_CHAR(
        to_timestamp(t.unix_timestamp_ms/1000) AT TIME ZONE 'Europe/Berlin',
        'MM/DD HH24:MI'
    ) AS date, ROW_NUMBER() OVER (ORDER BY market_price_ger_lux DESC) as hour, 2022 as year,
               t.share_of_photovoltaic_wind_onshore_offshore_computed as size
FROM computed_data_re_share_and_external_trade t
JOIN public.smard_data_collection sdc
    ON t.unix_timestamp_ms = sdc.unix_timestamp_ms AND t.region = sdc.region AND t.resolution = sdc.resolution
WHERE t.share_of_photovoltaic_wind_onshore_offshore_computed >= 1
AND t.resolution = 'hour'
AND t.region = 'DE'
AND extract(YEAR FROM to_timestamp(t.unix_timestamp_ms / 1000)) = 2022
AND sdc.market_price_ger_lux IS NOT NULL
    
-- The Value of Electricity is in Hellbrise always negative, hours of incidences increasing every year
-- 2025: 126 out of (365*24h=) 8760h => 1.44%

-- Outliers 2023: 
-- market price GER/LUX: -500.00, date: 2023/07/02, time: 14, more supply of wind+solar than demand: 2.72%
-- market price GER/LUX: -399.00, date: 2023/07/02, time: 15, more supply of wind+solar than demand: 5.88%
-- market price GER/LUX: -266.92, date: 2023/07/02, time: 13, more supply of wind+solar than demand: 0.89%

-- TODO: Transform query to the use of CTE to reduce duplicate lines
"""



"""
-- Power Consumption Total is not solely responsible for the prices as 2024/01/15 11:00, max(2024), the price was 90.26 €/MWh
-- and 2023/06/18 04:00, min(2023), the price was at 104.00 €/MWh
-- Keep in mind that these extremes are closely followed by unrelated points in time where the consumption was about the same
-- Nevertheless, the maxima are in the winter, minima most times in the summer with Xmas 2022 and 2024/09/22 3am as an exemption
WITH temp as (
    SELECT t.unix_timestamp_ms, t.power_consumption_total, extract(YEAR FROM to_timestamp(t.unix_timestamp_ms / 1000)) as year,
           TO_CHAR(
            to_timestamp(t.unix_timestamp_ms/1000) AT TIME ZONE 'Europe/Berlin',
            'YYYY/MM/DD HH24:MI'
        ) AS date, market_price_ger_lux
    FROM smard_data_collection t
    WHERE t.region='DE'
    AND t.resolution='hour'
)
SELECT * FROM (
    SELECT *,
           power_consumption_total = MAX(power_consumption_total) OVER() OR
           power_consumption_total = MIN(power_consumption_total) OVER() as is_extreme
    FROM temp t WHERE year=2023
) t2023 WHERE t2023.is_extreme
UNION ALL
SELECT * FROM (
    SELECT *,
           power_consumption_total = MAX(power_consumption_total) OVER() OR
           power_consumption_total = MIN(power_consumption_total) OVER() as is_extreme
    FROM temp t WHERE year=2024
) t2024 WHERE t2024.is_extreme
UNION ALL
SELECT * FROM (
    SELECT *,
           power_consumption_total = MAX(power_consumption_total) OVER() OR
           power_consumption_total = MIN(power_consumption_total) OVER() as is_extreme
    FROM temp t WHERE year=2022
) t2022 WHERE t2022.is_extreme
UNION ALL
SELECT * FROM (
    SELECT *,
           power_consumption_total = MAX(power_consumption_total) OVER() OR
           power_consumption_total = MIN(power_consumption_total) OVER() as is_extreme
    FROM temp t WHERE year=2021
) t2021 WHERE t2021.is_extreme
UNION ALL
SELECT * FROM ( -- Corona year was the weakest
    SELECT *,
           power_consumption_total = MAX(power_consumption_total) OVER() OR
           power_consumption_total = MIN(power_consumption_total) OVER() as is_extreme
    FROM temp t WHERE year=2020
) t2020 WHERE t2020.is_extreme
ORDER BY power_consumption_total
        /*
        consumption: 30902.75,  year: 2023,  date: 2023/06/18 04:00,  price: 104.00
        consumption: 32413.25,  year: 2024,  date: 2024/09/22 03:00,  price: 89.50
        consumption: 33042.50,  year: 2020,  date: 2020/06/01 03:00,  price: 6.07
        consumption: 34122.50,  year: 2022,  date: 2022/12/25 02:00,  price: 106.65
        consumption: 36580.75,  year: 2021,  date: 2021/06/06 05:00,  price: 51.63
        consumption: 73747.50,  year: 2023,  date: 2023/12/04 17:00,  price: 127.75
        consumption: 75508.25,  year: 2024,  date: 2024/01/15 11:00,  price: 90.26
        consumption: 78599.25,  year: 2020,  date: 2020/12/03 17:00,  price: 52.94
        consumption: 78680.50,  year: 2022,  date: 2022/02/01 12:00,  price: 143.70
        consumption: 81319.50,  year: 2021,  date: 2021/11/30 11:00,  price: 108.44
        */
"""



"""
-- Residual Load = Backup Power Plant needs
SELECT max(t.power_consumption_residual_load) as megawatt_res_load, extract(YEAR FROM to_timestamp(t.unix_timestamp_ms / 1000)) as year
FROM smard_data_collection t
WHERE t.resolution = 'hour'
AND t.region = 'DE'
GROUP BY extract(YEAR FROM to_timestamp(t.unix_timestamp_ms / 1000))
ORDER BY year
/*
75093.5,2015
75951.75,2016
76049,2017
72721.75,2018
74638.75,2019
72274.5,2020
70465,2021
70964,2022
67957.75,2023
67251,2024
67890.25,2025
*/
"""



"""
-- Electricity consumption per year in TWh
SELECT extract(YEAR FROM to_timestamp(min(t.unix_timestamp_ms) / 1000)) AS date,
       sum( t.power_consumption_total ) /1000 /1000 AS yearly_consumption_in_TWh
FROM smard_data_collection t
WHERE resolution='hour'
AND region='DE'
AND extract(YEAR FROM to_timestamp(t.unix_timestamp_ms / 1000)) IN (
        2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024
    )
GROUP BY extract(YEAR FROM to_timestamp(t.unix_timestamp_ms / 1000))
    /*
     2015: 500.218634
     2016: 503.0870325
     2017: 505.67943475
     2018: 509.25270175
     2019: 497.36780625
     2020: 485.357906
     2021: 504.6008845
     2022: 482.29037925
     2023: 458.3835565
     2024: 465.508479
     */
"""



""" -- Compare the calculated wind speed of the various coordinates with the different weather models
WITH shear AS ( -- Calculate average shear exponent from available height pairs
    SELECT
        (LN(avg(wind_speed_120m)/avg(wind_speed_80m)) / LN(120.0/80.0) +
         LN(avg(wind_speed_180m)/avg(wind_speed_120m)) / LN(180.0/120.0) +
         LN(avg(wind_speed_180m)/avg(wind_speed_80m)) / LN(180.0/80.0)) / 3.0
            as alpha_avg,
        forecast.model, forecast.lat, forecast.lng,
        avg(wind_speed_80m)::DECIMAL(6, 3) AS wind_speed_80m_avg,
        avg(wind_speed_120m)::DECIMAL(6, 3) AS wind_speed_120m_avg,
        avg(wind_speed_180m)::DECIMAL(6, 3) AS wind_speed_180m_avg,
        (avg(wind_speed_80m) * POWER(100.0/80.0, LN(avg(wind_speed_120m)/avg(wind_speed_80m)) / LN(120.0/80.0)))
            ::DECIMAL(6, 3) as wind_100m_log
    FROM weather_forecasts_data_raw forecast
    GROUP BY forecast.lat, forecast.lng, forecast.model
) SELECT
    w.model, w.lat, w.lng,
    round(wind_100m_log, 2) as wind_speed_80_120_log,
    round((avg(w.wind_speed_80m) * POWER(100.0/80.0, p.alpha_avg))::DECIMAL(6, 3), 2) as wind_speed_80_120_180_log_avg -- null for gfs_global
    FROM weather_forecasts_data_raw w
    JOIN shear p ON w.model=p.model AND w.lat=p.lat AND w.lng=p.lng
    GROUP BY w.model, w.lat, w.lng, p.alpha_avg, p.wind_100m_log, w.model
    ORDER BY alpha_avg;
"""