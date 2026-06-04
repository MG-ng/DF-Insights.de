import decimal
import json
import numbers
from math import log
from decimal import Decimal
from sys import float_repr_style

import requests
# Switch from Highcharts to Plotly for future Graphs in commercial product because of Licensing!
# Plotly is free, but bigger (3.5MB vs 385kB) => GZIP compression needed
from flask import Flask, render_template, request
from numpy.matlib import empty

from Helper import REGION_LIST, FILTER, FilterTranslations, FLAG, Resolution, unix_time_duration, repi_power1avg2_ID
# These imports crash if app.py is in a separate folder, not seeing psqlDatabase/
from psqlDatabase.QueryComplex import get_smard_timeseries, get_timeseries
from psqlDatabase.dunkelflauteSearch import get_dunkelflaute_matches, get_dunkelflaute_timeseries, \
	getEnrichedDunkelflauten

## TODO: Change Server Configuration Path

app = Flask(__name__)

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
		return "Data not available1", 404
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

		# High Chart needs more adjustments for correct string placements
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

	# Highcharts needs data to be sorted for performance reasons
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


@app.route('/enrichedDF')
def enrichedDF():
	tableName = request.args.get( 'tableName', "computed_data_dunkelflauten_enriched30", type = str )
	if tableName not in ["computed_data_dunkelflauten_enriched" + str(percent) for percent in
						 [15, 20, 25, 30, 35, 40, 45, 50, 55]]:
		return "Data not available", 404
	rows, columns = getEnrichedDunkelflauten( tableName )

	return {'ordering': columns, 'series': rows}


@app.route('/features')
def features():
	return render_template('features.html', title='Features')

@app.route('/usage')
def usage():
	return render_template('usage.html', title='Usage')

@app.route('/prediction')
def prediction():
	return render_template('prediction.html', title='prediction')

@app.route('/about')
def about():
	return render_template('about.html', title='About Us')

@app.route('/forecast')
def forecast():
	response = requests.get("https://api.open-meteo.com/v1/forecast?latitude=54,54,54,52,52,52,50,50,50,48,48,48&longitude=7,10,13,7,10,13,7,10,13,7,10,13&hourly=wind_speed_120m,wind_speed_80m,direct_radiation,diffuse_radiation&models=icon_global&timeformat=unixtime&wind_speed_unit=ms")
	if response.status_code != 200:
		return "API Error"
	try:
		data = response.json()
	except Exception:
		return "API Error"
	wind_locations = [loc for loc in data if loc["latitude"] > 51]
	wind_locations_amount = len(wind_locations)
	solar_locations = [loc for loc in data if loc["latitude"] < 52]
	solar_locations_amount = len(solar_locations)

	for wind_location in wind_locations:
		"""(avg( wind_speed_80m ) * POWER( 100.0 / 80.0, LN( avg( wind_speed_120m ) / avg( wind_speed_80m ) )
										/ LN( 120.0 / 80.0 ) ))::DECIMAL( 6, 3 ) as wind_100m_log"""
		w120 = wind_location["hourly"]["wind_speed_120m"]
		w80 = wind_location["hourly"]["wind_speed_80m"]
		wind_location["hourly"]["wind_speed_100m"] = [(w80 * pow( 100.0/80.0, log( w120/w80 ) / log( 120.0/80 ) ))
													  for w80, w120 in zip(w80, w120) ]  # calculate new 100m height


	repis = {}
	for index, timestamp in enumerate(data[0]["hourly"]["time"]):

		wind_speed_100m_sum = sum( [ wind_locations[ location ][ "hourly" ][ "wind_speed_100m" ][ index ]
										  for location in range( wind_locations_amount ) ] )
		wind_speed_100m_avg = wind_speed_100m_sum / wind_locations_amount * 1.0

		direct_radiation_sum = sum( [ solar_locations[ location ][ "hourly" ][ "direct_radiation" ][ index ]
										  for location in range( solar_locations_amount ) ] )
		direct_radiation_avg = direct_radiation_sum / solar_locations_amount * 1.0

		diffuse_radiation_sum = sum( [ solar_locations[ location ][ "hourly" ][ "diffuse_radiation" ][ index ]
										  for location in range( solar_locations_amount ) ] )
		diffuse_radiation_avg = diffuse_radiation_sum / solar_locations_amount * 1.0

		"""round( (least( wind.wind_speed_100_avg, 11 ) ^ 3
				+ (radiation.direct_radiation_avg) * 2
				+ (radiation.diffuse_radiation_avg) * 2
				)::Decimal( 8, 4 ), 2 ) AS repi_power1avg2"""

		repis[timestamp] = round( min( wind_speed_100m_avg, 11.0 )**3
								  + direct_radiation_avg * 2
								  + diffuse_radiation_avg * 2, 2 )
	return { "REPIs": repis }

if __name__ == '__main__':
	app.run(debug=True)