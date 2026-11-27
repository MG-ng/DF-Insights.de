import psycopg2
from psycopg2 import sql
import sys

from config import DB_PARAMS
from Helper import VIEW_NAME_RE_SHARE_EXT_TRADE, VIEW_NAME_PRICE_CHANGE, VIEW_NAME_DUNKELFLAUTEN_STATS, \
	VIEW_NAME_HISTORICAL_WEATHER_AGG, VIEW_NAME_WEATHER_FORECASTS_AGG
from psqlDatabase.viewsSQL import dunkelflauten_stats_view_sql, re_share_import_view_sql, price_change_view_sql, \
	historical_weather_agg_view_sql, historical_weather_forecasts_agg_view_sql


def _has_unique_index( cursor, view_name ):
    cursor.execute( """
        SELECT EXISTS (
            SELECT 1
            FROM pg_index idx
            JOIN pg_class relation ON relation.oid = idx.indrelid
            JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = current_schema()
              AND relation.relname = %s
              AND idx.indisunique
              AND idx.indpred IS NULL
        );
    """, (view_name,) )
    return cursor.fetchone()[0]


def create_computed_view( connection_params, computed_view_name, view_sql, concurrently = False ):
    """
    Creates the computed view, assuming smard_data_collection is already populated and filled

    Args:
        connection_params (dict): Database connection parameters
        computed_view_name (str): Name of the materialized view
        view_sql (str): Query used to populate the materialized view
        concurrently (bool): Refresh an existing view with REFRESH ... CONCURRENTLY, so the website
            can keep reading it during the refresh. Needs the unique index created below; without it
            the plain (locking) refresh is used.

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
            refresh_concurrently = concurrently and _has_unique_index( cursor, computed_view_name )
            refresh_view_sql = sql.SQL( "REFRESH MATERIALIZED VIEW {concurrently}{view};" ).format(
                concurrently = sql.SQL( "CONCURRENTLY " if refresh_concurrently else "" ),
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



DUNKELFLAUTEN_THRESHOLDS = [ 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55 ]


def computed_views():
    """(view name, SQL) in build order: the Dunkelflauten stats read the weather aggregates."""
    views = [
        (VIEW_NAME_RE_SHARE_EXT_TRADE, re_share_import_view_sql),
        (VIEW_NAME_PRICE_CHANGE, price_change_view_sql),
        (VIEW_NAME_WEATHER_FORECASTS_AGG, historical_weather_forecasts_agg_view_sql),
        (VIEW_NAME_HISTORICAL_WEATHER_AGG, historical_weather_agg_view_sql),
    ]
    for threshold in DUNKELFLAUTEN_THRESHOLDS:
        views.append( (VIEW_NAME_DUNKELFLAUTEN_STATS + str( int( round( threshold * 100 ) ) ),
                       dunkelflauten_stats_view_sql( threshold )) )
    return views


def create_or_refresh_all_views( connection_params, concurrently = False ):
    """Create missing views and refresh existing ones. Stops at the first failure and returns False."""
    for view_name, view_sql in computed_views():
        if create_computed_view( connection_params, view_name, view_sql, concurrently ):
            print( f"{view_name} creation completed successfully!" )
        else:
            print( f"View {view_name} creation failed!" )
            return False
    return True


if __name__ == "__main__":
    if not create_or_refresh_all_views( DB_PARAMS ):
        sys.exit( 1 )
