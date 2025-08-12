
from Helper import FilterTranslations, TABLE_NAME_SMARD, FILTER, WIND_SOLAR_ID, RE_SHARE_ID, ELEC_IMPORT_ID, \
        ELEC_PRICE_CHANGE_ABS_ID, ELEC_PRICE_CHANGE_REL_ID, VIEW_NAME_RE_SHARE_EXT_TRADE

# Share of the renewable load as a test for the postgresql view
## Calculating a virtual percentage/max_share line of (wind+solar) on total demand if resLoad + gridLoad are available
# TODO: Fix not forecasted electricity import
re_share_import_view_sql = f"""
        SELECT  t.unix_timestamp_ms, t.region, t.resolution, 
            1- ((t.power_consumption_residual_load) / t.power_consumption_total)::DECIMAL(6, 5) 
            AS {FilterTranslations[FILTER.inverse[WIND_SOLAR_ID]]}, 
            
            1- ((t.power_consumption_residual_load - t.electricity_production_hydropower - t.electricity_production_other_renewables 
             - t.electricity_production_biomass - t.electricity_production_pumped_storage ) 
             / t.power_consumption_total)::DECIMAL(6, 5) 
            AS {FilterTranslations[FILTER.inverse[RE_SHARE_ID]]}, 
            -- "Nur der importierte Strom stammt aus eigenen Berechnungen und entspricht der Differenz von Neztlast und Erzeugung."
            (t.power_consumption_total - t.total_production)::DECIMAL(12, 2) 
            AS import_to_fix, 
            
            (t.power_consumption_total - t.production_forecast_total)::DECIMAL(11, 2) 
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
                + electricity_production_natural_gas
            )::DECIMAL(12, 2) AS total_production 
            FROM {TABLE_NAME_SMARD} d
            ORDER BY unix_timestamp_ms ASC 
             ) t
        WHERE t.power_consumption_residual_load is not null 
                and t.power_consumption_total is not null
                and t.power_consumption_total != 0
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
# TODO: Add peak price during DUnkelflaute?
def dunkelflauten_stats_view_sql( threshold=0.3 ):
        return f"""
                WITH prices AS (
                    SELECT sdc.unix_timestamp_ms, sdc.region, sdc.resolution, sdc.market_price_ger_lux AS ger_lux,
                           sdc.power_consumption_residual_load AS res_load
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
                        AND t.resolution = 'quarterhour'),
                     events AS (
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
                        FROM matches),
                     extent_revenue AS ( -- 17 seconds for this table
                        SELECT pd.*,
                           (
                               SELECT SUM(p.res_load)
                                   FROM prices p
                                   WHERE p.unix_timestamp_ms 
                                   BETWEEN pd.start_time AND pd.end_time) AS extent,
                           (
                               SELECT SUM(p.res_load * p.ger_lux)
                                   FROM prices p
                                   WHERE p.unix_timestamp_ms 
                                   BETWEEN pd.start_time AND pd.end_time) AS res_load_revenue_during_df,
                           (
                               SELECT SUM(p.res_load)
                                   FROM prices p
                                   WHERE p.unix_timestamp_ms
                                   BETWEEN pd.start_time - 1000 *60 *60 *24 *7::BIGINT AND pd.start_time) AS extent_week_before,
                           (
                               SELECT SUM(p.res_load * p.ger_lux)
                                   FROM prices p
                                   WHERE p.unix_timestamp_ms
                                   BETWEEN pd.start_time - 1000 *60 *60 *24 *7::BIGINT AND pd.start_time) AS res_load_revenue_before_df,
                           (
                               SELECT SUM(p.res_load)
                                   FROM prices p
                                   WHERE p.unix_timestamp_ms
                                   BETWEEN pd.end_time AND pd.end_time + 1000 *60 *60 *24 *7::BIGINT) AS extent_week_after,
                           (
                               SELECT SUM(p.res_load * p.ger_lux)
                                   FROM prices p
                                   WHERE p.unix_timestamp_ms
                                   BETWEEN pd.end_time AND pd.end_time + 1000 *60 *60 *24 *7::BIGINT) AS res_load_revenue_after_df
                                FROM dunkelflauten pd
                                
                        ), dunkelflauten_prices AS ( --38 secs for this table
                        SELECT er.*,
                           (er.res_load_revenue_during_df / er.extent)::DECIMAL(6, 2) AS avg_weighted_price_during_dunkelflaute,
                           (er.res_load_revenue_before_df / er.extent_week_before)::DECIMAL(6, 2) AS avg_weighted_price_before_dunkelflaute,
                           (er.res_load_revenue_after_df / er.extent_week_after)::DECIMAL(6, 2) AS avg_weighted_price_after_dunkelflaute,
                           (
                               SELECT AVG(during_df.ger_lux)
                                   FROM prices during_df
                                   WHERE during_df.unix_timestamp_ms
                                             BETWEEN er.start_time AND er.start_time -- <=> value >= low AND value <= high
                           )::DECIMAL(6, 2) AS avg_price_during_dunkelflaute,
                           (
                               SELECT AVG(week_before_df.ger_lux)
                                   FROM prices week_before_df
                                   WHERE week_before_df.unix_timestamp_ms
                                             BETWEEN er.start_time - 1000 * 60 * 60 * 24 * 7::BIGINT AND er.start_time -- <=> value >= low AND value <= high
                           )::DECIMAL(6, 2) AS avg_price_week_before_dunkelflaute,
                           (
                               SELECT AVG(week_after_df.ger_lux)
                                   FROM prices week_after_df
                                   WHERE week_after_df.unix_timestamp_ms
                                             -- 1 or 7 days because in between those it takes the other more expensive Dunkelflauten periods into account too
                                             BETWEEN er.end_time AND er.end_time + 1000 * 60 * 60 * 24 * 7::BIGINT
                            )::DECIMAL(6, 2)  AS avg_price_week_after_dunkelflaute
                        FROM extent_revenue er
                        WHERE er.res_load_revenue_during_df IS NOT NULL
                        
                    ), price_delta AS ( --1 min 3 s for this table
                            SELECT dp.*,
                                   dp.avg_price_during_dunkelflaute
                                       - (dp.avg_price_week_before_dunkelflaute + dp.avg_price_week_after_dunkelflaute) / 2
                                       ::DECIMAL(7, 3) AS price_increase_during_df,
                                   ((dp.avg_price_during_dunkelflaute
                                       / ((dp.avg_price_week_before_dunkelflaute + dp.avg_price_week_after_dunkelflaute) / 2))
                                       -1)*100
                                       ::DECIMAL(7, 3) AS relative_price_increase_during_df,
                                   dp.avg_weighted_price_during_dunkelflaute
                                       - (dp.avg_weighted_price_before_dunkelflaute + dp.avg_weighted_price_after_dunkelflaute) / 2
                                       AS price_increase_during_df_weighted,
                                   ((dp.avg_weighted_price_during_dunkelflaute
                                       / ((dp.avg_weighted_price_before_dunkelflaute + dp.avg_weighted_price_after_dunkelflaute) / 2))
                                       -1)*100
                                       ::DECIMAL(7, 3) AS relative_weighted_price_increase_during_df,
                                   dp.avg_weighted_price_during_dunkelflaute
                                       > LEAST(dp.avg_price_week_before_dunkelflaute, dp.avg_price_week_after_dunkelflaute)
                                       AND dp.avg_weighted_price_during_dunkelflaute
                                               < GREATEST(dp.avg_price_week_before_dunkelflaute, dp.avg_price_week_after_dunkelflaute)
                                       AS dp_in_before_after_range
                                FROM dunkelflauten_prices dp
                
                    ) SELECT *, extent * price_increase_during_df_weighted ::DECIMAL(14, 2) AS dunkelflauten_cost,
                             extract(DOW FROM (to_timestamp((start_time + end_time) / 2 / 1000) 
                                AT TIME ZONE 'Europe/Berlin')) AS day_of_week,
                             extract(MONTH FROM (to_timestamp((start_time + end_time) / 2 / 1000) 
                                AT TIME ZONE 'Europe/Berlin')) AS month,
                             extract(YEAR FROM (to_timestamp((start_time + end_time) / 2 / 1000)  
                                AT TIME ZONE 'Europe/Berlin')) AS year,
                             duration as duration_ms,
                             (duration / (1000*60*60*24.0))::Decimal(5, 2) AS duration_days
                    FROM price_delta
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
"""
