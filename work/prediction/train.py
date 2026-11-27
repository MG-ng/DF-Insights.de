"""Train the Dunkelflaute forecast model and backtest it honestly against baselines.

  python -m prediction.train          (from work/, after prediction.fetch_training_data)

Writes prediction/model.json (coefficients the website uses) and prediction/backtest.json
(the scores and series shown on /prediction).

Method in short
---------------
1. Physical-statistical generation model. Hourly 100 m wind goes through a turbine power curve
   (features.py) at 16 points where Germany's wind and PV fleet is; ridge regressions map the
   daily capacity factors / radiation to SMARD's onshore, offshore and PV generation, and calendar
   plus temperature to grid load. Fleet growth is handled with a capacity index: the ratio of
   actual generation to modelled generation over the trailing 365 days, extrapolated linearly.
2. Dunkelflaute day = daily renewable share (site definition, incl. biomass and hydro) <= threshold.
3. Probabilities: the predicted share gets a Gaussian error in logit space whose width is
   measured per lead time on held-out data (and, live, is combined with the ECMWF ensemble spread).
4. Weather regimes: k-means on ERA5 sea level pressure anomalies over the Euro-Atlantic gives
   7 regimes (as in Grams et al. 2017); their Dunkelflaute rates and persistence give the
   long-range (week 2 to 4) outlook.

Backtest periods are never used for fitting: generation/load models are trained on 2015-2022
ERA5 years; error widths and NWP recalibration are fitted on 2024 forecasts and scored on 2025+.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from prediction.features import MSLP_GRID
from prediction.model import COMPONENTS, apply_linear, design, logit, probability_below

HERE = Path( __file__ ).resolve().parent
DATA = HERE / "data"
TRAIN_END = pd.Timestamp( "2022-12-31" )
TEST_START = pd.Timestamp( "2023-01-01" )
CALIBRATION_END = pd.Timestamp( "2024-12-31" )  # forecasts: calibrate on 2024, score on 2025+
THRESHOLDS = [ 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55 ]
MAIN_THRESHOLD = 0.35
# A linear recalibration of the forecast share (a + b * logit) was tried: it pulls calm days towards the mean
# and lowered the skill at 1-5 days, so only the probabilities are calibrated (logistic, see below).
RECALIBRATE = False
N_REGIMES = 7
RIDGE = { "wind_on": 1.0, "wind_off": 1.0, "pv": 1.0, "load": 0.1 }


# ------------------------------------------------------------------------------------------- data
def read_daily( name ):
	frame = pd.read_csv( DATA / name, index_col = 0, parse_dates = True )
	frame.index = pd.DatetimeIndex( frame.index ).normalize()
	return frame


def load_targets():
	smard = read_daily( "smard_daily.csv" )
	smard = smard[ smard[ "hours" ] >= 23 ]
	targets = pd.DataFrame( index = smard.index )
	targets[ "wind_on" ] = smard[ "wind_onshore" ]
	targets[ "wind_off" ] = smard[ "wind_offshore" ]
	targets[ "pv" ] = smard[ "pv" ]
	targets[ "load" ] = smard[ "load" ]
	targets[ "other_re" ] = ( smard[ "hydro" ] + smard[ "biomass" ] + smard[ "other_renewables" ]
							  + smard[ "pumped_storage_generation" ].fillna( 0 )
							  - smard[ "pumped_storage_consumption" ].fillna( 0 ) )
	targets[ "re_share" ] = ( targets[ "wind_on" ] + targets[ "wind_off" ] + targets[ "pv" ]
							  + targets[ "other_re" ] ) / targets[ "load" ]
	for name in ( "forecast_onshore", "forecast_offshore", "forecast_pv", "forecast_load", "price",
				  "price_max", "ws_share_hour_min" ):
		targets[ name ] = smard.get( name )
	return targets.dropna( subset = [ "wind_on", "wind_off", "pv", "load", "other_re" ] )


# ------------------------------------------------------------------------------------ ridge model
def fit_ridge( x, y, alpha ):
	mean = x.mean( axis = 0 )
	scale = x.std( axis = 0 )
	scale[ scale == 0 ] = 1.0
	z = ( x - mean ) / scale
	y_mean = y.mean()
	coef = np.linalg.solve( z.T @ z + alpha * len( y ) * 1e-3 * np.eye( z.shape[ 1 ] ), z.T @ ( y - y_mean ) )
	return { "intercept": float( y_mean ), "coef": coef.tolist(), "mean": mean.tolist(), "scale": scale.tolist() }


def trailing_ratio( actual, modelled, window = 365 ):
	"""Capacity index known at the end of each day: sum(actual)/sum(modelled) over the trailing window."""
	a = actual.rolling( window, min_periods = window // 2 ).sum()
	m = modelled.rolling( window, min_periods = window // 2 ).sum()
	return a / m


def extrapolated_capacity( ratio, issue_dates, target_dates ):
	"""Capacity index for target days from what was known at the issue days (day before issue):
	the trailing ratio describes the fleet about half a window (182 days) back, so extrapolate
	with the growth over the past year."""
	known = ratio.reindex( pd.DatetimeIndex( issue_dates ) - pd.Timedelta( days = 1 ) ).to_numpy()
	year_before = ratio.reindex( pd.DatetimeIndex( issue_dates ) - pd.Timedelta( days = 366 ) ).to_numpy()
	slope = ( known - year_before ) / 365.0
	slope = np.where( np.isnan( slope ), 0.0, slope )
	ahead = ( pd.DatetimeIndex( target_dates ) - pd.DatetimeIndex( issue_dates ) ).days.to_numpy() + 183
	return known + slope * ahead


def fit_component( component, wx, target, train_mask ):
	"""Ridge fit of target/capacity on weather; the capacity index is iterated to convergence."""
	x_frame = design( component, wx )
	features = list( x_frame.columns )
	capacity = pd.Series( 1.0, index = wx.index )
	if component == "load":
		capacity = target.rolling( 365, center = True, min_periods = 120 ).mean()
	params = None
	for _ in range( 4 if component != "load" else 1 ):
		normalised = target / capacity
		ok = train_mask & normalised.notna() & x_frame.notna().all( axis = 1 )
		params = fit_ridge( x_frame[ ok ].to_numpy(), normalised[ ok ].to_numpy(), RIDGE[ component ] )
		params[ "features" ] = features
		unit = pd.Series( np.maximum( apply_linear( params, x_frame.fillna( 0 ) ), 1e-6 ), index = wx.index )
		if component != "load":
			# centred ratio for fitting: the fleet size around each training day
			a = target.rolling( 365, center = True, min_periods = 120 ).sum()
			m = unit.where( target.notna() ).rolling( 365, center = True, min_periods = 120 ).sum()
			capacity = ( a / m ).bfill().ffill()  # fleet size (MWh/day per unit of model output) around each day
	unit = pd.Series( apply_linear( params, x_frame.fillna( 0 ) ), index = wx.index )
	if component != "load":
		unit = unit.clip( lower = 0 )
	return params, unit


# ------------------------------------------------------------------------------------- scoring
def brier( p, y ):
	p, y = np.asarray( p, float ), np.asarray( y, float )
	return float( np.mean( ( p - y ) ** 2 ) )


def auc( p, y ):
	p, y = np.asarray( p, float ), np.asarray( y, bool )
	pos, neg = p[ y ], p[ ~y ]
	if len( pos ) == 0 or len( neg ) == 0:
		return None
	ranks = pd.Series( np.concatenate( [ pos, neg ] ) ).rank().to_numpy()
	return float( ( ranks[ :len( pos ) ].sum() - len( pos ) * ( len( pos ) + 1 ) / 2 ) / ( len( pos ) * len( neg ) ) )


def scores( p, y, reference ):
	b, b_ref = brier( p, y ), brier( reference, y )
	p_arr, y_arr = np.asarray( p ), np.asarray( y, bool )
	warn = p_arr >= 0.5
	hits = int( ( warn & y_arr ).sum() )
	return {
		"brier": round( b, 4 ),
		"bss": round( 1 - b / b_ref, 3 ) if b_ref > 0 else None,
		"auc": None if auc( p, y ) is None else round( auc( p, y ), 3 ),
		"events": int( y_arr.sum() ), "days": int( len( y_arr ) ),
		"hit_rate": round( hits / max( 1, y_arr.sum() ), 3 ),
		"false_alarm_ratio": round( 1 - hits / max( 1, warn.sum() ), 3 ) if warn.sum() else None,
	}


def reliability( p, y, bins = ( 0, 0.05, 0.15, 0.3, 0.5, 0.7, 0.85, 0.95, 1.0001 ) ):
	p, y = np.asarray( p ), np.asarray( y, float )
	rows = []
	for lo, hi in zip( bins[ :-1 ], bins[ 1: ] ):
		m = ( p >= lo ) & ( p < hi )
		if m.sum() >= 5:
			rows.append( { "forecast": round( float( p[ m ].mean() ), 3 ), "observed": round( float( y[ m ].mean() ), 3 ),
						   "n": int( m.sum() ) } )
	return rows


def fit_logistic( z, y, iterations = 50 ):
	"""Two-parameter logistic regression (Newton steps), returns (alpha, beta)."""
	x = np.column_stack( [ np.ones_like( z ), z ] )
	w = np.array( [ 0.0, 1.0 ] )
	for _ in range( iterations ):
		p = 1 / ( 1 + np.exp( -( x @ w ) ) )
		gradient = x.T @ ( y - p )
		hessian = x.T @ ( x * ( p * ( 1 - p ) )[ :, None ] ) + 1e-6 * np.eye( 2 )
		w = w + np.linalg.solve( hessian, gradient )
	return float( w[ 0 ] ), float( w[ 1 ] )


def calibrated_probability( corrected_logit, threshold, params ):
	z = ( logit( threshold ) - corrected_logit ) / params[ "sigma" ]
	return 1 / ( 1 + np.exp( -( params[ "alpha" ] + params[ "beta" ] * z ) ) )


# ------------------------------------------------------------------------------- weather regimes
def kmeans( x, k, seed = 0, iterations = 100, restarts = 10 ):
	rng = np.random.default_rng( seed )
	best = None
	for _ in range( restarts ):
		centres = x[ rng.choice( len( x ), k, replace = False ) ]
		for _ in range( iterations ):
			labels = np.argmin( ( ( x[ :, None, : ] - centres[ None ] ) ** 2 ).sum( -1 ), axis = 1 )
			new = np.array( [ x[ labels == j ].mean( 0 ) if ( labels == j ).any() else centres[ j ] for j in range( k ) ] )
			if np.allclose( new, centres ):
				break
			centres = new
		inertia = ( ( x - centres[ labels ] ) ** 2 ).sum()
		if best is None or inertia < best[ 0 ]:
			best = ( inertia, centres, labels )
	return best[ 1 ], best[ 2 ]


def regimes( mslp, train_mask ):
	"""7 regimes from daily MSLP anomalies (seasonal cycle removed, 10-day low-pass, latitude weighted),
	PCA to 7 EOFs and k-means, like the usual regime classifications. Returns labels and the parts
	needed to classify new (forecast) fields."""
	mslp = mslp.dropna()
	doy = mslp.index.dayofyear
	clim = mslp.groupby( doy ).mean().rolling( 31, center = True, min_periods = 1 ).mean()
	anomaly = mslp - clim.reindex( doy ).to_numpy()
	anomaly = anomaly.rolling( 5, center = True, min_periods = 1 ).mean()
	weights = np.sqrt( np.cos( np.deg2rad( [ lat for lat, _ in MSLP_GRID ] ) ) )
	x = anomaly.to_numpy() * weights
	train = x[ train_mask.reindex( anomaly.index ).fillna( False ).to_numpy() ]
	mean = train.mean( 0 )
	_, _, vt = np.linalg.svd( train - mean, full_matrices = False )
	eofs = vt[ :7 ]
	pcs = ( x - mean ) @ eofs.T
	centres, _ = kmeans( pcs[ train_mask.reindex( anomaly.index ).fillna( False ).to_numpy() ], N_REGIMES )
	labels = np.argmin( ( ( pcs[ :, None, : ] - centres[ None ] ) ** 2 ).sum( -1 ), axis = 1 )
	centre_fields = centres @ eofs / weights  # hPa anomaly pattern of each regime
	return pd.Series( labels, index = anomaly.index ), {
		"climatology": clim.round( 1 ).to_numpy().tolist(), "mean": mean.tolist(), "eofs": eofs.tolist(),
		"centres": centres.tolist(), "weights": weights.tolist(), "patterns": centre_fields.round( 1 ).tolist(),
	}


def name_regime( pattern ):
	"""Name a regime from its mean MSLP anomaly pattern (hPa) on the 6 x 7 grid (lat 35..70, lon -30..30),
	following the usual Euro-Atlantic regime names (Grams et al. 2017)."""
	grid = np.array( pattern ).reshape( 6, 7 )
	lats, lons = ( 35, 42, 49, 56, 63, 70 ), ( -30, -20, -10, 0, 10, 20, 30 )
	i, j = np.unravel_index( np.argmax( grid ), grid.shape )
	high_lat, high_lon, high = lats[ i ], lons[ j ], grid.max()
	germany = grid[ 2:4, 4 ].mean()  # 49-56N, 10E
	north, south = grid[ 4:, : ].mean(), grid[ :2, : ].mean()
	if north < -5 and south > 1:
		return "Zonal (strong westerlies)"
	if high > 3:
		if high_lat >= 63 and high_lon <= -20:
			return "Greenland blocking"
		if high_lat >= 56 and high_lon >= 10:
			return "Scandinavian blocking"
		if high_lat >= 63:
			return "Northern blocking (Iceland to North Sea high)"
		if high_lon <= -20:
			return "Atlantic ridge"
		return "European blocking"
	if germany < -3:
		return "Trough over Central Europe"
	return "No clear regime"


def unique_names( names ):
	seen = {}
	result = []
	for name in names:
		seen[ name ] = seen.get( name, 0 ) + 1
		result.append( name if seen[ name ] == 1 else f"{name} ({seen[name]})" )
	return result


# ---------------------------------------------------------------------------------------- main
def main():
	targets = load_targets()
	wx = read_daily( "weather_daily.csv" )
	days = targets.index.intersection( wx.index )
	targets, wx = targets.loc[ days ], wx.loc[ days ]
	train = pd.Series( days <= TRAIN_END, index = days )
	model = { "version": 1, "trained_on": f"{days[0].date()} .. {TRAIN_END.date()}", "data_until": str( days[ -1 ].date() ) }

	units, ratios = {}, {}
	for component in COMPONENTS + ( "load", ):
		params, unit = fit_component( component, wx, targets[ component ], train )
		units[ component ] = unit
		if component == "load":
			ratio = targets[ "load" ].rolling( 365, min_periods = 180 ).mean() / unit.rolling( 365, min_periods = 180 ).mean()
		else:
			ratio = trailing_ratio( targets[ component ], unit )
		ratios[ component ] = ratio
		last = ratio.dropna()
		slope = ( last.iloc[ -1 ] - last.iloc[ -366 ] ) / 365.0
		params[ "capacity" ] = { "ref_date": str( ( last.index[ -1 ] - pd.Timedelta( days = 182 ) ).date() ),
								 "value": float( last.iloc[ -1 ] ), "slope_per_day": float( slope ) }
		model[ component ] = params
	recent = targets[ "other_re" ].iloc[ -730: ]
	model[ "other_re" ] = { "by_month": [ float( recent[ recent.index.month == m ].mean() ) for m in range( 1, 13 ) ] }

	def reconstruct( wx_frame, issue, target_days, other_re ):
		"""Predicted components for target_days with the fleet known at the issue days."""
		out = pd.DataFrame( index = target_days )
		for component in COMPONENTS + ( "load", ):
			unit = apply_linear( model[ component ], design( component, wx_frame ).fillna( 0 ) )
			if component != "load":
				unit = np.maximum( unit, 0 )
			out[ component ] = unit * extrapolated_capacity( ratios[ component ], issue, target_days )
		out[ "other_re" ] = other_re
		out[ "re_share" ] = ( out[ "wind_on" ] + out[ "wind_off" ] + out[ "pv" ] + out[ "other_re" ] ) / out[ "load" ]
		return out

	other_trailing = targets[ "other_re" ].rolling( 28, min_periods = 14 ).mean()

	def other_known( issue ):
		return other_trailing.reindex( pd.DatetimeIndex( issue ) - pd.Timedelta( days = 1 ) ).to_numpy()

	backtest = { "thresholds": THRESHOLDS, "main_threshold": MAIN_THRESHOLD, "periods": {} }

	# --- 1) ERA5 "perfect weather" skill of the energy model (lead 1 fleet knowledge)
	test_days = days[ days >= TEST_START ]
	issue = test_days - pd.Timedelta( days = 1 )
	era5 = reconstruct( wx.loc[ test_days ], issue, test_days, other_known( issue ) )
	actual = targets.loc[ test_days ]
	err_logit = logit( actual[ "re_share" ] ) - logit( era5[ "re_share" ] )
	relevant = np.minimum( actual[ "re_share" ], era5[ "re_share" ] ).to_numpy() < 0.75
	sigma_model = float( np.std( err_logit[ ( test_days <= CALIBRATION_END ) & relevant ] ) )
	cal_days = np.asarray( test_days <= CALIBRATION_END )
	era5_logit = logit( era5[ "re_share" ] )
	z_cal = np.concatenate( [ ( logit( t ) - era5_logit[ cal_days ] ) / sigma_model for t in THRESHOLDS ] )
	y_cal = np.concatenate( [ ( actual[ "re_share" ].to_numpy()[ cal_days ] <= t ) for t in THRESHOLDS ] )
	alpha0, beta0 = fit_logistic( z_cal, y_cal )
	model[ "error" ] = { "sigma_model_logit": sigma_model, "alpha": alpha0, "beta": beta0 }
	component_skill = {}
	for component in COMPONENTS + ( "load", "re_share" ):
		a, p = actual[ component ], era5[ component ]
		component_skill[ component ] = {
			"mae": round( float( np.mean( np.abs( a - p ) ) ), 4 if component == "re_share" else 0 ),
			"bias": round( float( np.mean( p - a ) ), 4 if component == "re_share" else 0 ),
			"r2": round( float( 1 - np.sum( ( a - p ) ** 2 ) / np.sum( ( a - a.mean() ) ** 2 ) ), 3 ),
		}
	backtest[ "energy_model_era5" ] = { "period": f"{test_days[0].date()} .. {test_days[-1].date()}",
										"components": component_skill, "sigma_logit": round( sigma_model, 3 ) }

	# --- climatology baseline built the fair way: ERA5 weather of all training years, today's fleet
	# (base rates fall as the fleet grows, so a plain historical frequency would be biased)
	train_days = days[ days <= TRAIN_END ]


	# Unit (fleet-independent) model output for every ERA5 day, and the share any fleet would have had
	unit_all = {}
	for component in COMPONENTS + ( "load", ):
		u = apply_linear( model[ component ], design( component, wx ).fillna( 0 ) )
		unit_all[ component ] = pd.Series( u if component == "load" else np.maximum( u, 0 ), index = days )

	def fleet_at( iss ):
		return { c: extrapolated_capacity( ratios[ c ], [ iss ], [ iss ] )[ 0 ] for c in COMPONENTS + ( "load", ) }

	def constant_fleet_share( sample_days, fleet, other ):
		gen = sum( unit_all[ c ].loc[ sample_days ] * fleet[ c ] for c in COMPONENTS )
		return ( gen + other ) / ( unit_all[ "load" ].loc[ sample_days ] * fleet[ "load" ] )

	clim_cache = {}
	train_doy = train_days.dayofyear.to_numpy()

	def clim_prob( target, iss, threshold ):
		"""P(Dunkelflaute) from the weather of all training years +-15 days around the target's day of year,
		with the fleet and other renewables known at the issue date: a fair, fleet-adjusted climatology."""
		key = ( iss.year, iss.month )
		if key not in clim_cache:
			other = other_trailing.reindex( [ iss - pd.Timedelta( days = 1 ) ] ).iloc[ 0 ]
			clim_cache[ key ] = constant_fleet_share( train_days, fleet_at( iss ), other ).to_numpy()
		window = np.abs( ( ( train_doy - target.dayofyear + 182 ) % 365 ) - 182 ) <= 15
		return float( ( clim_cache[ key ][ window ] <= threshold ).mean() )

	era5_probabilities = {}
	for threshold in THRESHOLDS:
		y = ( actual[ "re_share" ] <= threshold ).to_numpy()
		p = calibrated_probability( era5_logit, threshold, model[ "error" ] | { "sigma": sigma_model } )
		clim = np.array( [ clim_prob( t, i, threshold ) for t, i in zip( test_days, issue ) ] )
		mask = test_days > CALIBRATION_END
		era5_probabilities[ threshold ] = {
			"model": scores( p[ mask ], y[ mask ], clim[ mask ] ),
			"climatology": scores( clim[ mask ], y[ mask ], clim[ mask ] ),
		}
	backtest[ "era5_dunkelflaute" ] = { str( k ): v for k, v in era5_probabilities.items() }

	# --- 2) TSO day-ahead forecasts from SMARD as a strong lead-1 baseline
	tso = actual[ [ "forecast_onshore", "forecast_offshore", "forecast_pv", "forecast_load" ] ].dropna()
	tso_share = ( tso[ "forecast_onshore" ] + tso[ "forecast_offshore" ] + tso[ "forecast_pv" ]
				  + other_known( tso.index - pd.Timedelta( days = 1 ) ) ) / tso[ "forecast_load" ]
	tso_err = logit( actual.loc[ tso.index, "re_share" ] ) - logit( tso_share )
	tso_sigma = float( np.std( tso_err[ tso.index <= CALIBRATION_END ] ) )
	tso_bias = float( np.mean( tso_err[ tso.index <= CALIBRATION_END ] ) )

	# --- 3) real archived NWP forecasts, lead 1..7 days
	lead_scores = []
	forecast_series = []
	fc_path = DATA / "forecast_daily.csv"
	if fc_path.exists():
		fc = pd.read_csv( fc_path, parse_dates = [ "date" ] )
		fc[ "date" ] = fc[ "date" ].dt.normalize()
		model[ "forecast_model" ] = str( fc[ "model" ].iloc[ 0 ] )
		calib = {}
		for lead, group in fc.groupby( "lead" ):
			group = group.set_index( "date" ).sort_index()
			group = group[ group.index.isin( targets.index ) ].dropna()
			if len( group ) < 100:
				continue
			target_days = group.index
			iss = target_days - pd.Timedelta( days = int( lead ) )
			pred = reconstruct( group[ wx.columns ], iss, target_days, other_known( iss ) )
			obs = targets.loc[ target_days ]
			cal_mask = target_days <= CALIBRATION_END
			lp, lo = logit( pred[ "re_share" ] ), logit( obs[ "re_share" ] )
			b, a = np.polyfit( lp[ cal_mask ], lo[ cal_mask ], 1 ) if RECALIBRATE else ( 1.0, 0.0 )
			corrected = a + b * lp
			sigma = float( np.std( lo[ cal_mask ] - corrected[ cal_mask ] ) )
			# logistic calibration of the probabilities, shared by all thresholds (more events to fit on):
			# P = sigmoid( alpha + beta * (logit(threshold) - corrected) / sigma )
			z_cal = np.concatenate( [ ( logit( t ) - corrected[ cal_mask ] ) / sigma for t in THRESHOLDS ] )
			y_cal = np.concatenate( [ ( obs[ "re_share" ][ cal_mask ] <= t ).to_numpy() for t in THRESHOLDS ] )
			alpha, beta = fit_logistic( z_cal, y_cal )
			calib[ int( lead ) ] = { "a": float( a ), "b": float( b ), "sigma": sigma, "alpha": alpha, "beta": beta }
			eval_mask = ~cal_mask
			share_pred = 1 / ( 1 + np.exp( -corrected ) )
			row = { "lead": int( lead ), "days": int( eval_mask.sum() ),
					"mae_share": round( float( np.mean( np.abs( share_pred[ eval_mask ] - obs[ "re_share" ][ eval_mask ] ) ) ), 4 ),
					"sigma_logit": round( sigma, 3 ), "thresholds": {} }
			for threshold in THRESHOLDS:
				y = ( obs[ "re_share" ] <= threshold ).to_numpy()[ eval_mask ]
				p = calibrated_probability( corrected, threshold, calib[ int( lead ) ] )[ eval_mask ]
				p_gauss = probability_below( share_pred, threshold, sigma )[ eval_mask ]
				clim = np.array( [ clim_prob( t, i, threshold ) for t, i in zip( target_days[ eval_mask ], iss[ eval_mask ] ) ] )
				last_obs = targets[ "re_share" ].reindex( iss[ eval_mask ] - pd.Timedelta( days = 1 ) ).to_numpy()
				# probabilistic persistence: P(event | last observed day was / was not an event), from 2023 and 2024 (recent fleet)
				tr = targets.loc[ ( targets.index >= TEST_START ) & ( targets.index <= CALIBRATION_END ), "re_share" ]
				now_ev, later_ev = ( tr <= threshold ), ( tr.shift( -( int( lead ) + 1 ) ) <= threshold )
				p_if = float( later_ev[ now_ev ].mean() ) if now_ev.any() else 0.0
				p_ifnot = float( later_ev[ ~now_ev ].mean() )
				persistence = np.where( last_obs <= threshold, p_if, p_ifnot )
				entry = { "model": scores( p, y, clim ), "model_gaussian": scores( p_gauss, y, clim ),
						  "climatology": scores( clim, y, clim ),
						  "persistence": scores( persistence, y, clim ) }
				if int( lead ) == 1:
					tso_days = target_days[ eval_mask ].intersection( tso.index )
					tso_p = probability_below( 1 / ( 1 + np.exp( -( logit( tso_share.loc[ tso_days ] ) + tso_bias ) ) ),
											   threshold, tso_sigma )
					idx = target_days[ eval_mask ].get_indexer( tso_days )
					entry[ "tso_day_ahead" ] = scores( tso_p, y[ idx ], clim[ idx ] )
					entry[ "model_same_days" ] = scores( p[ idx ], y[ idx ], clim[ idx ] )
				if threshold == MAIN_THRESHOLD:
					entry[ "reliability" ] = reliability( p, y )
				row[ "thresholds" ][ str( threshold ) ] = entry
			lead_scores.append( row )
			if int( lead ) in ( 1, 3, 5, 7 ):
				forecast_series.append( { "lead": int( lead ), "dates": [ str( d.date() ) for d in target_days[ eval_mask ] ],
										  "predicted": np.round( share_pred[ eval_mask ], 4 ).tolist() } )
		model[ "forecast_calibration" ] = calib
	backtest[ "nwp_leads" ] = lead_scores
	backtest[ "series" ] = {
		"dates": [ str( d.date() ) for d in actual.index[ actual.index > CALIBRATION_END ] ],
		"actual": np.round( actual[ "re_share" ][ actual.index > CALIBRATION_END ], 4 ).tolist(),
		"era5_model": np.round( era5[ "re_share" ][ era5.index > CALIBRATION_END ], 4 ).tolist(),
		"forecasts": forecast_series,
	}

	# --- 4) weather regimes: Dunkelflaute rates and long-range skill
	mslp_path = DATA / "mslp_daily.csv"
	if mslp_path.exists():
		mslp = read_daily( "mslp_daily.csv" )
		labels, regime_params = regimes( mslp, pd.Series( mslp.index <= TRAIN_END, index = mslp.index ) )
		# Dunkelflaute indicator with a constant (current) fleet, so 2015-2022 rates are comparable
		# Dunkelflaute indicator with a constant (current) fleet, so all years' rates are comparable
		months_all = days.month.to_numpy()
		other_now = np.array( model[ "other_re" ][ "by_month" ] )[ months_all - 1 ]
		share_fleet_now = constant_fleet_share( days, fleet_at( days[ -1 ] ), other_now )
		common = labels.index.intersection( days )
		lab, share_now = labels.loc[ common ], share_fleet_now.loc[ common ]
		winter = common.month.isin( [ 10, 11, 12, 1, 2, 3 ] )
		regime_table = []
		for r in range( N_REGIMES ):
			m = ( lab == r ).to_numpy()
			mw = m & winter
			regime_table.append( {
				"id": r, "name": name_regime( regime_params[ "patterns" ][ r ] ),
				"frequency": round( float( m.mean() ), 3 ),
				"winter_frequency": round( float( mw.sum() / winter.sum() ), 3 ),
				"mean_share_winter": round( float( share_now[ mw ].mean() ), 3 ) if mw.any() else None,
				"df_rate_winter": { str( t ): round( float( ( share_now[ mw ] <= t ).mean() ), 3 ) for t in THRESHOLDS } if mw.any() else None,
				"persistence_days": round( float( 1 / max( 1e-3, 1 - np.mean( ( lab.shift( -1 ) == lab )[ m ] ) ) ), 1 ),
				"pattern": regime_params[ "patterns" ][ r ],
			} )
		for row, name in zip( regime_table, unique_names( [ row[ "name" ] for row in regime_table ] ) ):
			row[ "name" ] = name
		regime_params[ "table" ] = regime_table
		model[ "regimes" ] = { k: v for k, v in regime_params.items() if k != "patterns" }
		model[ "regimes" ][ "names" ] = [ row[ "name" ] for row in regime_table ]
		# long range: P(DF at d+L | regime at d, month) from training, vs monthly climatology, scored on test years
		long_range = []
		t = MAIN_THRESHOLD
		event = ( share_now <= t ).astype( float )
		for lead in ( 1, 2, 3, 5, 7, 10, 14, 21, 28 ):
			future = event.shift( -lead )
			df = pd.DataFrame( { "regime": lab, "month": common.month, "future": future } ).dropna()
			train_part, test_part = df[ df.index <= TRAIN_END ], df[ df.index > TRAIN_END ]
			cond = train_part.groupby( [ "regime", "month" ] )[ "future" ].mean()
			counts = train_part.groupby( [ "regime", "month" ] )[ "future" ].count()
			month_clim = train_part.groupby( "month" )[ "future" ].mean()
			k = 20.0  # shrink sparse regime-month cells towards the monthly climatology
			shrunk = ( cond * counts + month_clim.reindex( cond.index.get_level_values( 1 ) ).to_numpy() * k ) / ( counts + k )
			p = shrunk.reindex( list( zip( test_part[ "regime" ], test_part[ "month" ] ) ) ).to_numpy()
			c = month_clim.reindex( test_part[ "month" ] ).to_numpy()
			ok = ~np.isnan( p ) & ~np.isnan( c )
			long_range.append( { "lead": lead, **scores( p[ ok ], test_part[ "future" ].to_numpy()[ ok ], c[ ok ] ) } )
		backtest[ "regimes" ] = { "table": regime_table, "long_range": long_range,
								  "grid": { "lats": [ 35, 42, 49, 56, 63, 70 ], "lons": [ -30, -20, -10, 0, 10, 20, 30 ] } }
		# conditional climatology used live beyond the ensemble range
		model[ "regimes" ][ "df_rate_by_regime_month" ] = {
			str( t ): [ [ round( float( ( share_now[ ( lab == r ).to_numpy() & ( common.month == m ) ] <= t ).mean() ), 3 )
						  if ( ( lab == r ).to_numpy() & ( common.month == m ) ).sum() >= 10 else None
						  for m in range( 1, 13 ) ] for r in range( N_REGIMES ) ] for t in THRESHOLDS }
		model[ "climatology_df_rate_by_month" ] = {
			str( t ): [ round( float( ( share_now[ common.month == m ] <= t ).mean() ), 3 ) for m in range( 1, 13 ) ] for t in THRESHOLDS }

	model[ "tso_baseline" ] = { "sigma_logit": tso_sigma, "bias_logit": tso_bias }
	model[ "thresholds" ] = THRESHOLDS
	with open( HERE / "model.json", "w" ) as handle:
		json.dump( model, handle, indent = 1, default = float )
	with open( HERE / "backtest.json", "w" ) as handle:
		json.dump( backtest, handle, default = lambda v: None if isinstance( v, float ) and math.isnan( v ) else float( v ) )
	print( json.dumps( { k: v for k, v in backtest.items() if k not in ( "series", ) }, indent = 1, default = str )[ :20000 ] )


if __name__ == "__main__":
	main()
