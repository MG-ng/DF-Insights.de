"use strict";

import {toast} from "./script.js";
import {filters, cma_options, reloadData, resolutions, translations} from "./flask_variables.js";
export { timeChart, selectorFilter, selectorRes, cma_selector, cma_replacement, dunkelflauteColor, Match, timeShares }

let timeChart
var timeShares
var dunkelflauteColor = "#DD224422"
window.cma_replacement = cma_replacement

console.log("Executing Setup Home……")


Highcharts.getJSON('/api', function(data) {
    var grid_load = data['series'].map(triple => {
        return [triple[0], triple[2]]
    })
    // Calculating a virtual percentage/max_share line of (wind+solar) on total demand if resLoad + gridLoad are available
    if( data['ordering'][3] === 'power_consumption_residual_load'
        && data['ordering'][4] === 'power_consumption_total' ) {
        console.log("Drawing computed percentage/max_share line of (wind+solar)")

        timeShares = data['series'].map(triple => {
            return [triple[0], 1- (triple[1] / triple[2])]
        })
    }

    // TODO: "Die Erzeugungsdaten beziehen sich auf die Erzeugung innerhalb Deutschlands und wurden
    //  von der Bundesnetzagentur über ihr Portal SMARD bereitgestellt. Nur der importierte Strom stammt
    //  aus eigenen Berechnungen und entspricht der Differenz von Neztlast und Erzeugung."
    // By: https://dunkelflauten-guide.smc.page/
    // So berechnen zum Beispiel das Fraunhofer ISE auch die Einspeisung von Kraftwerken oder Anlagen
    // kleiner als 50MW – diese werden von der EEx nicht erfasst. Zudem unterscheiden sich die beiden Datensätze
    // in den Zeitpunkten, zu dem sie neu installierte EE-Anlagen aufführen. Prinzipiell kann unser Tool
    // beide Datensätze einsetzen, so dass ein Vergleich möglich ist. Im ersten Schritt haben wir uns dabei
    // auf die SMARD-Daten konzentriert, die Energy-Charts-Werte werden wir in einem späteren Update einpflegen.

    // Für die Auswertung haben wir den Datensatz etwas aufgearbeitet. So berechnen wir zum Beispiel
    // die in unregelmäßigen Abständen durch Inbetriebnahme neuer Windkraft- und PV-Anlagen steigende installierte
    // Leistung dadurch, dass wir für ein Jahr den Durchschnitt aus der installierten Leistung am Jahresanfang
    // und am Jahresende bilden. Dadurch liegt prinzipiell die Leistung in der ersten Jahreshälfte etwas zu hoch,
    // in der zweiten etwas zu niedrig.

    var chartMinX = 0, chartMaxX = 0
    timeChart = Highcharts.stockChart('container', {
        yAxis: [{ // Primary y-axis (index 0)
            title: {text: 'Prices (€/MWh)'},
            labels: {
                style: {color: '#FF0000'}
            },
            opposite: false // Places it on the left side
        }, {// Secondary y-axis (index 1)
            title: {text: 'Electric Energy (MWh)'},
            labels: {style: {color: '#0000FF'}},
            visible: true,
            opposite: true // Places it on the right side
        }, {// Third y-axis (index 2)
            title: {text: 'Percentage'},  // Dimensionless 0-100% for residual generation max_share
            labels: {style: {color: '#00FF00'}},
            opposite: true // Places it on the right side
        }],
        xAxis: {
            title: {text: 'Date'},
            ordinal: false,
            crosshair: true,
            events: {
                afterSetExtremes: function(e) {
                    var chartDurationDays = (this.max - this.min)/1000/60/60/24  // ms->s->m->h->d
                    if( !selectorRes.getValue() ){
                        // default case in the beginning, no resolution selected
                    } else if( selectorRes.getValue() === selectorRes.options.quarterhour.value
                                || selectorRes.getValue() === selectorRes.options.hour.value ) {
                        if( chartDurationDays > 365*2 ) {
                            selectorRes.setValue(selectorRes.options.day.value)
                        }
                        reloadData()
                    }
                }
            }
        },
        rangeSelector: {
            selected: 4  // selects the zoom level index in the top left of the chart element
        },
        series: [{
            name: "Share_of_Renewable_Energies_Computed",
            data: timeShares,
            tooltip: { pointFormatter: function (fStr) {
                    // fStr = <span style="color:{point.color}">●</span> {series.name}: <b>{point.y}</b><br/>
                    var retStr = fStr.replace('{point.color}', this["color"])
                    retStr = retStr.replace('{series.name}', this.series.name)
                    var percent = (this.y * 100).toFixed(0) + " %"
                    retStr = retStr.replace('{point.y}', percent)
                    return retStr
                },
            },
            yAxis: 2,
            color: "#00FF00",  // green
            // visible: true
        },{
            name: 'Residual Load',
            data: data['series'],
            tooltip: {
                valueDecimals: 2
            }
        }, {
            name: 'Total Grid Load',
            data: grid_load,
            tooltip: {
                valueDecimals: 2
            }
        }],
        plotOptions: {
            column: {
                events: {
                    legendItemClick: function (col) {
                        if (col.target.index === 0) {
                            $(timeChart.series).each(function () {
                                if (this.index !== 0) {
                                    // this.setVisible(false, false);
                                    console.log("Clicked!")
                                }
                            });
                            return false;
                        }
                    }
                }
            }
        }, legend: {
            enabled: true
        },
        function() {
            const timeChart = this;
            Highcharts.addEvent(
                timeChart.container,
                document.onmousewheel === undefined ? 'DOMMouseScroll' : 'mousewheel',
                function (event) {
                    const axis = timeChart.xAxis[0],
                        extremes = axis.getExtremes(),
                        min = extremes.min,
                        max = extremes.max,
                        range = max - min,
                        precision = range / 150,
                        e = timeChart.pointer.normalize(event)

                    let delta = e.deltaY, prevent = true

                    if (timeChart.isInsidePlot(e.chartX - chart.plotLeft, e.chartY - chart.plotTop)) {
                        const proportion = (e.chartX - timeChart.plotLeft) / timeChart.plotWidth
                        axis.setExtremes(min + proportion * delta * precision, max)

                        // Crosshair handling logic
                        timeChart.yAxis.forEach(axis => {
                            if (!(axis.pos < e.chartY && axis.pos + axis.len > e.chartY) && timeChart.hoverPoint && axis.cross) {
                                delete axis.cross.e
                            }
                        })

                        if (prevent) {
                            if (e) {
                                if (e.preventDefault) {
                                    e.preventDefault()
                                }
                                if (e.stopPropagation) {
                                    e.stopPropagation()
                                }
                                e.cancelBubble = true
                            }
                        }
                    }
                }
            )
        }
    })
})

/**
 * Tom Filter Selector for Big Chart Display
 *
 * */
// console.log(  filters  )  // { filter-id: german-filter-name
// console.log( translations )  // {german-filter-name: english-filter-name}

var filterClasses = [
    {
        value: 'price_EUR_MWh',
        label: 'Prices in EUR/MWh',
        label_scientific: 'Electricity Market Prices provided by SMARD'
    },
    {
        value: 'elec_MWh',
        label: 'Electric Energy in MWh',
        label_scientific: 'Electricity during this given time resolution'
    },
    {
        value: 'computed',
        label: 'Virtual Computed Timeseries',
        label_scientific: 'Various units depending on the calculation'
    }
]

var options = [];
for (var filter in filters) {
    // console.log(filter, filters[filter])
    options.push({  // TODO: Enhance logic
        class: filters[filter].includes("Marktpreis") ? filterClasses[0].value :
            filters[filter].includes("Computed") ? filterClasses[2].value :
                filterClasses[1].value,
        value: filter,
        label: translations[filters[filter]],
        label_scientific: filters[filter]
    })
}

// console.log(options)
// console.log(filterClasses)

const selectorFilter = new TomSelect('#select-filter', {
    create: false,           // No item creation at all
    createOnBlur: false,     // Don't create when losing focus
    allowEmptyOption: false, // Don't allow empty selections
    maxItems: 10,            // Only allow single selection (optional)
    onChange: reloadData(),
    options: options,
    optgroups: filterClasses,
    optgroupField: 'class',
    labelField: 'label',
    searchField: ['label'],
    render: {
        optgroup_header: function (data, escape) {
            return '<div class="optgroup-header">' + escape(data.label) + ' <span class="scientific">' + escape(data.label_scientific) + '</span></div>';
        }
    }
})

const selectorRes = new TomSelect('#select-resolution', {
    create: false,           // No item creation at all
    createOnBlur: false,     // Don't create when losing focus
    allowEmptyOption: false, // Don't allow empty selections
    maxItems: 1,            // Only allow single selection (optional)
    onChange: reloadData(),
    onDelete: function() {
        // Prevent deletion if it would leave no items
        if (this.items.length < 1) {
            toast('You must have at least one selected item.');
            return false; // Prevent deletion
        }
        return true;
    },
    options: resolutions.map( resolution => ({
        value: resolution,
        text: resolution.toUpperCase()
    })),
    onInitialize: function(){
        if (!this.getValue() && this.options.day) {
            this.addItem(this.options.day.value, true)  // Ensure at least one item is selected on initialization
        }
	}
})


/**
 * Centered Mean Average Calculation
 */
function cma_replacement () {
    var cmaFiltersNew = cma_selector.items.map(item => {return })
    var cmaFilters = []
    for (var selected_cma_index in cma_selector.items) {
        var filterID = cma_selector.items[selected_cma_index]
        console.log(filterID)
        cmaFilters.push(filterID)
    }
    if(cmaFilters.length === 0) { toast(" No timeseries to smooth selected! "); return; }

    for (var seriesIndex in timeChart.series) {
        // Example: var results = array.filter(function(x) { return x.ID == 3 });
        var name = timeChart.series[seriesIndex]["name"]
        if (cmaFilters.includes(name)) {
            console.log("Found match: " + name)
        } else {
            if( cma_selector.options[name] ) {  // computed graph lines aren't in the selector
                timeChart.series[seriesIndex].setData(cma_selector.options[name].data)
            }
            continue
        }
        // Having trouble with this as this doesn't return the date (NaN and sometimes not all list entries
        // timeChart.series[seriesIndex].options.data  // list of objects with x and y attributes
        console.log(cma_selector.options)
        var timedValues = cma_selector.options[name].data  // list of objects with x and y attributes
        var preservedValues = timedValues.slice()

        console.log("timedValues")
        console.log( timedValues )
        console.log("Period: " + period)

        // "To memorize this, remember that (a, b) => a - b sorts numbers in ascending order"
        timedValues.sort( (a, b) => { return a[0]-b[0] })

        var MOVINGWINDOW = timedValues.splice( 0, period )
        const average = (array) => array.reduce((a, b) => a + b) / array.length;
        var newShorterTime = []
        var newTimedValue = timedValues.shift()

        while( timedValues && timedValues.length && newTimedValue ) {
            newShorterTime.push([ Math.round( average( MOVINGWINDOW.map( timedValue => {
                // console.log(timedValue)
                return timedValue[0]
            } ) ) ), average( MOVINGWINDOW.map( timedValue => timedValue[1] ) ) ] )
            // console.log("newShorterTime")
            // console.log(newShorterTime)
            // console.log("timedValues")
            // console.log(timedValues)
            MOVINGWINDOW.push( newTimedValue )
            do{ newTimedValue = timedValues.shift() }
            while( !newTimedValue && timedValues )
            MOVINGWINDOW.shift()
            // console.log(MOVINGWINDOW)
        }
        timeChart.series[seriesIndex].setData( newShorterTime )
        cma_selector.options[name].data = preservedValues
    }
}


const cma_selector = new TomSelect('#select-cma', {
    create: false,           // No item creation at all
    createOnBlur: false,     // Don't create when losing focus
    allowEmptyOption: false, // Don't allow empty selections
    maxItems: 10,            // Only allow single selection (optional)
    options: cma_options,
    optgroups: filterClasses,
    optgroupField: 'class',
    labelField: 'label',
    searchField: ['label'],
    render: {
        optgroup_header: function (data, escape) {
            return '<div class="optgroup-header">' + escape(data.label) + ' <span class="scientific">' + escape(data.label_scientific) + '</span></div>';
        }
    }
});


class Match {
    constructor(begin, end, matchedShares) {
        this.begin = begin
        this.end = end
        this.matchedShares = matchedShares
        this.clientSearch = true
    }
    plotBand() {
        return {from: this.begin, to: this.end, color: dunkelflauteColor, id: "same"}  // for unified removal
    }
    seriousness() {
        console.log( "Calculation of matchedShares" )
        // console.log( matchedShares )
    }
}



