import psycopg2
from psycopg2 import sql

from Helper import DB_PARAMS, VIEW_NAME_RE_SHARE_EXT_TRADE


def get_dunkelflaute_matches( region, resolution, max_share, min_duration_ms, start_ms, end_ms ):
    conn, cursor, rows, column_names = [None] * 4
    try:
        conn = psycopg2.connect( **DB_PARAMS )
        cursor = conn.cursor()

        query = sql.SQL("""
			WITH share_categories as (  -- TODO: FIX 2 hour timezone shift
				SELECT t.unix_timestamp_ms, t.region, t.resolution, t.share_of_renewable_energies_computed,
					   CASE WHEN t.share_of_renewable_energies_computed <= %s THEN 'LOW'
							ELSE 'HIGH' END as current_share
				FROM {view_name_re_share_ext_trade} t
				WHERE region = %s AND resolution = %s
				AND unix_timestamp_ms >= %s AND unix_timestamp_ms <= %s
			), events as (
				SELECT unix_timestamp_ms, region, resolution, share_of_renewable_energies_computed, current_share,
							 (CASE  /* Guaranteed that a START is at the beginning of a period but not that an END is at the finish */
								 WHEN (LAG(current_share, 1, 'HIGH') OVER w = 'HIGH' AND current_share = 'LOW') THEN 'START'
								 WHEN (LAG(current_share, 1, 'HIGH') OVER w = 'LOW' AND current_share = 'HIGH') THEN 'END'
								 ELSE 'nothing' END) as event_bucket
				FROM share_categories
				WINDOW w as (ORDER BY unix_timestamp_ms ASC)
			), cleaned as (
				SELECT * FROM events WHERE event_bucket != 'nothing'
			), start_end as (
				SELECT *, LEAD( unix_timestamp_ms, 1, 
						  (select unix_timestamp_ms from cleaned order by unix_timestamp_ms desc limit 1))
					OVER (ORDER BY unix_timestamp_ms ASC) as end_time
				FROM cleaned
			), matches as (
				SELECT *
				FROM start_end
				WHERE end_time - unix_timestamp_ms >= %s AND event_bucket = 'START'
			) SELECT unix_timestamp_ms as start_time, region, resolution, end_time
			FROM matches;
			""" ).format( view_name_re_share_ext_trade = sql.Identifier( VIEW_NAME_RE_SHARE_EXT_TRADE ) )
        cursor.execute( query, (max_share, region, resolution, start_ms, end_ms, min_duration_ms) )
        rows = cursor.fetchall()

        column_names = [ desc[ 0 ] for desc in cursor.description ]
        print( f"Computed: Found {len( rows )} rows with columns: {column_names}")

    except psycopg2.Error as e:
        print( f"Database error: {e}" )
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
    return rows, column_names


def get_dunkelflaute_timeseries( region, resolution, max_share, min_duration_ms, start_ms, end_ms ):
    conn, cursor, rows, column_names = [None] * 4
    try:
        conn = psycopg2.connect( **DB_PARAMS )
        cursor = conn.cursor()

        query = sql.SQL("""
			WITH share_categories as (
				SELECT t.unix_timestamp_ms, t.region, t.resolution, t.share_of_renewable_energies_computed,
					   CASE WHEN t.share_of_renewable_energies_computed <= %s THEN 'LOW'
							ELSE 'HIGH' END as current_share
				FROM {view_name_re_share_ext_trade} t
				WHERE region = %s AND resolution = %s
				AND unix_timestamp_ms >= %s AND unix_timestamp_ms <= %s
			), events as (
				SELECT unix_timestamp_ms, region, resolution, share_of_renewable_energies_computed, current_share,
							 (CASE  /* Guaranteed that a START is at the beginning of a period but not that an END is at the finish */
								 WHEN (LAG(current_share, 1, 'HIGH') OVER w = 'HIGH' AND current_share = 'LOW') THEN 'START'
								 WHEN (LAG(current_share, 1, 'HIGH') OVER w = 'LOW' AND current_share = 'HIGH') THEN 'END'
								 ELSE 'nothing' END) as event_bucket
				FROM share_categories
				WINDOW w as (ORDER BY unix_timestamp_ms ASC)
			), cleaned as (
				SELECT * FROM events WHERE event_bucket != 'nothing'
			), start_end as (
				SELECT *, LEAD( unix_timestamp_ms, 1, (select unix_timestamp_ms from cleaned order by unix_timestamp_ms desc limit 1) )
					OVER (ORDER BY unix_timestamp_ms ASC) as end_time
				FROM cleaned
			), matches as (
				SELECT *
				FROM start_end
				WHERE end_time - unix_timestamp_ms >= %s AND event_bucket = 'START'
			), dunkelflauten as (
                SELECT unix_timestamp_ms AS start_time, region, resolution, end_time
                    FROM matches
            ) SELECT series.unix_timestamp_ms, -- series.region, series.resolution,
                     count(df.start_time) as occurrences_in_last_rolling_year,
                     sum(df.end_time - df.start_time)::BIGINT/1000/60/60/24 as total_days_in_last_rolling_year
			FROM {view_name_re_share_ext_trade} series
			JOIN dunkelflauten df ON (series.unix_timestamp_ms - 1000 *60 *60 *24 *365::BIGINT < df.end_time
                                  AND series.unix_timestamp_ms >= df.start_time)
            WHERE series.region=%s
				AND series.resolution='day'  -- To keep the answer fast
				AND series.unix_timestamp_ms BETWEEN %s AND %s
			GROUP BY series.unix_timestamp_ms, series.region, series.resolution
			ORDER BY series.unix_timestamp_ms ASC
			OFFSET 365;
			""" ).format( view_name_re_share_ext_trade = sql.Identifier( VIEW_NAME_RE_SHARE_EXT_TRADE ) )
        cursor.execute( query, (max_share, region, resolution, start_ms, end_ms, min_duration_ms, region, start_ms, end_ms) )
        rows = cursor.fetchall()

        column_names = [ desc[ 0 ] for desc in cursor.description ]

    except psycopg2.Error as e:
        print( f"Database error: {e}" )
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
    return rows, column_names


def getEnrichedDunkelflauten( tableName ):
    conn, cursor, rows, column_names = [None] * 4
    try:
        conn = psycopg2.connect( **DB_PARAMS )
        cursor = conn.cursor()

        query = sql.SQL("""
			SELECT *
			FROM {table_name};
			""" ).format( table_name = sql.Identifier( tableName ) )
        cursor.execute( query )
        rows = cursor.fetchall()

        column_names = [ desc[ 0 ] for desc in cursor.description ]
        print( f"Computed: Found {len( rows )} rows with columns: {column_names}")

    except psycopg2.Error as e:
        print( f"Database error: {e}" )
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
    return rows, column_names



if __name__ == '__main__':
    unix_duration = 1000 *60 *60 *24
    threshold = 0.1
    region = 'DE'
    resolution = 'day'
    start_ms = 1000000000000
    end_ms = 2000000000000
    print( get_dunkelflaute_matches( region, resolution, threshold, unix_duration, start_ms, end_ms ) )
