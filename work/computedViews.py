import psycopg2
from psycopg2 import sql
import sys

from config import DB_PARAMS
from Helper import VIEW_NAME_RE_SHARE_EXT_TRADE, VIEW_NAME_PRICE_CHANGE, VIEW_NAME_DUNKELFLAUTEN_STATS, \
	VIEW_NAME_HISTORICAL_WEATHER_AGG, VIEW_NAME_WEATHER_FORECASTS_AGG
from psqlDatabase.viewsSQL import dunkelflauten_stats_view_sql, re_share_import_view_sql, price_change_view_sql, \
	historical_weather_agg_view_sql, historical_weather_forecasts_agg_view_sql


def create_computed_view( connection_params, computed_view_name, view_sql ):
    """
    Creates the computed view, assuming smard_data_collection is already populated and filled

    Args:
        connection_params (dict): Database connection parameters
        computed_view_name (str): Name of the materialized view
        view_sql (str): Query used to populate the materialized view

    Returns:
        bool: True if creation or refresh was successful, False otherwise
    """
    conn = None
    cursor = None
    try:
        # Connect to PostgreSQL
        conn = psycopg2.connect( **connection_params )
        cursor = conn.cursor()

        cursor.execute( """
            SELECT EXISTS (
                SELECT 1
                FROM pg_matviews
                WHERE schemaname = current_schema()
                  AND matviewname = %s
            );
        """, (computed_view_name,) )
        view_exists = cursor.fetchone()[0]

        if view_exists:
            refresh_view_sql = sql.SQL( "REFRESH MATERIALIZED VIEW {view};" ).format(
                view = sql.Identifier( computed_view_name )
            )
            print( refresh_view_sql.as_string( conn ) )
            cursor.execute( refresh_view_sql )
        else:
            create_view_sql = sql.SQL( """
                CREATE MATERIALIZED VIEW {view}
                AS ( {view_query} )
                WITH DATA;
            """ ).format(
                view = sql.Identifier( computed_view_name ),
                view_query = sql.SQL( view_sql )
            )
            print( create_view_sql.as_string( conn ) )
            cursor.execute( create_view_sql )

        conn.commit()
        print( "Materialized view is populated." )

        cursor.execute( """
            SELECT attribute.attname
            FROM pg_attribute attribute
            JOIN pg_class relation ON relation.oid = attribute.attrelid
            JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = current_schema()
              AND relation.relname = %s
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped;
        """, (computed_view_name,) )
        view_columns = { row[0] for row in cursor.fetchall() }

        index_candidates = [
            ("unix_timestamp_ms", "region", "resolution"),
            ("start_time", "end_time"),
            ("timestamp_s", "model", "temporal_resolution"),
            ("date", "resolution"),
        ]
        index_columns = next(
            (columns for columns in index_candidates if set(columns).issubset(view_columns)),
            None,
        )

        if index_columns:
            create_index_sql = sql.SQL( """
                CREATE UNIQUE INDEX IF NOT EXISTS {index}
                ON {view} ({columns});
            """ ).format(
                index = sql.Identifier( f"idx_{computed_view_name}_unique" ),
                view = sql.Identifier( computed_view_name ),
                columns = sql.SQL( ", " ).join( sql.Identifier( column ) for column in index_columns )
            )
            cursor.execute( create_index_sql )
            conn.commit()
            print( f"Unique index uses columns: {', '.join(index_columns)}" )
        else:
            print( f"No suitable unique index columns found for {computed_view_name}." )

        return True

    except psycopg2.Error as e:
        print( f"Database error while preparing materialized view '{computed_view_name}': {e}" )
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        print( f"Unexpected error while preparing materialized view '{computed_view_name}': {e}" )
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
                           [VIEW_NAME_PRICE_CHANGE, price_change_view_sql],
                           [VIEW_NAME_WEATHER_FORECASTS_AGG, historical_weather_forecasts_agg_view_sql],
                           [VIEW_NAME_HISTORICAL_WEATHER_AGG, historical_weather_agg_view_sql],
                           [VIEW_NAME_DUNKELFLAUTEN_STATS, None]]:  # important ordering: stats should use weather_agg

        if sql is None:
            if view_name == VIEW_NAME_DUNKELFLAUTEN_STATS:
                for threshold in [ 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55 ]:

                    sql = dunkelflauten_stats_view_sql(threshold)
                    currentViewName = view_name + str(int(round( threshold*100 )))
                    if create_computed_view( DB_PARAMS, currentViewName, sql ):
                        print( f"{currentViewName} creation completed successfully!" )
                    else:
                        print( f"View {currentViewName} creation failed!" )
                        sys.exit( 1 )

        else:
            if create_computed_view( DB_PARAMS, view_name, sql ):
                print( f"{view_name} creation completed successfully!" )
            else:
                print( "View creation failed!" )
                sys.exit( 1 )
