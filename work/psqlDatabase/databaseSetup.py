import psycopg2
from psycopg2.extras import execute_batch
import sys

from config import DB_PARAMS
from Helper import FilterTranslations, TABLE_NAME_SMARD, FILTER, OTHER_THAN_SMARD_FILTER_IDs


allCols = list( FilterTranslations.values() )
numeric_columns = [ col for col in allCols if FILTER[FilterTranslations.inverse[col]] not in OTHER_THAN_SMARD_FILTER_IDs ]
# OTHER_THAN_SMARD_FILTER_IDs get inserted by computed by view SQL


def create_table_with_schema( connection_params, table_name ):
    """
    Creates a PostgreSQL table with predefined schema including ENUM types.

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

        # Table existence will be handled by CREATE TABLE error

        # Create ENUM types first
        cursor.execute( """
            DO $$ BEGIN
                CREATE TYPE region_type AS ENUM ('DE', 'AT', 'LU', 'DE-LU', 'DE-AT-LU', '50Hertz', 'Amprion', 'TenneT', 'TransnetBW', 'APG', 'Creos');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """ )

        cursor.execute( """
            DO $$ BEGIN
                CREATE TYPE resolution_type AS ENUM ('hour', 'quarterhour', 'day', 'week', 'month', 'year');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """ )

        # Create table with appropriate data types
        numeric_cols_sql = ",\n    ".join( [ f"{col} DECIMAL(11,2)" for col in numeric_columns ] )

        create_table_sql = f"""
        CREATE TABLE {table_name} (
            unix_timestamp_ms BIGINT,
            is_bucket_timestamp BOOLEAN,
            region region_type,
            resolution resolution_type,
            {numeric_cols_sql},
            PRIMARY KEY (unix_timestamp_ms, region, resolution)
        );
        """

        print(create_table_sql)
        cursor.execute( create_table_sql )
        conn.commit()
        print( f"Table '{table_name}' created successfully." )

        return True

    except psycopg2.Error as e:
        if "already exists" in str( e ):
            print( f"Table '{table_name}' already exists." )
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


def insert_optional_data_in_batches( connection_params, table_name, data_rows, data_column, batch_size = 1000 ):
    """
    Inserts data into an existing PostgreSQL table in batches for optimal performance.

    Args:
        connection_params (dict): Database connection parameters
        table_name (str): Name of the existing table to insert data into
        data_rows (list): List of tuples containing data to insert
        batch_size (int): Number of rows to insert per batch (default: 1000)

    Returns:
        bool: True if data insertion was successful, False otherwise
    """
    conn = None
    cursor = None
    try:
        # Connect to PostgreSQL
        conn = psycopg2.connect( **connection_params )
        cursor = conn.cursor()

        # Prepare insert statement
        placeholders = ", ".join( [ "%s" ] * (2 + 2 + 37) )  # timestamp + bucket_Bool + region + resolution + 37 numeric
        insert_sql = f"""
        INSERT INTO {table_name} (unix_timestamp_ms, is_bucket_timestamp, region, resolution, {', '.join( numeric_columns )})
        VALUES ({placeholders})
        ON CONFLICT (unix_timestamp_ms, region, resolution) 
        DO UPDATE SET 
            {data_column} = COALESCE(EXCLUDED.{data_column}, {table_name}.{data_column});
        """

        # Insert data in batches for better performance
        total_rows = len( data_rows )

        for i in range( 0, total_rows, batch_size ):
            batch = data_rows[ i:i + batch_size ]
            execute_batch( cursor, insert_sql, batch, page_size = batch_size )
            print( f"Inserted batch {i // batch_size + 1}: {len( batch )} rows - { data_column = } - { data_rows[0] = }" )

        conn.commit()
        print( f"Successfully inserted {total_rows} rows into '{table_name}'" )

        return True

    except psycopg2.Error as e:
        if "does not exist" in str( e ) or "relation" in str( e ):
            print( f"Table '{table_name}' does not exist. Please create it first." )
        else:
            print( f"Database error during data insertion: {e}" )
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        print( f"Unexpected error during data insertion: {e}" )
        print( f"{insert_sql = }" )
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Example usage
if __name__ == "__main__":

    # Example data (replace with your actual data)
    # Each row should have: unix_timestamp_ms + region + resolution + 37 numeric values
    sample_data = [
        # (unix_timestamp_ms, is_bucket_timestamp, region, resolution, filter-values)
        (0, False, 'DE', 'hour', *[ None ] * 37),  # Fill the remaining 37 columns with None (NULL)
    ]

    # Step 1: Create the table
    if create_table_with_schema( DB_PARAMS, TABLE_NAME_SMARD ):
        print( "Table creation completed successfully!" )

        # Step 2: Insert the sample data
        if insert_optional_data_in_batches( DB_PARAMS, TABLE_NAME_SMARD, sample_data, "unix_timestamp_ms" ):
            print( "Data insertion completed successfully!" )
            print( "Operation completed successfully!" )
        else:
            print( "Data insertion failed!" )
            sys.exit( 1 )
    else:
        print( "Table creation failed!" )
        sys.exit( 1 )
