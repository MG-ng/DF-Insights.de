"""Live Dunkelflaute outlook for the next 15 days from three global ensembles (130+ members):

  ECMWF IFS ENS (51 members), ECMWF AIFS ENS (51, the machine-learning ensemble) and NOAA GEFS (31),
  all from the free Open-Meteo ensemble API.

Every member's hourly 100 m wind, radiation and temperature at the 16 model points goes through
the same feature pipeline and energy model as in the backtest. The probability of a Dunkelflaute
day is the member average of a Gaussian (logit) model error around each member's renewable share,
so both weather uncertainty (member spread) and energy-model error are included. ECMWF members'
sea level pressure is also sorted into the 7 weather regimes, giving regime probabilities per day.

Open-Meteo's free tier is metered per location, variable and member, so results are cached for
3 hours (in memory, per process).
"""
import datetime as dt
import threading
import time

import numpy as np
import pandas as pd
import requests

from prediction.features import MSLP_GRID, POINTS, hourly_to_daily_features
from prediction.model import load_model, logit, normal_cdf, predict_components

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


def calibrate( model, lead_days, shares ):
	"""Per-lead linear recalibration of the logit share, fitted on archived forecasts (train.py)."""
	calibration = model.get( "forecast_calibration" ) or {}
	if not calibration:
		return shares, None
	leads = sorted( int( k ) for k in calibration )
	key = str( min( max( lead_days, leads[ 0 ] ), leads[ -1 ] ) )
	params = calibration[ key ]
	corrected = params[ "a" ] + params[ "b" ] * logit( shares )
	return 1 / ( 1 + np.exp( -corrected ) ), params[ "sigma" ]


def build_outlook( model = None ):
	model = model or load_model()
	today = pd.Timestamp( dt.datetime.now( dt.timezone.utc ) ).tz_convert( TZ ).normalize().tz_localize( None )
	shares, components, used = {}, {}, []
	for key, label in ENSEMBLES.items():
		try:
			members = fetch_members( key )
		except ( requests.RequestException, ValueError, KeyError ) as error:
			print( f"Dunkelflaute outlook: {key} failed: {error!r}" )
			continue
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
		calibrated, sigma_lead = calibrate( model, max( lead, 1 ), values )
		# member spread already carries the weather uncertainty, so each member gets only the model error;
		# use the larger of that and the remaining (non-weather) part of the archived-forecast error
		sigma = sigma_model
		probabilities = {}
		for threshold in model[ "thresholds" ]:
			p = float( np.mean( normal_cdf( ( logit( threshold ) - logit( calibrated ) ) / sigma ) ) )
			clim = month_clim.get( str( threshold ) )
			if clim and lead > 10:  # beyond ~10 days ensemble skill fades: blend towards climatology
				weight = min( 0.3, 0.06 * ( lead - 10 ) )
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
			"sigma_lead": None if sigma_lead is None else round( sigma_lead, 3 ),
		} )

	regimes = None
	if model.get( "regimes" ):
		try:
			labels = classify_regimes( REGIME_MODEL, model[ "regimes" ] )
			frame = pd.DataFrame( labels )
			frame = frame[ frame.index >= today ]
			n = len( model[ "regimes" ][ "names" ] )
			regimes = {
				"names": model[ "regimes" ][ "names" ],
				"days": [ { "date": str( d.date() ),
							"probabilities": [ round( float( ( r.dropna() == k ).mean() ), 3 ) for k in range( n ) ] }
						  for d, r in frame.iterrows() ],
			}
		except ( requests.RequestException, ValueError, KeyError ) as error:
			print( f"Dunkelflaute outlook: regimes failed: {error!r}" )
	return {
		"issued": dt.datetime.now( dt.timezone.utc ).isoformat( timespec = "minutes" ),
		"ensembles": used, "thresholds": model[ "thresholds" ], "days": days, "regimes": regimes,
	}


def cached_outlook():
	with _lock:
		if _cache[ "value" ] is None or time.time() - _cache[ "time" ] > CACHE_SECONDS:
			_cache[ "value" ] = build_outlook()
			_cache[ "time" ] = time.time()
		return _cache[ "value" ]
