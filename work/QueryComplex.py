import psycopg2
from Helper import TABLE_NAME, DB_PARAMS


# Keep the FLAGS in the database in mind
# TODO: Add Timestamps Filtering
# TODO: Fully Support different Regions (but current focus is on Germany)
def get_smard_timeseries( resolution, filter_names ):
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect( **DB_PARAMS )
        cursor = conn.cursor()

        cursor.execute( f"SELECT unix_timestamp_ms, region, resolution, {", ".join(filter_names)} FROM {TABLE_NAME} "
                        f"WHERE resolution = '{resolution}' " )
        rows = cursor.fetchall()

        column_names = [ desc[ 0 ] for desc in cursor.description ]
        # print( f"Found {len( rows )} rows with columns: {column_names}" )

        return rows, column_names

    except psycopg2.Error as e:
        print( f"Database error: {e}" )
        return None, None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
