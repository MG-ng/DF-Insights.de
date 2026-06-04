import psycopg2
from psycopg2 import sql
from Helper import FLAG


def get_timestamp_buckets( connection_params, table_name, filter_name ):
    global cursor, conn
    try:
        conn = psycopg2.connect( **connection_params )
        cursor = conn.cursor()

        query = sql.SQL("""
            SELECT unix_timestamp_ms, region, resolution
            FROM {table_name}
            WHERE {filter_name} = %s AND IS_BUCKET_TIMESTAMP;
        """).format(
            table_name = sql.Identifier( table_name ),
            filter_name = sql.Identifier( filter_name.lower() )
        )
        cursor.execute( query, (FLAG,) )
        rows = cursor.fetchall()

        column_names = [ desc[ 0 ] for desc in cursor.description ]
        print( f"Found {len( rows )} rows with columns: {column_names} and {filter_name=}" )

        return rows, column_names

    except psycopg2.Error as e:
        print( f"Database error: {e}" )
        return None, None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_all_rows( connection_params, table_name ):
    """
    Basic method: Get all filtered rows using fetchall()
    Good for: Small to medium tables (< 10,000 rows)
    """
    global cursor, conn
    try:
        conn = psycopg2.connect( **connection_params )
        cursor = conn.cursor()

        query = sql.SQL("SELECT * FROM {table_name}").format(
            table_name = sql.Identifier( table_name )
        )
        cursor.execute( query )
        rows = cursor.fetchall()

        column_names = [ desc[ 0 ] for desc in cursor.description ]
        print( f"Found {len( rows )} rows with columns: {column_names}" )

        return rows, column_names

    except psycopg2.Error as e:
        print( f"Database error: {e}" )
        return None, None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


            #and only update one column of a row despite don't knowing the other columns
