import time

import psycopg2
from psycopg2 import sql
from config import DB_PARAMS
from Helper import (TABLE_NAME_SMARD, FILTER, FilterTranslations, OTHER_THAN_SMARD_FILTER_IDs,
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
    allowed_filter_names = set( FilterTranslations.values() )
    if filter_names == [] or any( filter_name not in allowed_filter_names for filter_name in filter_names ):
        return [], []  # needed because otherwise the query doesn't make sense
    conn, cursor, rows, column_names = [None] * 4
    try:
        conn = psycopg2.connect( **DB_PARAMS )
        cursor = conn.cursor()

        query = sql.SQL("""-- I wish Highcharts is automatically converting the unix timestamp to the local timezone
						SELECT (extract( EPOCH FROM (to_timestamp(unix_timestamp_ms/1000)
								AT TIME ZONE 'Europe/Berlin')) *1000)::BIGINT								
								AS unix_timestamp_ms, 
								region, resolution, {columns}
							FROM {table_name}
							WHERE region = %s
                                AND resolution = %s
                                AND unix_timestamp_ms >= %s
                                AND unix_timestamp_ms <= %s; """
                        ).format(
            columns = sql.SQL( ", " ).join( sql.Identifier( name.lower() ) for name in filter_names ),
            table_name = sql.Identifier( TABLE_NAME_SMARD )
        )
        cursor.execute( query, (region, resolution, start_ms, end_ms) )
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
    allowed_filter_names = set( FilterTranslations.values() )
    if filter_names == [] or any( filter_name not in allowed_filter_names for filter_name in filter_names ):
        return [], []
    conn, cursor, rows, column_names = [None] * 4
    try:
        conn = psycopg2.connect( **DB_PARAMS )
        cursor = conn.cursor()
        query = sql.SQL("""
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
                                FROM {view_name_price_change} pct
                                         NATURAL FULL JOIN {view_name_re_share_ext_trade} rsett)
						 -- TODO: move to s instead of ms
                        SELECT (extract(EPOCH FROM (to_timestamp(t.unix_timestamp_ms_filled/1000)                         		
                        		AT TIME ZONE 'Europe/Berlin'))*1000)::BIGINT as unix_timestamp_ms, 
                        		t.region_filled as region,
								t.resolution_filled as resolution, {columns}
                            FROM filled_primary_keys t
                            LEFT JOIN {view_name_historical_weather_agg} weather
                                ON extract(EPOCH FROM weather.date) = t.tstz
                                    AND t.resolution_filled::text in ('hour', 'day')
                                    AND t.resolution_filled::text = weather.resolution
                            WHERE t.region_filled = %s
                            AND t.resolution_filled = %s
                            AND t.unix_timestamp_ms_filled >= %s
                            AND t.unix_timestamp_ms_filled <= %s
                            ORDER BY t.unix_timestamp_ms_filled ASC;
                        """).format(
            columns = sql.SQL( ", " ).join( sql.Identifier( name.lower() ) for name in filter_names ),
            view_name_price_change = sql.Identifier( VIEW_NAME_PRICE_CHANGE ),
            view_name_re_share_ext_trade = sql.Identifier( VIEW_NAME_RE_SHARE_EXT_TRADE ),
            view_name_historical_weather_agg = sql.Identifier( VIEW_NAME_HISTORICAL_WEATHER_AGG )
        )
        cursor.execute( query, (region, resolution, start_ms, end_ms) )

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
