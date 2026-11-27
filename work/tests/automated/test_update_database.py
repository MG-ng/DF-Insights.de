"""Tests of the incremental update (updateDatabase.py) with fake SMARD responses and a real PostgreSQL."""
from datetime import date, datetime, timezone

import psycopg2
import pytest

import updateDatabase  # adds psqlDatabase/ to sys.path for the flat imports below
from Helper import FLAG, TABLE_NAME_OPEN_METEO, TABLE_NAME_SMARD
from psqlDatabase.databaseSetup import create_table_with_schema
from smardDataInsertion import BASE_URL, SMARD_FILTERS, buckets_to_refresh, update_recent_smard_data


HOUR_MS = 60 * 60 * 1000
WEEK_MS = 7 * 24 * HOUR_MS
BUCKET_1 = 1_795_388_400_000  # SMARD hour buckets start on Mondays, 23:00 UTC
BUCKET_2 = BUCKET_1 + WEEK_MS
PRICE_FILTER, PRICE_COLUMN = next( item for item in SMARD_FILTERS if item[ 1 ] == "Market_Price_GER_LUX" )


# ---- choosing the buckets ----------------------------------------------------------------------

def test_buckets_start_one_before_the_newest_stored_value():
	buckets = [ 100, 200, 300, 400 ]
	assert buckets_to_refresh( buckets, 250 ) == [ 100, 200, 300, 400 ]
	assert buckets_to_refresh( buckets, 350, overlap_buckets = 0 ) == [ 300, 400 ]
	assert buckets_to_refresh( buckets, 400 ) == [ 300, 400 ]


def test_buckets_handle_unsorted_input_and_old_values():
	assert buckets_to_refresh( [ 300, 100, 200 ], 50 ) == [ 100, 200, 300 ]


def test_no_buckets_without_stored_values():
	assert buckets_to_refresh( [ 100, 200 ], None ) == []
	assert buckets_to_refresh( [], 100 ) == []


# ---- SMARD upsert against PostgreSQL -----------------------------------------------------------

class FakeSmard:
	"""Answers like the SMARD chart_data API: one filter with two hourly buckets, everything else 404."""

	def __init__( self, series ):
		self.series = series  # {bucket timestamp: [[timestamp, value], ...]}
		self.requested = []

	def __call__( self, url, allow_not_found = False ):
		self.requested.append( url )
		if url == f"{BASE_URL}/chart_data/{PRICE_FILTER}/DE/index_hour.json":
			return { "timestamps": sorted( self.series ) }
		for bucket, points in self.series.items():
			if url == f"{BASE_URL}/chart_data/{PRICE_FILTER}/DE/{PRICE_FILTER}_DE_hour_{bucket}.json":
				return { "series": points }
		if allow_not_found:
			return None
		raise AssertionError( f"unexpected request {url}" )


@pytest.fixture
def connection( database ):
	assert create_table_with_schema( database, TABLE_NAME_SMARD )
	conn = psycopg2.connect( **database )
	with conn.cursor() as cursor:
		cursor.execute( f"TRUNCATE {TABLE_NAME_SMARD}" )
	conn.commit()
	yield conn
	conn.rollback()
	with conn.cursor() as cursor:
		cursor.execute( f"TRUNCATE {TABLE_NAME_SMARD}" )
	conn.commit()
	conn.close()


def stored_prices( conn ):
	with conn.cursor() as cursor:
		cursor.execute( f"""SELECT unix_timestamp_ms, is_bucket_timestamp, market_price_ger_lux::float
							FROM {TABLE_NAME_SMARD} WHERE region = 'DE' AND resolution = 'hour'
							ORDER BY unix_timestamp_ms""" )
		return cursor.fetchall()


def seed_price( conn, timestamp, value, is_bucket = False ):
	with conn.cursor() as cursor:
		cursor.execute(
			f"""INSERT INTO {TABLE_NAME_SMARD} (unix_timestamp_ms, is_bucket_timestamp, region, resolution, {PRICE_COLUMN})
				VALUES (%s, %s, 'DE', 'hour', %s)""",
			(timestamp, is_bucket, value),
		)
	conn.commit()


def test_update_adds_new_values_overwrites_revisions_and_ignores_gaps( connection ):
	seed_price( connection, BUCKET_1, 10.0, is_bucket = True )
	seed_price( connection, BUCKET_1 + HOUR_MS, 11.0 )
	fake = FakeSmard( {
		BUCKET_1: [ [ BUCKET_1, 10.0 ], [ BUCKET_1 + HOUR_MS, 11.5 ], [ BUCKET_1 + 2 * HOUR_MS, 12.0 ] ],
		BUCKET_2: [ [ BUCKET_2, 20.0 ], [ BUCKET_2 + HOUR_MS, None ] ],  # not published yet
	} )

	written = update_recent_smard_data( connection, fetch = fake, log = lambda _: None )

	assert written == 4
	assert stored_prices( connection ) == [
		(BUCKET_1, True, 10.0),
		(BUCKET_1 + HOUR_MS, False, 11.5),  # revised by SMARD
		(BUCKET_1 + 2 * HOUR_MS, False, 12.0),
		(BUCKET_2, True, 20.0),  # a new bucket start is marked like in the full import
	]


def test_update_is_idempotent( connection ):
	seed_price( connection, BUCKET_1, 10.0, is_bucket = True )
	fake = FakeSmard( { BUCKET_1: [ [ BUCKET_1, 10.0 ], [ BUCKET_1 + HOUR_MS, 11.0 ] ] } )
	update_recent_smard_data( connection, fetch = fake, log = lambda _: None )
	first = stored_prices( connection )
	update_recent_smard_data( connection, fetch = fake, log = lambda _: None )
	assert stored_prices( connection ) == first


def test_update_skips_old_buckets_and_leaves_other_columns_alone( connection ):
	old_bucket = BUCKET_1 - 3 * WEEK_MS
	seed_price( connection, BUCKET_2, 20.0, is_bucket = True )
	with connection.cursor() as cursor:
		cursor.execute( f"UPDATE {TABLE_NAME_SMARD} SET power_consumption_total = 55000" )
	connection.commit()
	fake = FakeSmard( { old_bucket: [ [ old_bucket, 1.0 ] ], BUCKET_1: [ [ BUCKET_1, 10.0 ] ],
						BUCKET_2: [ [ BUCKET_2, 21.0 ] ] } )

	update_recent_smard_data( connection, fetch = fake, log = lambda _: None )

	assert not any( str( old_bucket ) in url for url in fake.requested )
	assert stored_prices( connection ) == [ (BUCKET_1, True, 10.0), (BUCKET_2, True, 21.0) ]
	with connection.cursor() as cursor:
		cursor.execute( f"SELECT power_consumption_total FROM {TABLE_NAME_SMARD} WHERE unix_timestamp_ms = %s",
						(BUCKET_2,) )
		assert cursor.fetchone()[ 0 ] == 55000


def test_flag_placeholders_do_not_count_as_stored_data( connection ):
	# A bucket row left with the FLAG marker by an interrupted full import is not real data
	seed_price( connection, BUCKET_2, FLAG, is_bucket = True )
	fake = FakeSmard( { BUCKET_1: [ [ BUCKET_1, 10.0 ] ], BUCKET_2: [ [ BUCKET_2, 20.0 ] ] } )
	assert update_recent_smard_data( connection, fetch = fake, log = lambda _: None ) == 0


def test_since_loads_columns_without_data( connection ):
	fake = FakeSmard( { BUCKET_1: [ [ BUCKET_1, 10.0 ], [ BUCKET_1 + HOUR_MS, 11.0 ] ] } )
	since_ms = BUCKET_1 + HOUR_MS
	update_recent_smard_data( connection, fetch = fake, since_ms = since_ms, log = lambda _: None )
	assert stored_prices( connection ) == [ (BUCKET_1 + HOUR_MS, False, 11.0) ]


# ---- weather start dates and the run as a whole ------------------------------------------------

def test_weather_starts_three_days_before_the_newest_complete_hour( connection ):
	with connection.cursor() as cursor:
		cursor.execute( f"DROP TABLE IF EXISTS {TABLE_NAME_OPEN_METEO}" )
		cursor.execute( f"""CREATE TABLE {TABLE_NAME_OPEN_METEO}
							(date timestamptz, wind_speed_100m real, direct_radiation real)""" )
		cursor.execute( f"""INSERT INTO {TABLE_NAME_OPEN_METEO} VALUES
							('2026-11-20 05:00+00', 4.2, 0), ('2026-11-25 05:00+00', NULL, NULL)""" )
	connection.commit()
	try:
		assert updateDatabase.weather_start_date( connection, None ) == date( 2026, 11, 17 )
		assert updateDatabase.weather_start_date( connection, date( 2026, 1, 1 ) ) == date( 2026, 1, 1 )
	finally:
		with connection.cursor() as cursor:
			cursor.execute( f"DROP TABLE {TABLE_NAME_OPEN_METEO}" )
		connection.commit()


def test_only_one_update_runs_at_a_time( connection, capsys ):
	with connection.cursor() as cursor:
		cursor.execute( "SELECT pg_advisory_lock(%s)", (updateDatabase.LOCK_ID,) )
	try:
		assert updateDatabase.main( [ "--only", "smard", "--skip-views" ] ) == 0
		assert "Another update is still running" in capsys.readouterr().out
	finally:
		with connection.cursor() as cursor:
			cursor.execute( "SELECT pg_advisory_unlock(%s)", (updateDatabase.LOCK_ID,) )
		connection.commit()


def test_a_missing_table_fails_the_run( database, monkeypatch, capsys ):
	monkeypatch.setattr( updateDatabase, "TABLE_NAME_OPEN_METEO", "table_that_does_not_exist" )
	assert updateDatabase.main( [ "--only", "weather", "--skip-views" ] ) == 1
	assert "Run databaseSetupAll.py first" in capsys.readouterr().out


def test_forecast_start_date_from_unix_seconds( connection ):
	with connection.cursor() as cursor:
		cursor.execute( "CREATE TEMP TABLE weather_forecasts_data_raw (timestamp_s bigint, model text, temperature_2m real)" )
		newest = int( datetime( 2026, 11, 20, 6, tzinfo = timezone.utc ).timestamp() )
		cursor.execute( "INSERT INTO weather_forecasts_data_raw VALUES (%s, 'icon_eu', 1.5), (%s, 'icon_eu', NULL)",
						(newest, newest + 3600 * 48) )
	assert updateDatabase.forecast_start_date( connection, "icon_eu", None ) == date( 2026, 11, 16 )
	assert updateDatabase.forecast_start_date( connection, "gfs_global", None ) is None


def test_hdf_export_replaces_the_file_atomically( tmp_path ):
	import pandas as pd
	from exportColabData import write_hdf_atomically

	target = tmp_path / "data.h5"
	write_hdf_atomically( pd.DataFrame( { "a": [ 1.0, 2.0 ] } ), target )
	write_hdf_atomically( pd.DataFrame( { "a": [ 3.0 ] } ), target )
	assert pd.read_hdf( target ).to_dict( "list" ) == { "a": [ 3.0 ] }
	assert [ path.name for path in tmp_path.iterdir() ] == [ "data.h5" ]
