
from Helper import FilterTranslations, TABLE_NAME_SMARD, FILTER, RE_SHARE_ID, ELEC_IMPORT_ID, \
        ELEC_PRICE_CHANGE_ABS_ID, ELEC_PRICE_CHANGE_REL_ID


# Share of the renewable load as a test for the postgresql view
## Calculating a virtual percentage/share line of (wind+solar) on total demand if resLoad + gridLoad are available
# TODO: Fix not forecasted electricity import
re_share_import_view_sql = f"""
        SELECT  t.unix_timestamp_ms, t.region, t.resolution,
            1- (t.power_consumption_residual_load / t.power_consumption_total)::DECIMAL(6, 5) 
            AS {FilterTranslations[FILTER.inverse[RE_SHARE_ID]]},
            /* Nur der importierte Strom stammt aus eigenen Berechnungen und entspricht der Differenz von Neztlast und Erzeugung.

                electricity_production_lignite + electricity_production_nuclear_energy + electricity_production_wind_offshore +
                electricity_production_hydropower + 
                electricity_production_biomass + electricity_production_wind_onshore + electricity_production_photovoltaics + 
                electricity_production_hard_coal + electricity_production_pumped_storage + electricity_production_natural_gas 
               */
            (t.power_consumption_total - t.total_production)::DECIMAL(12, 2) 
            AS import_to_fix, 
            (t.power_consumption_total - t.production_forecast_total)::DECIMAL(11, 2) 
            AS {FilterTranslations[FILTER.inverse[ELEC_IMPORT_ID]]}
        FROM (
            SELECT *, ( 
                electricity_production_conventional + electricity_production_renewables + electricity_production_wind_offshore +
                electricity_production_hydropower + 
                electricity_production_biomass + electricity_production_wind_onshore + electricity_production_photovoltaics + 
                electricity_production_pumped_storage 
            )::DECIMAL(12, 2) AS total_production 
            FROM {TABLE_NAME_SMARD} d
            ORDER BY unix_timestamp_ms DESC 
             ) t
        WHERE t.power_consumption_residual_load is not null 
                and t.power_consumption_total is not null
                and t.power_consumption_total != 0
        """


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
       ((current_price / last_price) - 1)::DECIMAL(9, 5) as {FilterTranslations[FILTER.inverse[ELEC_PRICE_CHANGE_REL_ID]]}
FROM ger_lux_prices tmp
WHERE current_price IS NOT NULL
  AND last_price IS NOT NULL
  AND last_price != 0
  AND CASE resolution
          WHEN 'quarterhour' THEN unix_timestamp_ms - last_time = 1000 * 60 * 15 /* 15 min in milliseconds */
          WHEN 'hour' THEN unix_timestamp_ms - last_time = 1000 * 60 * 15 * 4
          WHEN 'day' THEN unix_timestamp_ms - last_time = 1000 * 60 * 15 * 4 * 24
          WHEN 'week' THEN unix_timestamp_ms - last_time = 1000 * 60 * 15 * 4 * 24 * 7
          ELSE FALSE
    END
ORDER BY region, unix_timestamp_ms
"""
