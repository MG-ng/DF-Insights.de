"""Download the training and backtest data for the Dunkelflaute forecast model.

Writes compact daily CSV files to work/prediction/data/ (one row per day, Europe/Berlin days):

  smard_daily.csv      SMARD generation, load and price (actuals) plus the TSOs' day-ahead forecasts
  weather_daily.csv    ERA5 reanalysis (Open-Meteo archive) at the model's grid points:
                       wind capacity factors computed hourly from 100 m wind, solar radiation, temperature
  mslp_daily.csv       ERA5 mean sea level pressure on a coarse Euro-Atlantic grid (for weather regimes)
  forecast_daily.csv   archived NWP forecasts (Open-Meteo previous-runs API) for lead days 1..7,
                       turned into the same daily features as weather_daily.csv (honest out-of-sample skill)

Run from work/:  python -m prediction.fetch_training_data [--only smard,weather,mslp,forecast]
Needs internet access to www.smard.de and the Open-Meteo APIs. Takes 10 to 40 minutes, mostly waiting
for Open-Meteo's free-tier rate limits.
"""
import argparse
import datetime as dt
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

if __package__ in (None, ""):
	sys.path.insert( 0, str( Path( __file__ ).resolve().parent.parent ) )

from prediction.features import POINTS, MSLP_GRID, hourly_to_daily_features  # noqa: E402

DATA_DIR = Path( __file__ ).resolve().parent / "data"
TZ = "Europe/Berlin"
START = dt.date( 2015, 1, 5 )

SMARD = "https://www.smard.de/app/chart_data"
SMARD_FILTERS = {
	"wind_onshore": 4067,
	"wind_offshore": 1225,
	"pv": 4068,
	"hydro": 1226,
	"biomass": 4066,
	"other_renewables": 1228,
	"pumped_storage_generation": 4070,
	"pumped_storage_consumption": 4387,
	"load": 410,
	"residual_load": 4359,
	"price": 4169,
	"forecast_onshore": 123,
	"forecast_offshore": 3791,
	"forecast_pv": 125,
	"forecast_load": 411,
	"forecast_residual_load": 4362,
}

session = requests.Session()
session.headers[ "User-Agent" ] = "df-insights-forecast-research/1.0"


def get_json( url, params = None, tries = 8 ):
	for attempt in range( tries ):
		try:
			response = session.get( url, params = params, timeout = 120 )
		except requests.RequestException as error:
			print( f"  network error {error!r}, retry {attempt + 1}", flush = True )
			time.sleep( 5 * ( attempt + 1 ) )
			continue
		if response.status_code == 404:
			return None
		if response.status_code == 429:  # Open-Meteo rate limit (per minute, hour or day)
			wait = 65 if attempt < 3 else 600
			print( f"  429 rate limited: {response.text[:200]} -> sleeping {wait}s", flush = True )
			time.sleep( wait )
			continue
		if response.status_code >= 500:
			time.sleep( 10 * ( attempt + 1 ) )
			continue
		if response.status_code >= 400:
			print( f"  HTTP {response.status_code}: {response.text[:300]}", flush = True )
			return None
		return response.json()
	raise RuntimeError( f"giving up on {url} {params}" )


# --------------------------------------------------------------------------------------------- SMARD
def smard_series( name, filter_id ):
	index = get_json( f"{SMARD}/{filter_id}/DE/index_hour.json" )
	if not index:
		print( f"SMARD {name}: no index", flush = True )
		return pd.Series( dtype = float, name = name )
	start_ms = pd.Timestamp( START, tz = TZ ).value // 1_000_000 - 7 * 86400_000
	stamps = [ t for t in index[ "timestamps" ] if t >= start_ms ]

	def chunk( timestamp ):
		data = get_json( f"{SMARD}/{filter_id}/DE/{filter_id}_DE_hour_{timestamp}.json" )
		return data[ "series" ] if data else []

	with ThreadPoolExecutor( 6 ) as pool:
		rows = [ row for part in pool.map( chunk, stamps ) for row in part if row[ 1 ] is not None ]
	series = pd.Series( { ms: value for ms, value in rows }, name = name, dtype = float )
	print( f"SMARD {name}: {len( series )} hours", flush = True )
	return series


def fetch_smard():
	hourly = pd.concat( [ smard_series( name, fid ) for name, fid in SMARD_FILTERS.items() ], axis = 1 )
	hourly.index = pd.to_datetime( hourly.index, unit = "ms", utc = True ).tz_convert( TZ )
	hourly = hourly.sort_index()
	day = hourly.index.date
	daily = hourly.groupby( day ).sum( min_count = 20 )  # MWh per day (hourly MWh values summed)
	counts = hourly.groupby( day ).count()
	daily[ "price" ] = hourly[ "price" ].groupby( day ).mean()
	daily[ "price_max" ] = hourly[ "price" ].groupby( day ).max()
	daily[ "price_min" ] = hourly[ "price" ].groupby( day ).min()
	daily[ "hours" ] = counts[ "load" ]
	# The minimum hourly wind+solar share of the day (an hourly Dunkelflaute indicator)
	ws_share = ( hourly[ "wind_onshore" ] + hourly[ "wind_offshore" ] + hourly[ "pv" ] ) / hourly[ "load" ]
	daily[ "ws_share_hour_min" ] = ws_share.groupby( day ).min()
	daily.index.name = "date"
	daily = daily[ daily.index >= START ]
	daily.round( 3 ).to_csv( DATA_DIR / "smard_daily.csv" )
	print( f"wrote smard_daily.csv ({len( daily )} days)", flush = True )


# ---------------------------------------------------------------------------------------- Open-Meteo
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
PREVIOUS_RUNS = "https://previous-runs-api.open-meteo.com/v1/forecast"
HOURLY_VARS = [ "wind_speed_100m", "shortwave_radiation", "temperature_2m" ]


def archive_end():
	return dt.date.today() - dt.timedelta( days = 6 )


def year_ranges( start, end ):
	current = start
	while current <= end:
		stop = min( dt.date( current.year, 12, 31 ), end )
		yield current, stop
		current = stop + dt.timedelta( days = 1 )


def hourly_frame( payload, variables ):
	hourly = payload[ "hourly" ]
	frame = pd.DataFrame( { var: hourly[ var ] for var in variables },
						  index = pd.to_datetime( hourly[ "time" ], unit = "s", utc = True ).tz_convert( TZ ) )
	return frame.astype( float )


def fetch_weather():
	end = archive_end()
	frames = []
	for point in POINTS:
		parts = []
		for start, stop in year_ranges( START, end ):
			payload = get_json( ARCHIVE, {
				"latitude": point[ "lat" ], "longitude": point[ "lon" ],
				"start_date": start.isoformat(), "end_date": stop.isoformat(),
				"hourly": ",".join( HOURLY_VARS ), "wind_speed_unit": "ms",
				"timeformat": "unixtime", "models": "era5",
			} )
			if payload:
				parts.append( hourly_frame( payload, HOURLY_VARS ) )
			time.sleep( 1.0 )
		hourly = pd.concat( parts ).sort_index()
		daily = hourly_to_daily_features( hourly[ "wind_speed_100m" ], hourly[ "shortwave_radiation" ],
										  hourly[ "temperature_2m" ] )
		daily.columns = [ f"{point['id']}_{column}" for column in daily.columns ]
		frames.append( daily )
		print( f"ERA5 {point['id']}: {len( daily )} days", flush = True )
	weather = pd.concat( frames, axis = 1 )
	weather.index.name = "date"
	weather.round( 4 ).to_csv( DATA_DIR / "weather_daily.csv" )
	print( f"wrote weather_daily.csv ({len( weather )} days)", flush = True )


def fetch_mslp():
	end = archive_end()
	columns = {}
	batch = 10
	for i in range( 0, len( MSLP_GRID ), batch ):
		group = MSLP_GRID[ i:i + batch ]
		for start, stop in year_ranges( START, end ):
			payload = get_json( ARCHIVE, {
				"latitude": ",".join( str( lat ) for lat, _ in group ),
				"longitude": ",".join( str( lon ) for _, lon in group ),
				"start_date": start.isoformat(), "end_date": stop.isoformat(),
				"daily": "pressure_msl_mean", "timezone": TZ, "models": "era5",
			} )
			if payload is None:
				continue
			payload = payload if isinstance( payload, list ) else [ payload ]
			for (lat, lon), entry in zip( group, payload ):
				key = f"p{lat}_{lon}"
				values = pd.Series( entry[ "daily" ][ "pressure_msl_mean" ],
									index = pd.to_datetime( entry[ "daily" ][ "time" ] ).date, dtype = float )
				columns[ key ] = pd.concat( [ columns[ key ], values ] ) if key in columns else values
			time.sleep( 2.0 )
		print( f"MSLP {i + len( group )}/{len( MSLP_GRID )} points", flush = True )
	mslp = pd.DataFrame( columns ).sort_index()
	mslp.index.name = "date"
	mslp.round( 1 ).to_csv( DATA_DIR / "mslp_daily.csv" )
	print( f"wrote mslp_daily.csv ({len( mslp )} days)", flush = True )


FORECAST_MODELS = [ ( "ecmwf_ifs025", "wind_speed_100m" ), ( "gfs_global", "wind_speed_100m" ),
					( "icon_global", "wind_speed_120m" ) ]
LEADS = range( 1, 8 )


def fetch_forecasts():
	start = dt.date( 2024, 1, 1 )
	end = dt.date.today() - dt.timedelta( days = 2 )
	rows = []
	for model, wind_var in FORECAST_MODELS:
		names = [ f"{var}_previous_day{lead}" for lead in LEADS for var in ( wind_var, "shortwave_radiation", "temperature_2m" ) ]
		probe = get_json( PREVIOUS_RUNS, {
			"latitude": POINTS[ 0 ][ "lat" ], "longitude": POINTS[ 0 ][ "lon" ], "models": model,
			"start_date": ( end - dt.timedelta( days = 3 ) ).isoformat(), "end_date": end.isoformat(),
			"hourly": ",".join( names ), "wind_speed_unit": "ms", "timeformat": "unixtime",
		} )
		if not probe or all( v is None for v in probe[ "hourly" ].get( names[ 0 ], [ None ] ) ):
			print( f"forecast model {model}: not available, skipping", flush = True )
			continue
		cache_dir = DATA_DIR / ".cache"  # per point, so an interrupted run (rate limit) resumes cheaply
		cache_dir.mkdir( exist_ok = True )
		for point in POINTS:
			cache = cache_dir / f"forecast_{model}_{point['id']}.csv"
			if cache.exists():
				rows.append( pd.read_csv( cache, parse_dates = [ "date" ] ) )
				print( f"forecast {model} {point['id']}: cached", flush = True )
				continue
			parts = []
			for range_start, range_stop in year_ranges( start, end ):
				payload = get_json( PREVIOUS_RUNS, {
					"latitude": point[ "lat" ], "longitude": point[ "lon" ], "models": model,
					"start_date": range_start.isoformat(), "end_date": range_stop.isoformat(),
					"hourly": ",".join( names ), "wind_speed_unit": "ms", "timeformat": "unixtime",
				} )
				if payload:
					parts.append( hourly_frame( payload, names ) )
				time.sleep( 3 )
			if not parts:
				continue
			hourly = pd.concat( parts ).sort_index()
			point_rows = []
			for lead in LEADS:
				wind = hourly[ f"{wind_var}_previous_day{lead}" ]
				if wind_var == "wind_speed_120m":
					wind = wind * ( 100 / 120 ) ** 0.14  # power-law shear back to 100 m
				daily = hourly_to_daily_features( wind, hourly[ f"shortwave_radiation_previous_day{lead}" ],
												  hourly[ f"temperature_2m_previous_day{lead}" ] )
				daily = daily.dropna( how = "all" )
				daily.columns = [ f"{point['id']}_{column}" for column in daily.columns ]
				daily[ "model" ], daily[ "lead" ] = model, lead
				point_rows.append( daily.reset_index( names = "date" ) )
			point_frame = pd.concat( point_rows )
			point_frame.round( 4 ).to_csv( cache, index = False )
			rows.append( point_frame )
			print( f"forecast {model} {point['id']}: done", flush = True )
		break  # one archived model is enough for the backtest (and keeps within the free API budget)
	if not rows:
		print( "no forecasts fetched", flush = True )
		return
	frame = pd.concat( rows )
	# one row per (date, model, lead) with all points side by side
	frame[ "date" ] = pd.to_datetime( frame[ "date" ] ).dt.date
	frame = frame.groupby( [ "date", "model", "lead" ] ).first().reset_index()
	frame.round( 4 ).to_csv( DATA_DIR / "forecast_daily.csv", index = False )
	print( f"wrote forecast_daily.csv ({len( frame )} rows)", flush = True )


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument( "--only", default = "smard,weather,mslp,forecast" )
	parts = parser.parse_args().only.split( "," )
	DATA_DIR.mkdir( exist_ok = True )
	np.seterr( all = "ignore" )
	steps = { "smard": fetch_smard, "weather": fetch_weather, "mslp": fetch_mslp, "forecast": fetch_forecasts }
	for part in parts:
		started = time.time()
		try:
			steps[ part ]()
		except Exception as error:  # keep the other parts going, report at the end
			print( f"!! {part} failed: {error!r}", flush = True )
		print( f"{part}: {time.time() - started:.0f}s", flush = True )
