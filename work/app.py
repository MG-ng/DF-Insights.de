import decimal
import json
from math import log

import requests
from flask import Flask, render_template, request, send_from_directory

from config import APP_DEBUG, APP_HOST, APP_PORT, APP_VERSION, CSP_ENFORCE
from Helper import REGION_LIST, FILTER, FilterTranslations, FLAG, Resolution, unix_time_duration
# These imports crash if app.py is in a separate folder, not seeing psqlDatabase/
from psqlDatabase.QueryComplex import get_timeseries, get_daily_price_ohlc
from psqlDatabase.dunkelflauteSearch import get_dunkelflaute_matches, get_dunkelflaute_timeseries, \
	getEnrichedDunkelflauten

# TODO: Change Server Configuration Path

app = Flask(__name__)


@app.context_processor
def inject_app_version():
	return {'app_version': APP_VERSION}


# Content Security Policy: only this site's own files, plus the two embedded iframes
# (Ventusky weather map, Google Slides) and the Website Carbon badge API.
# 'unsafe-inline' is still needed for the inline <script> blocks and onclick handlers
# in index.html and prediction.html; moving those into static/js would allow dropping it.
CONTENT_SECURITY_POLICY = "; ".join( [
	"default-src 'self'",
	"script-src 'self' 'unsafe-inline'",
	"style-src 'self' 'unsafe-inline'",
	"img-src 'self' data: blob:",
	"font-src 'self' data:",
	"connect-src 'self' https://api.websitecarbon.com",
	"frame-src https://embed.ventusky.com https://docs.google.com",
	"object-src 'none'",
	"base-uri 'self'",
	"form-action 'self'",
	"frame-ancestors 'none'",
] )
CSP_HEADER = "Content-Security-Policy" if CSP_ENFORCE else "Content-Security-Policy-Report-Only"


@app.after_request
def set_content_security_policy( response ):
	if response.mimetype == "text/html":
		response.headers.setdefault( CSP_HEADER, CONTENT_SECURITY_POLICY )
	return response

@app.route('/')
def index():
	return render_template('index.html',
							title='Dunkelflauten Research',
							message='Welcome to my website!',
							filters=FILTER,
							filtersInverse=json.dumps( dict(FILTER.inverse) ),
							filtersTranslation=json.dumps( dict(FilterTranslations) ),
							dataResolution=json.dumps( 'day' ),
							resolutions = json.dumps( Resolution.values() ),
						   )

@app.route('/api')
def api():
	filters = request.args.getlist( 'filters', type = int )  # filters contains the numeric ids
	if len([id for id in filters if (id not in FILTER.values())]) != 0:
		return "Data not available!", 404
	if not filters:  # no get parameters = filters
		filters.append( FILTER[ FilterTranslations.inverse[ "Power_Consumption_Residual_load" ] ] )
		filters.append( FILTER[ FilterTranslations.inverse[ "Power_Consumption_Total" ] ] )
	resolution = request.args.get( 'resolution', Resolution.DAY.value, type = str )
	region = request.args.get( 'region', "DE", type = str )
	if resolution not in Resolution.values() or region not in REGION_LIST:
		return "Data not available2", 404
	start_ms = request.args.get( 'startTime', 1000000000000, type = int )  # 9. September 2001
	end_ms = request.args.get( 'endTime', 2000000000000, type = int )  # 18. May 2033
	if start_ms < 0 or end_ms <= 0 or start_ms > end_ms or end_ms > 2000000000000:
		return "Data not available3", 404

	chartDurationDays = (end_ms - start_ms)/1000/60/60/24  # ms->s->m->h->d
	if resolution in [Resolution.HOUR.value, Resolution.QUARTERHOUR.value] and chartDurationDays > 365*2:
		resolution = Resolution.DAY.value

	rows, columns = get_timeseries( region, resolution, filters, start_ms, end_ms )

	if rows is None:
		return {'ordering': [], 'default': {'resolution': None, 'region': None}, 'series': []}
	newRows = []
	# print( f"{rows =}" )
	for row in rows:
		newRow = []
		newRow.append( row[0] )  # timestamp

		# The chart needs more adjustments for correct string placements
		# newRow.append( row[1] )  # region
		# newRow.append( row[2] )  # resolution
		# TypeError: Object of type Decimal is not JSON serializable,
		# But you know that the first 3 values are: unix_timestamp_ms, region, resolution
		containsContent = False
		for value in row[3:]:
			if value is None or value == FLAG:
				newRow.append( None )
			else:
				containsContent = True
				if isinstance( value, decimal.Decimal ):
					newRow.append( float(value) )  # rounding errors are negligible
				else:
					print( f"ERROR with: {row = }" )
					print( f"UNKNOWN TYPE: {type(value) = }" )
					print( f"{value = }" )

		if containsContent:
			newRows.append( newRow )

	# The charts need the data sorted by time
	newRows.sort( key = lambda row: row[ 0 ] )

	return {'ordering': columns, 'default': {'resolution': resolution, 'region': region}, 'series': newRows}



@app.route('/search')
def search():
	region = request.args.get( 'region', "DE", type = str )
	resolution = request.args.get( 'resolution', Resolution.DAY.value, type = str )
	if resolution not in Resolution.values() or region not in REGION_LIST:
		return "Data not available", 404

	start_ms = request.args.get( 'startTime', 1000000000000, type = int )  # 9. September 2001
	end_ms = request.args.get( 'endTime', 2000000000000, type = int )  # 18. May 2033
	if start_ms < 0 or end_ms <= 0 or start_ms > end_ms or end_ms > 2000000000000:
		return "Data not available", 404

	threshold = request.args.get( 'maxShare', 0.3, type = float )  # 30%
	unix_duration = request.args.get( 'min_duration_ms', unix_time_duration(1, Resolution.DAY), type = int )  # 1 day
	if threshold < 0 or unix_duration < 0 or threshold > 1 or unix_duration > unix_time_duration(4, Resolution.WEEK):
		return "Data not available", 404

	print( "Matches for: ", resolution, region, threshold, unix_duration, start_ms, end_ms)

	rows, columns = get_dunkelflaute_matches( region, resolution, threshold, unix_duration, start_ms, end_ms )
	print( f"Dunkelflaute: {rows = } & {columns = }" )

	if rows is None:
		return { 'ordering': [], 'default': {'resolution': None, 'region': None}, 'series': [] }
	newRows = []
	for row in rows:
		newRow = []
		newRow.append( row[0] )  # start_time
		# newRow.append( row[1] )  # region
		# newRow.append( row[2] )  # resolution
		newRow.append( row[3] )  # end_time
		newRows.append( newRow )

	return { 'ordering': columns, 'default': {'resolution': resolution, 'region': region}, 'series': newRows }


@app.route('/trend')
def trend():
	resolution = request.args.get( 'resolution', Resolution.DAY.value, type = str )
	region = request.args.get( 'region', "DE", type = str )
	if resolution not in Resolution.values() or region not in REGION_LIST:
		return "Data not available", 404

	start_ms = request.args.get( 'startTime', 1000000000000, type = int )  # 9. September 2001
	end_ms = request.args.get( 'endTime', 2000000000000, type = int )  # 18. May 2033
	if start_ms < 0 or end_ms <= 0 or start_ms > end_ms or end_ms > 2000000000000:
		return "Data not available", 404

	threshold = request.args.get( 'maxShare', 0.3, type = float )  # 30%
	unix_duration = request.args.get( 'min_duration_ms', unix_time_duration(1, Resolution.DAY), type = int )  # 1 day
	if threshold < 0 or unix_duration < 0 or threshold > 1 or unix_duration > unix_time_duration(4, Resolution.WEEK):
		return "Data not available", 404

	print( "Trendline for: ", resolution, region, threshold, unix_duration, start_ms, end_ms)

	rows, columns = get_dunkelflaute_timeseries( region, resolution, threshold, unix_duration, start_ms, end_ms )
	if rows is None:
		return { 'ordering': [], 'default': {'resolution': None, 'region': None}, 'series': [] }
	# newRows.sort( key = lambda row: row[ 0 ] )  # Already sorted using SQL
	return {'ordering': columns, 'default': {'resolution': resolution, 'region': region}, 'series': rows}


@app.route('/ohlc')
def ohlc():
	"""Daily candles (open, high, low, close) of the hourly day-ahead prices of one market price filter."""
	filter_id = request.args.get( 'filter', FILTER[ FilterTranslations.inverse[ "Market_Price_GER_LUX" ] ], type = int )
	if filter_id not in FILTER.values() or not FILTER.inverse[ filter_id ].startswith( "Marktpreis" ):
		return "Data not available!", 404
	region = request.args.get( 'region', "DE", type = str )
	if region not in REGION_LIST:
		return "Data not available2", 404
	start_ms = request.args.get( 'startTime', 1000000000000, type = int )  # 9. September 2001
	end_ms = request.args.get( 'endTime', 2000000000000, type = int )  # 18. May 2033
	if start_ms < 0 or end_ms <= 0 or start_ms > end_ms or end_ms > 2000000000000:
		return "Data not available3", 404

	filter_name = FilterTranslations[ FILTER.inverse[ filter_id ] ]
	rows, columns = get_daily_price_ohlc( region, filter_name, start_ms, end_ms )
	if not rows:
		return {'ordering': [], 'name': filter_name, 'series': []}
	series = [ [ row[0] ] + [ float(value) for value in row[1:] ] for row in rows ]
	return {'ordering': columns, 'name': filter_name, 'series': series}


@app.route('/enrichedDF')
def enrichedDF():
	tableName = request.args.get( 'tableName', "computed_data_dunkelflauten_enriched30", type = str )
	if tableName not in ["computed_data_dunkelflauten_enriched" + str(percent) for percent in
						 [10, 15, 20, 25, 30, 35, 40, 45, 50, 55]]:
		return "Data not available", 404
	rows, columns = getEnrichedDunkelflauten( tableName )

	return {'ordering': columns, 'series': rows}


@app.route('/robots.txt')
def robots_txt():
	return send_from_directory( app.static_folder, 'robots.txt', mimetype = 'text/plain' )

@app.route('/.well-known/security.txt')
def security_txt():
	"""Where to report security issues (RFC 9116). Renew the Expires date in the file at least once a year."""
	return send_from_directory( app.static_folder, 'well-known/security.txt', mimetype = 'text/plain' )


@app.route('/features')
def features():
	return render_template('features.html', title='Features')

@app.route('/usage')
def usage():
	return render_template('usage.html', title='Usage')

@app.route('/prediction')
def prediction():
	return render_template('prediction.html', title='prediction')

@app.route('/trade')
def trade():
	return render_template('trade.html', title='Trading the Power Price')

@app.route('/about')
def about():
	return render_template('about.html', title='About Us')

def wind_speed_100m( w80, w120 ):
	"""Log-law interpolation of the wind speed at 100 m from the 80 m and 120 m values (same formula as the SQL view):
	(avg( wind_speed_80m ) * POWER( 100.0 / 80.0, LN( avg( wind_speed_120m ) / avg( wind_speed_80m ) )
										/ LN( 120.0 / 80.0 ) ))::DECIMAL( 6, 3 ) as wind_100m_log
	The log law needs both speeds > 0. In calm air (a speed of 0) it falls back to the linear mean,
	and a missing value (None) stays missing."""
	if w80 is None or w120 is None:
		return None
	if w80 <= 0 or w120 <= 0:
		return (w80 + w120) / 2.0
	return w80 * pow( 100.0/80.0, log( w120/w80 ) / log( 120.0/80 ) )


def average( values ):
	"""Mean of the values that are not None, None if there are none."""
	values = [ value for value in values if value is not None ]
	return sum( values ) / len( values ) if values else None


@app.route('/forecast')
def forecast():
	try:
		response = requests.get("https://api.open-meteo.com/v1/forecast?latitude=54,54,54,52,52,52,50,50,50,48,48,48&longitude=7,10,13,7,10,13,7,10,13,7,10,13&hourly=wind_speed_120m,wind_speed_80m,direct_radiation,diffuse_radiation&models=icon_global&timeformat=unixtime&wind_speed_unit=ms",
								timeout = 10 )
		response.raise_for_status()
		data = response.json()
	except (requests.RequestException, ValueError) as error:
		print( f"Forecast: Open-Meteo request failed: {error}" )
		return "API Error", 502

	try:
		wind_locations = [loc for loc in data if loc["latitude"] > 51]
		solar_locations = [loc for loc in data if loc["latitude"] < 52]

		for wind_location in wind_locations:
			w120 = wind_location["hourly"]["wind_speed_120m"]
			w80 = wind_location["hourly"]["wind_speed_80m"]
			wind_location["hourly"]["wind_speed_100m"] = [ wind_speed_100m( w80, w120 )
														   for w80, w120 in zip(w80, w120) ]  # calculate new 100m height

		repis = {}
		for index, timestamp in enumerate(data[0]["hourly"]["time"]):
			wind_speed_100m_avg = average( location[ "hourly" ][ "wind_speed_100m" ][ index ] for location in wind_locations )
			direct_radiation_avg = average( location[ "hourly" ][ "direct_radiation" ][ index ] for location in solar_locations )
			diffuse_radiation_avg = average( location[ "hourly" ][ "diffuse_radiation" ][ index ] for location in solar_locations )
			if None in (wind_speed_100m_avg, direct_radiation_avg, diffuse_radiation_avg):
				continue  # no usable value at this hour

			"""round( (least( wind.wind_speed_100_avg, 11 ) ^ 3
					+ (radiation.direct_radiation_avg) * 2
					+ (radiation.diffuse_radiation_avg) * 2
					)::Decimal( 8, 4 ), 2 ) AS repi_power1avg2"""
			repis[timestamp] = round( min( wind_speed_100m_avg, 11.0 )**3
									  + direct_radiation_avg * 2
									  + diffuse_radiation_avg * 2, 2 )
	except (KeyError, IndexError, TypeError) as error:
		print( f"Forecast: unexpected Open-Meteo response: {error!r}" )
		return "API Error", 502
	return { "REPIs": repis }

if __name__ == '__main__':
	app.run(host=APP_HOST, port=APP_PORT, debug=APP_DEBUG)
