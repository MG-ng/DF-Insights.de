import time

import psycopg2
from Helper import (TABLE_NAME_SMARD, DB_PARAMS, FILTER, FilterTranslations, COMPUTED_IDS,
                    VIEW_NAME_RE_SHARE_EXT_TRADE, VIEW_NAME_PRICE_CHANGE)


# Merge SMARD data with computed views
def get_timeseries( region, resolution, filter_ids, start_ms, end_ms ):

    filterIdsComputed = [fId for fId in filter_ids if fId in COMPUTED_IDS]
    filterIdsSmard = [fId for fId in filter_ids if fId not in filterIdsComputed]

    print( f"{filterIdsComputed = } | {filterIdsSmard = }")

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

        cursor.execute( f"SELECT unix_timestamp_ms, region, resolution, {", ".join(filter_names)} "
                        f"FROM {TABLE_NAME_SMARD} "
                        f"WHERE region = '{region}' "
                        f"AND resolution = '{resolution}' "
                        f"AND unix_timestamp_ms >= {start_ms} "
                        f"AND unix_timestamp_ms <= {end_ms}; " )
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
                                   CASE
                                       WHEN pct.unix_timestamp_ms IS NULL THEN rsett.unix_timestamp_ms
                                       ELSE pct.unix_timestamp_ms END AS unix_timestamp_ms_filled,
                                   CASE
                                       WHEN pct.region IS NULL THEN rsett.region
                                       ELSE pct.region END AS region_filled,
                                   CASE
                                       WHEN pct.resolution IS NULL THEN rsett.resolution
                                       ELSE pct.resolution END AS resolution_filled
                                FROM {VIEW_NAME_PRICE_CHANGE} pct
                                         NATURAL FULL JOIN {VIEW_NAME_RE_SHARE_EXT_TRADE} rsett)
                        SELECT t.unix_timestamp_ms_filled, t.region_filled, t.resolution_filled, {", ".join(filter_names)}
                            FROM filled_primary_keys t
                            WHERE region = '{region}'
                            AND resolution = '{resolution}'
                            AND t.unix_timestamp_ms_filled >= {start_ms}
                            AND t.unix_timestamp_ms_filled <= {end_ms}
                            ORDER BY t.unix_timestamp_ms_filled;
                        """)

        rows = cursor.fetchall()

        column_names = [ desc[ 0 ] for desc in cursor.description ]
        print( f"Computed: Found {len( rows )} rows with columns: {column_names}")


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
