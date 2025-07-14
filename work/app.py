import json

from flask import Flask, render_template, request
from Helper import REGION_LIST, FILTER, TABLE_NAME, DB_PARAMS, FilterTranslationsList, FilterTranslations, FLAG
from QueryComplex import get_smard_timeseries
from decimal import Decimal

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html',
                            title='Dunkelflauten Research',
                            message='Welcome to my website!',
                            filters=FILTER,
                            filtersInverse=json.dumps( dict(FILTER.inverse) ),
                            filtersTranslation=json.dumps( dict(FilterTranslations)),
                            dataResolution=json.dumps( 'day' ) )

@app.route('/api')
def api():
    filters = request.args.getlist( 'filters', type = int )
    if not filters:  # no get parameters = filters
        filters.append( FILTER[ FilterTranslations.inverse[ "Power_Consumption_Residual_load" ] ] )
        filters.append( FILTER[ FilterTranslations.inverse[ "Power_Consumption_Total" ] ] )
    resolution = request.args.get( 'resolution', "day", type = str )

    # TODO: sanitise the URL get parameters instead of Internal Server Error (KeyError) to keep avoiding SQL injection
    filterNames = [ FilterTranslations[ FILTER.inverse[ id ] ] for id in filters  ]
    rows, columns = get_smard_timeseries( resolution, filterNames )

    # TypeError: Object of type Decimal is not JSON serializable
    # But you know that the first 3 values are: unix_timestamp_ms, region, resolution
    newRows = []
    for i, row in enumerate( rows ):
        newRow = []
        newRow.append( row[0] )  # timestamp

        # High Chart needs more adjustments for correct string placements
        # newRow.append( row[1] )  # region
        # newRow.append( row[2] )  # resolution

        row = row[ 3: ]
        containsContent = False
        for value in row:
            if value is None or value == FLAG:
                newRow.append( None )
                continue
            containsContent = True
            newRow.append( float(value) )  # rounding errors are negligible

        if containsContent:
            newRows.append( newRow )

    # Highcharts needs data to be sorted for performance reasons
    newRows.sort( key = lambda row: row[ 0 ] )

    return {'ordering': columns, 'series': newRows}


@app.route('/about')
def about():
    return render_template('about.html', title='About Us')

@app.route('/features')
def features():
    return render_template('features.html', title='Features')

if __name__ == '__main__':
    app.run(debug=True)