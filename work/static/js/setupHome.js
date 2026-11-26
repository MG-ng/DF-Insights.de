"use strict";

import {toast, apiToChartTime} from "./script.js";
import { TimeChart } from "./plotlyTimeChart.js";
import {filters, cma_options, reloadData, resolutions, translations} from "./flask_variables.js";
export { timeChart, selectorFilter, selectorRes, cma_selector, cma_replacement, dunkelflauteColor, Match, timeShares }

let timeChart
var timeShares
var dunkelflauteColor = "#DD224422"
window.cma_replacement = cma_replacement

console.log("Executing Setup Home……")


timeChart = new TimeChart('container', {
    // id: axis options; the order decides which axis is drawn first on its side
    0: { title: 'Prices (€/MWh)', color: '#FF0000', side: 'left' },
    1: { title: 'Electric Energy (MWh)', color: '#0000FF', side: 'right' },
    2: { title: 'Percentage', color: '#00AA00', side: 'right', tickformat: '.0%', hoverformat: '.0%' },
    'wind-speed_y-axis': { title: 'Wind Speed (m/s)', visible: false },
    'solar-radiation_y-axis': { title: 'Solar Radiation (W/m²)', visible: false },
    'repi_y-axis': { title: 'REPI', visible: false },
}, {
    initialRangeMs: 365 * 24 * 60 * 60 * 1000,  // like the former rangeSelector "1y" preselection
    onRangeChange: (minMs, maxMs) => {
        // Hourly data is only delivered for the visible window (max. 2 years), switch to daily data when zooming out
        const chartDurationDays = (maxMs - minMs) / 1000 / 60 / 60 / 24  // ms->s->m->h->d
        const resolution = selectorRes.getValue()
        if ((resolution === 'quarterhour' || resolution === 'hour') && chartDurationDays > 365 * 2) {
            selectorRes.setValue('day')  // triggers the reload via onChange
        }
    }
})

fetch('/api')
    .then(response => response.json())
    .then(data => {
        data['series'].forEach(row => { row[0] = apiToChartTime(row[0]) })  // epoch seconds -> ms
        var grid_load = data['series'].map(triple => [triple[0], triple[2]])
        var residual_load = data['series'].map(triple => [triple[0], triple[1]])
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

        if (timeShares) timeChart.addSeries({ name: "Share_of_Renewable_Energies_Computed", data: timeShares, yAxis: 2, color: "#00CC00" })
        timeChart.addSeries({ name: 'Residual Load', data: residual_load, yAxis: 1, color: '#2CAFFE' })
        timeChart.addSeries({ name: 'Total Grid Load', data: grid_load, yAxis: 1, color: '#544FC5' })
    })
    .catch(error => {
        console.error(error)
        toast("Loading Error! Contact the site maintainer.")
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
        value: 'weather_data',
        label: 'Weather Data in W/m^2 or m/s',
        label_scientific: 'Solar Radiation, Wind Speed'
    },
    {
        value: 'repi_tests',
        label: 'REPI Dimensionless Number',
        label_scientific: 'Renewable Energy Production Index'
    },
    {
        value: 'computed',
        label: 'Virtual Computed Timeseries',
        label_scientific: 'Various units depending on the calculation'
    }
]

function formatFilterName(filterName) {
    return filterName
        .split('_')
        .map(word => {
            if( word === "of" || word === "to" ) { return word }
            return word.charAt(0).toUpperCase() + word.slice(1)
        })
        .join(' ');
}

var options = [];
for (var filter in filters) {
    // console.log(filter, filters[filter])
    options.push({  // TODO: Enhance logic
        class: filters[filter].includes("Marktpreis") ? 'price_EUR_MWh' :
            filters[filter].includes("Computed") ? 'computed' :
                filters[filter].includes("Weather") ? 'weather_data' :
                    filters[filter].includes("REPI") ? 'repi_tests' :
                        filterClasses[1].value,
        value: filter,
        label: formatFilterName(translations[filters[filter]]),
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

    for (const series of timeChart.series.slice()) {
        var name = series.name
        if (cmaFilters.includes(name)) {
            console.log("Found match: " + name)
        } else {
            if( cma_selector.options[name] ) {  // computed graph lines aren't in the selector
                timeChart.setSeriesData(name, cma_selector.options[name].data)
            }
            continue
        }
        var timedValues = cma_selector.options[name].data.slice()  // list of [timestamp, value]
        console.log("Period: " + period)

        // "To memorize this, remember that (a, b) => a - b sorts numbers in ascending order"
        timedValues.sort( (a, b) => { return a[0]-b[0] })

        var MOVINGWINDOW = timedValues.splice( 0, period )
        const average = (array) => array.reduce((a, b) => a + b) / array.length;
        var newShorterTime = []
        var newTimedValue = timedValues.shift()

        while( timedValues && timedValues.length && newTimedValue ) {
            newShorterTime.push([ Math.round( average( MOVINGWINDOW.map( timedValue => timedValue[0] ) ) ),
                average( MOVINGWINDOW.map( timedValue => timedValue[1] ) ) ] )
            MOVINGWINDOW.push( newTimedValue )
            do{ newTimedValue = timedValues.shift() }
            while( !newTimedValue && timedValues.length )
            MOVINGWINDOW.shift()
        }
        timeChart.setSeriesData( name, newShorterTime )
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
        return {from: this.begin, to: this.end, color: dunkelflauteColor}
    }
    seriousness() {
        console.log( "Calculation of matchedShares" )
        // console.log( matchedShares )
    }
}


// https://www.smard.de/page/home/topic-article/211972/212398/nettonennleistung-am-strommarkt
// 2025
// Biomasse	Wasserkraft	Braunkohle	Steinkohle	Erdgas	Pumpspeicher	Mineralöl	Sonstige (nicht erneuerbar)
//    9.021 +     5.546 +    14.748   + 8.740     + 30.212 + 9.878        + 2.534      + 8.203
// = 88.882 GW conventional power plants