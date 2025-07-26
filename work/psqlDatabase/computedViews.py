import psycopg2
import sys

from Helper import DB_PARAMS, VIEW_NAME_RE_SHARE_EXT_TRADE, VIEW_NAME_PRICE_CHANGE
from viewsSQL import re_share_import_view_sql, price_change_view_sql



def create_computed_view( connection_params, computed_view_name, view_sql ):
    """
    Creates the computed view, assuming smard_data_collection is already populated and filled

    Args:
        connection_params (dict): Database connection parameters
        table_name (str): Name of the table to create

    Returns:
        bool: True if table creation was successful, False otherwise
    """
    conn = None
    cursor = None
    try:
        # Connect to PostgreSQL
        conn = psycopg2.connect( **connection_params )
        cursor = conn.cursor()

        create_view_sql = f"""
            CREATE MATERIALIZED VIEW IF NOT EXISTS {computed_view_name} 
            AS ( {view_sql} )
            WITH DATA;
        """ # no loading and querying with "no data" possible yet || MATERIALIZED prevent proper Code coloring by PyCharm :/

        # https://www.postgresql.org/docs/current/sql-creatematerializedview.html
        # CREATE MATERIALIZED VIEW defines a materialized view of a query.
        # The query is executed and used to populate the view at the time the command is issued (unless WITH NO DATA is used)
        # and may be refreshed later using REFRESH MATERIALIZED VIEW.

        # REFRESH MATERIALIZED VIEW computedData WITH NO DATA;
        # Frees the storage and leaves it in an unscannable state


        print(create_view_sql)
        cursor.execute( create_view_sql )
        conn.commit()
        print( "Created View successfully" )
        cursor.execute( f"""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_{computed_view_name}_unique
            ON {computed_view_name} (unix_timestamp_ms, region, resolution);
        """ )
        conn.commit()
        print( "Created unique index on View successfully" )

        # CONCURRENTLY resulted in: CONCURRENTLY cannot be used when the materialized view is not populated
        # cursor.execute( f"""
        #     REFRESH MATERIALIZED VIEW {computed_view_name} WITH DATA;
        # """ )
        # conn.commit()
        # print( "Filled Materialized View successfully" )
        #
        # print( f"View '{computed_view_name}' created successfully." )

        return True

    except psycopg2.Error as e:
        if "already exists" in str( e ):
            print( f"View '{computed_view_name}' already exists." )
        else:
            print( f"Database error during table creation: {e}" )
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        print( f"Unexpected error during table creation: {e}" )
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":

    for view_name, sql in [(VIEW_NAME_RE_SHARE_EXT_TRADE, re_share_import_view_sql),
                      [VIEW_NAME_PRICE_CHANGE, price_change_view_sql]]:

        if create_computed_view( DB_PARAMS, view_name, sql ):
            print( f"{view_name} creation completed successfully!" )

        else:
            print( "View creation failed!" )
            sys.exit( 1 )
