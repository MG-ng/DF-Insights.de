"""End-to-end test of /api against a real PostgreSQL database with a tiny fixture dataset."""
import psycopg2
import pytest

from Helper import TABLE_NAME_SMARD
from psqlDatabase.databaseSetup import create_table_with_schema


DAY_MS = 24 * 60 * 60 * 1000
START_MS = 1_700_000_000_000 - (1_700_000_000_000 % DAY_MS)  # a UTC midnight in November 2023

# (timestamp, residual load, total consumption) for three days in DE
FIXTURE_ROWS = [ (START_MS + i * DAY_MS, 30000.0 + i, 50000.0 + i) for i in range( 3 ) ]


@pytest.fixture
def smard_table( database ):
	assert create_table_with_schema( database, TABLE_NAME_SMARD )
	with psycopg2.connect( **database ) as conn, conn.cursor() as cursor:
		cursor.execute( f"TRUNCATE {TABLE_NAME_SMARD}" )
		cursor.executemany(
			f"""INSERT INTO {TABLE_NAME_SMARD}
					(unix_timestamp_ms, is_bucket_timestamp, region, resolution,
					 power_consumption_residual_load, power_consumption_total)
				VALUES (%s, true, 'DE', 'day', %s, %s)""",
			FIXTURE_ROWS,
		)
		# A row in another region must not show up
		cursor.execute(
			f"""INSERT INTO {TABLE_NAME_SMARD}
					(unix_timestamp_ms, is_bucket_timestamp, region, resolution, power_consumption_total)
				VALUES (%s, true, 'AT', 'day', 1)""",
			(START_MS,),
		)
	yield
	with psycopg2.connect( **database ) as conn, conn.cursor() as cursor:
		cursor.execute( f"TRUNCATE {TABLE_NAME_SMARD}" )


def test_api_returns_the_fixture_series( client, smard_table ):
	response = client.get( f"/api?region=DE&resolution=day&startTime={START_MS}&endTime={START_MS + 10 * DAY_MS}" )
	assert response.status_code == 200
	body = response.get_json()
	assert body[ "default" ] == { "resolution": "day", "region": "DE" }
	assert body[ "ordering" ][ 3: ] == [ "power_consumption_residual_load", "power_consumption_total" ]
	assert body[ "series" ] == [ [ ts, residual, total ] for ts, residual, total in FIXTURE_ROWS ]


def test_api_respects_the_time_range( client, smard_table ):
	response = client.get( f"/api?region=DE&resolution=day&startTime={START_MS + DAY_MS}&endTime={START_MS + DAY_MS}" )
	assert [ row[ 0 ] for row in response.get_json()[ "series" ] ] == [ START_MS + DAY_MS ]
