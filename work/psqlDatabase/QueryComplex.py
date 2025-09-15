import time

import psycopg2
from Helper import (TABLE_NAME_SMARD, DB_PARAMS, FILTER, FilterTranslations, OTHER_THAN_SMARD_FILTER_IDs,
					VIEW_NAME_RE_SHARE_EXT_TRADE, VIEW_NAME_PRICE_CHANGE, VIEW_NAME_HISTORICAL_WEATHER_AGG)


# Merge SMARD data with computed views
def get_timeseries( region, resolution, filter_ids, start_ms, end_ms ):

    filterIdsComputed = [ fId for fId in filter_ids if fId in OTHER_THAN_SMARD_FILTER_IDs ]
    filterIdsSmard = [fId for fId in filter_ids if fId not in filterIdsComputed]

    print( f"{filterIdsComputed = } | {filterIdsSmard = }" )

    filter_names_smard = [ FilterTranslations[ FILTER.inverse[ id ] ] for id in filterIdsSmard ]
    smardResult = get_smard_timeseries( region, resolution, filter_names_smard, start_ms, end_ms )

    filter_names_views = [ FilterTranslations[ FILTER.inverse[ id ] ] for id in filterIdsComputed ]
    viewResult = get_computed_timeseries( region, resolution, filter_names_views, start_ms, end_ms )

    if len(filterIdsSmard) == 0:
        return viewResult
    if len(filterIdsComputed) == 0:
        return smardResult

    rows = merge(smardResult, viewResult)  # len(viewResult[1])  # ERROR: TypeError: object of type 'NoneType' has no len()
    cols = smardResult[1][:3] + filter_names_smard + filter_names_views
    return rows, cols



# Keep the FLAGS in the database in mind
# TODO: Enhance Timestamps Filtering
# TODO: Fully Support different Regions (but current focus is on Germany)
def get_smard_timeseries( region, resolution, filter_names, start_ms, end_ms ):
    if filter_names == []:
        return [], []  # needed because otherwise the query doesn't make sense
    conn, cursor, rows, column_names = [None] * 4
    try:
        conn = psycopg2.connect( **DB_PARAMS )
        cursor = conn.cursor()

        cursor.execute( f"""-- I wish Highcharts is automatically converting the unix timestamp to the local timezone
						SELECT (extract( EPOCH FROM (to_timestamp(unix_timestamp_ms/1000)
								AT TIME ZONE 'Europe/Berlin')) *1000)::BIGINT								
								AS unix_timestamp_ms, 
								region, resolution, {", ".join(filter_names)}
							FROM {TABLE_NAME_SMARD} 
							WHERE region = '{region}'
							AND resolution = '{resolution}'
							AND unix_timestamp_ms >= {start_ms}
							AND unix_timestamp_ms <= {end_ms}; """
                        )
        rows = cursor.fetchall()

        column_names = [ desc[ 0 ] for desc in cursor.description ]
        # print( f"Found {len( rows )} rows with columns: {column_names}")
    except psycopg2.Error as e:
        print( f"Database error: {e}" )
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
    return rows, column_names


def get_computed_timeseries( region, resolution, filter_names, start_ms, end_ms ):
    if filter_names == []:
        return [], []
    conn, cursor, rows, column_names = [None] * 4
    try:
        conn = psycopg2.connect( **DB_PARAMS )
        cursor = conn.cursor()
        cursor.execute( f"""
                        WITH filled_primary_keys AS (
                            SELECT *,
                            		-- computed_data_historical_weather_agg date already in TZ 'Europe/Berlin'
									-- smard_data_collection in 'UTC'
                                   CASE
										WHEN pct.unix_timestamp_ms IS NULL THEN rsett.unix_timestamp_ms
										ELSE pct.unix_timestamp_ms END AS unix_timestamp_ms_filled,
                                   extract( EPOCH FROM
                                            to_timestamp( (CASE
                                                WHEN pct.unix_timestamp_ms IS NULL THEN rsett.unix_timestamp_ms
                                                ELSE pct.unix_timestamp_ms END) /1000)
                                                AT TIME ZONE 'Europe/Berlin') AS tstz,  -- convert here for performance
                                   CASE
                                       WHEN pct.region IS NULL THEN rsett.region
                                       ELSE pct.region END AS region_filled,
                                   CASE
                                       WHEN pct.resolution IS NULL THEN rsett.resolution
                                       ELSE pct.resolution END AS resolution_filled
                                FROM {VIEW_NAME_PRICE_CHANGE} pct
                                         NATURAL FULL JOIN {VIEW_NAME_RE_SHARE_EXT_TRADE} rsett)
						 -- TODO: move to s instead of ms
                        SELECT (extract(EPOCH FROM (to_timestamp(t.unix_timestamp_ms_filled/1000)                         		
                        		AT TIME ZONE 'Europe/Berlin'))*1000)::BIGINT as unix_timestamp_ms, 
                        		t.region_filled as region,
                         		t.resolution_filled as resolution, {", ".join(filter_names)}
                            FROM filled_primary_keys t
                            LEFT JOIN {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
                                ON extract(EPOCH FROM weather.date) = t.tstz
                                    AND t.resolution_filled::text in ('hour', 'day')
                                    AND t.resolution_filled::text = weather.resolution
                            WHERE t.region_filled = '{region}'
                            AND t.resolution_filled = '{resolution}'
                            AND t.unix_timestamp_ms_filled >= {start_ms}
                            AND t.unix_timestamp_ms_filled <= {end_ms}
                            ORDER BY t.unix_timestamp_ms_filled ASC;
                        """)

        rows = cursor.fetchall()

        column_names = [ desc[ 0 ] for desc in cursor.description ]
        print( f"Computed: Found {len( rows )} rows with columns: {column_names}")
        print( f"Computed: Used {resolution = }, {region = }, {start_ms = } and {end_ms = }")


    except psycopg2.Error as e:
        print( f"Database error: {e}" )
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
    return rows, column_names


# TODO: Test Correctness
def merge(smardResult, viewResult):
    smardDict, viewDict, mergedDict = {}, {}, {}
    smardRowDataWidth = len(smardResult[1]) - 3
    viewsRowDataWidth = len(viewResult[1]) - 3  # ERROR: TypeError: object of type 'NoneType' has no len()
    for row in smardResult[0]:
        smardDict[tuple(row[:3])] = row[3:]
    for row in viewResult[0]:
        viewDict[tuple(row[:3])] = row[3:]

    print("smardDict.items() at " + str(time.time()))
    for key, value in smardDict.items():
        mergedDict[ key ] = value + viewDict.get( key, tuple( [None]*viewsRowDataWidth) )
    for key, value in viewDict.items():
        mergedDict[ key ] = smardDict.get( key, tuple( [None]*smardRowDataWidth) ) + value

    rows = []
    for key, value in mergedDict.items():
        rows.append( key + value )

    return rows
