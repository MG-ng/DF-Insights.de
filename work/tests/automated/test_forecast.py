"""Tests for the /forecast math and route, with the Open-Meteo API mocked out."""
import pytest
import requests

import app as app_module
from app import average, wind_speed_100m


def test_wind_speed_100m_log_law_lies_between_the_two_heights():
	value = wind_speed_100m( 6.0, 8.0 )
	assert 6.0 < value < 8.0


def test_wind_speed_100m_equal_speeds():
	assert wind_speed_100m( 5.0, 5.0 ) == pytest.approx( 5.0 )


@pytest.mark.parametrize( "w80, w120, expected", [ (0.0, 4.0, 2.0), (3.0, 0.0, 1.5), (0.0, 0.0, 0.0) ] )
def test_wind_speed_100m_calm_air_falls_back_to_the_mean( w80, w120, expected ):
	assert wind_speed_100m( w80, w120 ) == pytest.approx( expected )


@pytest.mark.parametrize( "w80, w120", [ (None, 4.0), (4.0, None), (None, None) ] )
def test_wind_speed_100m_missing_value_stays_missing( w80, w120 ):
	assert wind_speed_100m( w80, w120 ) is None


def test_average_ignores_none():
	assert average( [ 1.0, None, 3.0 ] ) == 2.0
	assert average( [ None, None ] ) is None
	assert average( [] ) is None


LATITUDES = [ 54, 54, 54, 52, 52, 52, 50, 50, 50, 48, 48, 48 ]


def open_meteo_response( wind = 5.0, direct = 100.0, diffuse = 50.0, hours = (0, 3600) ):
	"""Shape of the Open-Meteo multi-location response: one entry per location."""
	n = len( hours )
	return [
		{ "latitude": lat, "hourly": {
			"time": list( hours ),
			"wind_speed_80m": [ wind ] * n,
			"wind_speed_120m": [ wind ] * n,
			"direct_radiation": [ direct ] * n,
			"diffuse_radiation": [ diffuse ] * n,
		} }
		for lat in LATITUDES
	]


class FakeResponse:
	def __init__( self, payload, status = 200 ):
		self.payload, self.status = payload, status

	def raise_for_status( self ):
		if self.status >= 400:
			raise requests.HTTPError( f"{self.status}" )

	def json( self ):
		return self.payload


@pytest.fixture
def mock_open_meteo( monkeypatch ):
	calls = []

	def install( response ):
		def fake_get( url, **kwargs ):
			calls.append( kwargs )
			if isinstance( response, Exception ):
				raise response
			return response
		monkeypatch.setattr( app_module.requests, "get", fake_get )
		return calls

	return install


def test_forecast_computes_repi( client, mock_open_meteo ):
	calls = mock_open_meteo( FakeResponse( open_meteo_response( wind = 5.0, direct = 100.0, diffuse = 50.0 ) ) )
	response = client.get( "/forecast" )
	assert response.status_code == 200
	# min(5, 11)^3 + 100*2 + 50*2 = 125 + 300
	assert response.get_json() == { "REPIs": { "0": 425.0, "3600": 425.0 } }
	assert calls[0].get( "timeout" ), "the Open-Meteo request must have a timeout"


def test_forecast_caps_wind_at_11( client, mock_open_meteo ):
	mock_open_meteo( FakeResponse( open_meteo_response( wind = 20.0, direct = 0.0, diffuse = 0.0, hours = (0,) ) ) )
	assert client.get( "/forecast" ).get_json() == { "REPIs": { "0": 1331.0 } }


def test_forecast_handles_calm_air( client, mock_open_meteo ):
	mock_open_meteo( FakeResponse( open_meteo_response( wind = 0.0, hours = (0,) ) ) )
	response = client.get( "/forecast" )
	assert response.status_code == 200
	assert response.get_json() == { "REPIs": { "0": 300.0 } }


def test_forecast_skips_hours_without_data( client, mock_open_meteo ):
	payload = open_meteo_response( hours = (0, 3600) )
	for location in payload:
		location[ "hourly" ][ "direct_radiation" ][ 1 ] = None
	mock_open_meteo( FakeResponse( payload ) )
	assert list( client.get( "/forecast" ).get_json()[ "REPIs" ] ) == [ "0" ]


@pytest.mark.parametrize( "response", [
	requests.ConnectionError( "offline" ),
	requests.Timeout( "slow" ),
	FakeResponse( {}, status = 503 ),
	FakeResponse( [ { "unexpected": True } ] ),
] )
def test_forecast_upstream_problems_return_502( client, mock_open_meteo, response ):
	mock_open_meteo( response )
	assert client.get( "/forecast" ).status_code == 502
