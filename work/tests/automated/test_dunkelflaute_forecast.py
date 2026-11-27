"""Tests for the Dunkelflaute forecast (work/prediction/): features, energy model, live outlook and routes.
The Open-Meteo ensemble API is mocked; model.json and backtest.json are the committed, trained files."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest
import requests

from prediction import live
from prediction.calendar_de import calendar_features, easter_sunday
from prediction.features import POINTS, hourly_to_daily_features, wind_capacity_factor
from prediction.model import load_model, predict_components, probability_below


def test_power_curve():
	cf = wind_capacity_factor( [ 0.0, 2.9, 3.0, 7.0, 11.5, 20.0, 25.0, np.nan ] )
	assert cf[ 0 ] == cf[ 1 ] == cf[ 2 ] == 0.0
	assert 0 < cf[ 3 ] < 0.3
	assert cf[ 4 ] == cf[ 5 ] == 1.0
	assert cf[ 6 ] == 0.0  # storm shutdown
	assert np.isnan( cf[ 7 ] )


def test_daily_features_need_most_hours():
	index = pd.date_range( "2025-01-01", periods = 30, freq = "h", tz = "Europe/Berlin" )
	daily = hourly_to_daily_features( pd.Series( 8.0, index ), pd.Series( 50.0, index ), pd.Series( 2.0, index ) )
	assert list( daily.index ) == [ dt.date( 2025, 1, 1 ) ]  # 6 hours of Jan 2 are not enough
	assert daily[ "ws" ].iloc[ 0 ] == 8.0


@pytest.mark.parametrize( "year, expected", [ ( 2024, dt.date( 2024, 3, 31 ) ), ( 2025, dt.date( 2025, 4, 20 ) ),
										   ( 2026, dt.date( 2026, 4, 5 ) ) ] )
def test_easter( year, expected ):
	assert easter_sunday( year ) == expected


def test_calendar_marks_holidays_and_weekends():
	cal = calendar_features( [ "2025-12-25", "2025-12-27", "2025-12-28", "2025-12-29" ] )
	assert cal[ "holiday" ].tolist() == [ 1.0, 0.0, 0.0, 0.0 ]
	assert cal[ "sat" ].tolist() == [ 0, 1, 0, 0 ] and cal[ "sun" ].tolist() == [ 0, 0, 1, 0 ]
	assert cal[ "christmas" ].tolist() == [ 1, 1, 1, 1 ]


def weather( ws, ghi, t = 2.0, days = 3, start = "2026-01-12" ):
	index = pd.date_range( start, periods = days, freq = "D" )
	columns = {}
	for point in POINTS:
		columns[ f"{point['id']}_ws" ] = ws
		columns[ f"{point['id']}_cf" ] = float( wind_capacity_factor( [ ws ] )[ 0 ] )
		columns[ f"{point['id']}_ghi" ] = ghi
		columns[ f"{point['id']}_t" ] = t
	return pd.DataFrame( columns, index = index )


def test_calm_dark_winter_days_have_a_low_share():
	model = load_model()
	calm = predict_components( model, weather( ws = 3.5, ghi = 20 ) )
	windy = predict_components( model, weather( ws = 12.0, ghi = 20 ) )
	assert ( calm[ "re_share" ] < 0.3 ).all()
	assert ( windy[ "re_share" ] > 0.6 ).all()
	assert ( calm[ "load" ] > 1.0e6 ).all()  # MWh per day, Germany uses over 1 TWh a day


def test_probability_is_monotonic_and_bounded():
	shares = np.array( [ 0.1, 0.3, 0.35, 0.4, 0.8 ] )
	p = probability_below( shares, 0.35, 0.25 )
	assert np.all( np.diff( p ) < 0 )
	assert np.all( ( p >= 0 ) & ( p <= 1 ) )
	assert p[ 2 ] == pytest.approx( 0.5 )


def ensemble_payload( params, members = 3, wind = 5.0 ):
	"""Shape of the Open-Meteo ensemble response for a multi-location request."""
	lats = params[ "latitude" ].split( "," )
	start = pd.Timestamp.now( tz = "Europe/Berlin" ).normalize()
	times = [ int( ts.timestamp() ) for ts in pd.date_range( start, periods = 24 * 4, freq = "h" ) ]
	variables = params[ "hourly" ].split( "," )
	entries = []
	for _ in lats:
		hourly = { "time": times }
		for var in variables:
			value = { "wind_speed_100m": wind, "shortwave_radiation": 40.0, "temperature_2m": 3.0,
					  "pressure_msl": 1020.0 }[ var ]
			hourly[ var ] = [ value ] * len( times )
			for m in range( 1, members ):
				hourly[ f"{var}_member{m:02d}" ] = [ value + 0.5 * m ] * len( times )
		entries.append( { "hourly": hourly } )
	return entries


class FakeResponse:
	def __init__( self, payload ):
		self.payload = payload

	def raise_for_status( self ):
		pass

	def json( self ):
		return self.payload


def test_build_outlook_with_mocked_ensembles( monkeypatch ):
	monkeypatch.setattr( live.requests, "get", lambda url, params, timeout: FakeResponse( ensemble_payload( params ) ) )
	outlook = live.build_outlook()
	assert len( outlook[ "ensembles" ] ) == 3
	assert outlook[ "days" ], "expected at least one forecast day"
	for day in outlook[ "days" ]:
		assert day[ "members" ] == 9
		assert all( 0 <= p <= 1 for p in day[ "probability" ].values() )
		assert day[ "share" ][ "p10" ] <= day[ "share" ][ "p50" ] <= day[ "share" ][ "p90" ]
	# lower thresholds can only be less likely
	probabilities = [ outlook[ "days" ][ 0 ][ "probability" ][ str( t ) ] for t in outlook[ "thresholds" ] ]
	assert probabilities == sorted( probabilities )
	if outlook[ "regimes" ]:
		for day in outlook[ "regimes" ][ "days" ]:
			assert sum( day[ "probabilities" ] ) == pytest.approx( 1.0, abs = 0.01 )


def test_build_outlook_survives_one_failing_ensemble( monkeypatch ):
	def fake_get( url, params, timeout ):
		if params[ "models" ] == "gfs05":
			raise requests.ConnectionError( "down" )
		return FakeResponse( ensemble_payload( params ) )
	monkeypatch.setattr( live.requests, "get", fake_get )
	monkeypatch.setattr( live.time, "sleep", lambda seconds: None )
	assert [ e[ "id" ] for e in live.build_outlook()[ "ensembles" ] ] == [ "ecmwf_ifs025", "ecmwf_aifs025" ]


def test_outlook_route( client, monkeypatch ):
	monkeypatch.setattr( live, "cached_outlook", lambda: { "days": [], "thresholds": [ 0.35 ] } )
	response = client.get( "/dunkelflaute-outlook" )
	assert response.status_code == 200
	assert response.get_json()[ "thresholds" ] == [ 0.35 ]


def test_outlook_route_reports_upstream_failure( client, monkeypatch ):
	def broken():
		raise RuntimeError( "no ensemble data" )
	monkeypatch.setattr( live, "cached_outlook", broken )
	assert client.get( "/dunkelflaute-outlook" ).status_code == 502


def test_backtest_route( client ):
	response = client.get( "/dunkelflaute-backtest" )
	assert response.status_code == 200
	data = response.get_json()
	assert "energy_model_era5" in data and "nwp_leads" in data


def test_prediction_page_has_the_outlook( client ):
	page = client.get( "/prediction" ).get_data( as_text = True )
	assert 'id="df-outlook-chart"' in page
	assert "js/dunkelflauteOutlook.js" in page


def test_cached_outlook_reuses_and_falls_back( monkeypatch, tmp_path ):
	monkeypatch.setattr( live, "CACHE_FILE", tmp_path / "outlook.json" )
	monkeypatch.setattr( live, "_cache", { "time": 0.0, "value": None } )
	calls = []

	def build():
		calls.append( 1 )
		return { "days": [ len( calls ) ] }
	monkeypatch.setattr( live, "build_outlook", build )
	assert live.cached_outlook() == { "days": [ 1 ] }
	assert live.cached_outlook() == { "days": [ 1 ] } and len( calls ) == 1  # cached
	assert ( tmp_path / "outlook.json" ).exists()  # shared with the other workers

	live._cache[ "time" ] -= live.CACHE_SECONDS + 1  # expired: rebuild fails, the last good result is served
	monkeypatch.setattr( live, "_read_cache_file", lambda: ( 0.0, None ) )

	def broken():
		raise RuntimeError( "no ensemble data" )
	monkeypatch.setattr( live, "build_outlook", broken )
	assert live.cached_outlook() == { "days": [ 1 ] }
