"""Live Dunkelflaute outlook for the next 15 days from three global ensembles (130+ members):

  ECMWF IFS ENS (51 members), ECMWF AIFS ENS (51, the machine-learning ensemble) and NOAA GEFS (31),
  all from the free Open-Meteo ensemble API.

Every member's hourly 100 m wind, radiation and temperature at the 16 model points goes through
the same feature pipeline and energy model as in the backtest. The probability of a Dunkelflaute
day is the member average of a Gaussian (logit) model error around each member's renewable share,
so both weather uncertainty (member spread) and energy-model error are included. ECMWF members'
sea level pressure is also sorted into the 7 weather regimes, giving regime probabilities per day.

Open-Meteo's free tier is metered per location, variable and member, so results are cached for
3 hours in a file in the temp directory, shared by all web server workers. If a refresh fails,
the last result is served for up to a day.
"""
import datetime as dt
import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from prediction.features import MSLP_GRID, POINTS, hourly_to_daily_features
from prediction.model import load_model, logit, predict_components

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
TZ = "Europe/Berlin"
ENSEMBLES = {
	"ecmwf_ifs025": "ECMWF IFS ENS",
	"ecmwf_aifs025": "ECMWF AIFS ENS",
	"gfs05": "NOAA GEFS",
}
REGIME_MODEL = "ecmwf_ifs025"
CACHE_SECONDS = 3 * 3600
FORECAST_DAYS = 15

STALE_SECONDS = 24 * 3600
CACHE_FILE = Path( os.getenv( "DF_OUTLOOK_CACHE", Path( tempfile.gettempdir() ) / "df-insights-outlook.json" ) )

_cache = { "time": 0.0, "value": None }
_lock = threading.Lock()


def _get( params, timeout = 60, tries = 3 ):
	for attempt in range( tries ):
		try:
			response = requests.get( ENSEMBLE_URL, params = params, timeout = timeout )
			response.raise_for_status()
			break
		except requests.RequestException:
			if attempt == tries - 1:
				raise
			time.sleep( 2 * ( attempt + 1 ) )
	payload = response.json()
	return payload if isinstance( payload, list ) else [ payload ]


def member_keys( hourly, variable ):
	"""Column names of the control run and all perturbed members of one variable."""
	keys = [ variable ] if variable in hourly else []
	keys += sorted( k for k in hourly if k.startswith( f"{variable}_member" ) )
	return keys


def fetch_members( model ):
	"""Daily feature frames per ensemble member: {member_index: DataFrame(days x point features)}."""
	payload = _get( {
		"latitude": ",".join( str( p[ "lat" ] ) for p in POINTS ),
		"longitude": ",".join( str( p[ "lon" ] ) for p in POINTS ),
		"hourly": "wind_speed_100m,shortwave_radiation,temperature_2m",
		"models": model, "forecast_days": FORECAST_DAYS + 1, "wind_speed_unit": "ms",
		"timeformat": "unixtime", "timezone": TZ,
	} )
	members = {}
	for point, entry in zip( POINTS, payload ):
		hourly = entry[ "hourly" ]
		index = pd.to_datetime( hourly[ "time" ], unit = "s", utc = True ).tz_convert( TZ )
		wind_keys = member_keys( hourly, "wind_speed_100m" )
		for m, wind_key in enumerate( wind_keys ):
			suffix = wind_key[ len( "wind_speed_100m" ): ]
			series = { var: pd.Series( hourly.get( var + suffix ), index = index, dtype = float )
					   for var in ( "wind_speed_100m", "shortwave_radiation", "temperature_2m" ) }
			daily = hourly_to_daily_features( series[ "wind_speed_100m" ], series[ "shortwave_radiation" ],
											  series[ "temperature_2m" ] )
			daily.columns = [ f"{point['id']}_{c}" for c in daily.columns ]
			members.setdefault( m, [] ).append( daily )
	frames = {}
	for m, parts in members.items():
		frame = pd.concat( parts, axis = 1 ).dropna()
		frame.index = pd.DatetimeIndex( frame.index )
		if len( frame ):
			frames[ m ] = frame
	return frames


def classify_regimes( model, regime_params ):
	"""Daily regime of every ECMWF member from its forecast sea level pressure."""
	lats = [ lat for lat, _ in MSLP_GRID ]
	lons = [ lon for _, lon in MSLP_GRID ]
	payload = _get( {
		"latitude": ",".join( map( str, lats ) ), "longitude": ",".join( map( str, lons ) ),
		"hourly": "pressure_msl", "models": model, "forecast_days": FORECAST_DAYS + 1,
		"timeformat": "unixtime", "timezone": TZ,
	}, timeout = 90 )
	fields = {}
	for g, entry in enumerate( payload ):
		hourly = entry[ "hourly" ]
		index = pd.to_datetime( hourly[ "time" ], unit = "s", utc = True ).tz_convert( TZ )
		for m, key in enumerate( member_keys( hourly, "pressure_msl" ) ):
			daily = pd.Series( hourly[ key ], index = index, dtype = float ).groupby( index.date ).mean()
			fields.setdefault( m, {} )[ g ] = daily
	clim = np.array( regime_params[ "climatology" ] )  # day-of-year x grid point
	weights = np.array( regime_params[ "weights" ] )
	mean, eofs, centres = ( np.array( regime_params[ k ] ) for k in ( "mean", "eofs", "centres" ) )
	labels = {}
	for m, columns in fields.items():
		frame = pd.DataFrame( columns ).dropna()
		if frame.empty:
			continue
		doy = pd.DatetimeIndex( frame.index ).dayofyear.to_numpy()
		anomaly = frame.to_numpy() - clim[ np.minimum( doy, len( clim ) ) - 1 ]
		pcs = ( anomaly * weights - mean ) @ eofs.T
		labels[ m ] = pd.Series( np.argmin( ( ( pcs[ :, None, : ] - centres[ None ] ) ** 2 ).sum( -1 ), axis = 1 ),
								 index = pd.DatetimeIndex( frame.index ) )
	return labels


def member_probability( model, shares, threshold ):
	"""P(Dunkelflaute) for each member's predicted share: the energy model's own error, as a logistic curve
	calibrated on held-out ERA5 years (train.py). The weather uncertainty comes from the member spread."""
	error = model[ "error" ]
	z = ( logit( threshold ) - logit( shares ) ) / error[ "sigma_model_logit" ]
	return 1 / ( 1 + np.exp( -( error.get( "alpha", 0.0 ) + error.get( "beta", 1.7 ) * z ) ) )


def build_outlook( model = None ):
	model = model or load_model()
	today = pd.Timestamp( dt.datetime.now( dt.timezone.utc ) ).tz_convert( TZ ).normalize().tz_localize( None )
	shares, components, used = {}, {}, []

	def fetch( key ):
		try:
			return fetch_members( key )
		except ( requests.RequestException, ValueError, KeyError ) as error:
			print( f"Dunkelflaute outlook: {key} failed: {error!r}" )
			return None

	regime_labels = None
	with ThreadPoolExecutor( len( ENSEMBLES ) + 1 ) as pool:
		regime_future = pool.submit( classify_regimes, REGIME_MODEL, model[ "regimes" ] ) if model.get( "regimes" ) else None
		results = dict( zip( ENSEMBLES, pool.map( fetch, ENSEMBLES ) ) )
		if regime_future is not None:
			try:
				regime_labels = regime_future.result()
			except ( requests.RequestException, ValueError, KeyError ) as error:
				print( f"Dunkelflaute outlook: regimes failed: {error!r}" )
	for key, label in ENSEMBLES.items():
		members = results[ key ]
		if not members:
			continue
		used.append( { "id": key, "name": label, "members": len( members ) } )
		for m, wx in members.items():
			predicted = predict_components( model, wx )
			shares[ ( key, m ) ] = predicted[ "re_share" ]
			components[ ( key, m ) ] = predicted
	if not shares:
		raise RuntimeError( "no ensemble data" )

	table = pd.DataFrame( shares )
	table = table[ table.index >= today ]
	table = table[ table.notna().mean( axis = 1 ) >= 0.5 ]
	sigma_model = model[ "error" ][ "sigma_model_logit" ]
	month_clim = model.get( "climatology_df_rate_by_month", {} )
	days = []
	for date, row in table.iterrows():
		values = row.dropna().to_numpy()
		lead = int( ( date - today ).days )
		calibrated = values
		probabilities = {}
		for threshold in model[ "thresholds" ]:
			p = float( np.mean( member_probability( model, calibrated, threshold ) ) )
			clim = month_clim.get( str( threshold ) )
			if clim and lead > 7:  # skill fades after about a week (see the backtest): blend towards climatology
				weight = min( 0.35, 0.05 * ( lead - 7 ) )
				p = ( 1 - weight ) * p + weight * clim[ date.month - 1 ]
			probabilities[ str( threshold ) ] = round( p, 3 )
		member_frames = [ components[ k ].loc[ date ] for k in row.dropna().index ]
		mean_components = pd.DataFrame( member_frames ).mean()
		days.append( {
			"date": str( date.date() ), "lead": lead, "members": int( len( values ) ),
			"probability": probabilities,
			"share": { q: round( float( np.quantile( calibrated, v ) ), 3 )
					   for q, v in ( ( "p10", 0.1 ), ( "p25", 0.25 ), ( "p50", 0.5 ), ( "p75", 0.75 ), ( "p90", 0.9 ) ) },
			"gwh": { c: round( float( mean_components[ c ] ) / 1000, 1 )
					 for c in ( "wind_on", "wind_off", "pv", "other_re", "load" ) },
		} )

	regimes = None
	if regime_labels:
		frame = pd.DataFrame( regime_labels )
		frame = frame[ frame.index >= today ]
		n = len( model[ "regimes" ][ "names" ] )
		regimes = {
			"names": model[ "regimes" ][ "names" ],
			"days": [ { "date": str( d.date() ),
						"probabilities": [ round( float( ( r.dropna() == k ).mean() ), 3 ) for k in range( n ) ] }
					  for d, r in frame.iterrows() ],
		}
	return {
		"events": multi_day_events( model, table, today,
									sigma_model / model[ "error" ].get( "beta", 1.7 ) * 1.7 ),  # logistic -> normal scale
		"issued": dt.datetime.now( dt.timezone.utc ).isoformat( timespec = "minutes" ),
		"ensembles": used, "thresholds": model[ "thresholds" ], "days": days, "regimes": regimes,
	}


def _read_cache_file():
	try:
		with open( CACHE_FILE ) as handle:
			stored = json.load( handle )
		return stored[ "time" ], stored[ "value" ]
	except ( OSError, ValueError, KeyError ):
		return 0.0, None


def _write_cache_file( stamp, value ):
	try:
		temporary = CACHE_FILE.with_suffix( f".{os.getpid()}.tmp" )
		with open( temporary, "w" ) as handle:
			json.dump( { "time": stamp, "value": value }, handle )
		os.replace( temporary, CACHE_FILE )
	except OSError as error:  # read-only file system: the in-memory cache still works
		print( f"Dunkelflaute outlook: cache not written: {error!r}" )


def multi_day_events( model, table, today, sigma, draws = 40, rho = 0.6, min_days = 2, seed = 7 ):
	"""P(at least `min_days` Dunkelflaute days in a row) in the coming week and the whole outlook.

	Ensembles keep each scenario consistent over time, so runs of calm days can be counted per member,
	which a day-by-day probability cannot tell. The energy model's error is added as AR(1) noise
	(correlated from day to day), sampled `draws` times per member."""
	rng = np.random.default_rng( seed )
	complete = table.dropna( axis = 1 )
	if complete.empty:
		return None
	leads = np.array( [ ( d - today ).days for d in complete.index ] )
	columns = complete.to_numpy().T  # members x days
	logits = logit( columns )
	noise = np.empty( ( draws, ) + logits.shape )
	noise[ ..., 0 ] = rng.standard_normal( noise.shape[ :-1 ] )
	for day in range( 1, logits.shape[ 1 ] ):
		noise[ ..., day ] = rho * noise[ ..., day - 1 ] + np.sqrt( 1 - rho ** 2 ) * rng.standard_normal( noise.shape[ :-1 ] )
	samples = logits[ None ] + sigma * noise  # draws x members x days
	result = {}
	for threshold in model[ "thresholds" ]:
		below = samples <= logit( threshold )
		run = np.zeros( below.shape[ :-1 ], dtype = int )
		longest = np.zeros_like( run )
		week_longest = np.zeros_like( run )
		for day in range( below.shape[ -1 ] ):
			run = np.where( below[ ..., day ], run + 1, 0 )
			longest = np.maximum( longest, run )
			if leads[ day ] <= 7:
				week_longest = np.maximum( week_longest, run )
		result[ str( threshold ) ] = {
			"next_7_days": round( float( ( week_longest >= min_days ).mean() ), 3 ),
			"whole_outlook": round( float( ( longest >= min_days ).mean() ), 3 ),
			"expected_days": round( float( below.sum( -1 ).mean() ), 1 ),
		}
	return { "min_days": min_days, "days": int( len( leads ) ), "by_threshold": result }


def cached_outlook():
	"""The outlook, rebuilt at most every 3 hours; on failure the last good one (up to a day old)."""
	with _lock:
		if _cache[ "value" ] is None or time.time() - _cache[ "time" ] > CACHE_SECONDS:
			stamp, value = _read_cache_file()  # another worker may have refreshed it
			if value is not None and stamp > _cache[ "time" ]:
				_cache.update( time = stamp, value = value )
		if _cache[ "value" ] is not None and time.time() - _cache[ "time" ] <= CACHE_SECONDS:
			return _cache[ "value" ]
		try:
			value = build_outlook()
		except ( requests.RequestException, RuntimeError, ValueError, KeyError ):
			if _cache[ "value" ] is not None and time.time() - _cache[ "time" ] <= STALE_SECONDS:
				return _cache[ "value" ]
			raise
		_cache.update( time = time.time(), value = value )
		_write_cache_file( _cache[ "time" ], value )
		return value
