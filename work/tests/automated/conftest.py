"""Shared fixtures for the automated tests.

Run from work/:  pytest
The database tests need a PostgreSQL server reachable with the DB_* settings
(see .env.example). Without one they are skipped, unless REQUIRE_DB=1 is set,
as in CI, where a missing database is an error.
"""
import os

import psycopg2
import pytest

from config import DB_PARAMS


@pytest.fixture
def app():
	from app import app as flask_app
	flask_app.config.update( TESTING = True )
	return flask_app


@pytest.fixture
def client( app ):
	return app.test_client()


def _database_available():
	try:
		psycopg2.connect( connect_timeout = 3, **DB_PARAMS ).close()
		return True
	except psycopg2.Error:
		return False


@pytest.fixture(scope = "session")
def database():
	"""Connection parameters of an empty test database. Skips (or fails in CI) without one."""
	if not _database_available():
		message = f"PostgreSQL not reachable at {DB_PARAMS['host']}:{DB_PARAMS['port']}/{DB_PARAMS['database']}"
		if os.getenv( "REQUIRE_DB" ) == "1":
			pytest.fail( message )
		pytest.skip( message )
	return DB_PARAMS
