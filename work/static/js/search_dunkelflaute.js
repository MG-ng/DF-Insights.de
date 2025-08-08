"use strict"; // Turns on strict mode for this compilation unit

console.log("Executing Search Dunkelflaute…")

import { timeChart, dunkelflauteColor, Match, timeShares } from "./setupHome.js"
import {loadingToast, randomHSL, toast, unix_time_duration} from "./script.js"
import {closeLoadingToast, dataResolution, toasts} from "./flask_variables.js"
window.search_dunkelflaute = search_dunkelflaute  // needed for the button onclick
window.add_dunkelflaute_timeseries = add_dunkelflaute_timeseries


function search_dunkelflaute() {

    var input = getDunkelflauteInput()
    if (!input) { return }

    timeChart.xAxis.forEach( xAxis => xAxis.removePlotBand('same') )

    // Change the Search Button to Loading...
    var btn = document.getElementById('btn_search_dunkelflaute')
    btn.disabled = true
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>' +
        '<span class="mx-2">Loading...</span>'

    fetch('/search?maxShare=' + input["maxShare"] + "&min_duration_ms=" +
        unix_time_duration(input["minDuration"], input["dataRes"])
        + "&resolution=" + input["dataRes"] )
        .then(response => { return response.json() }
        ).then(data => {
        console.log("Matches: ", data["series"])

        for (var time_tuple of data["series"]) {
            var match = new Match(time_tuple[0], time_tuple[1], null)

            for (const xAxis of timeChart.xAxis) {  // There are 2 xAxis: one for the view, one for the view finder below
                xAxis.addPlotBand(match.plotBand())
            }
        }

        toast("Found " + data["series"].length + " periods matching your criteria.")

        btn.disabled = false
        btn.innerHTML = ' Search '

    }).catch(reason => {
        if (reason) {
            toast("Error in response because: ", reason.toString())
        }
    });
}

function add_dunkelflaute_timeseries() {

    var input = getDunkelflauteInput()
    if (!input) { return }

    // Change the Search Button to Loading...
    var btn = document.getElementById('btn_series_dunkelflaute')
    btn.disabled = true
    toasts.push( loadingToast() )
    toasts[toasts.length-1].showToast()


    fetch( '/trend?maxShare=' + input["maxShare"] + "&min_duration_ms=" +
        unix_time_duration( input["minDuration"], input["dataRes"] ) )
        .then(response => { return response.json() }
        ).then(data => {

        closeLoadingToast(toasts.pop())
        btn.disabled = false

        var dbData = data['series']
        if (dbData[0] === undefined) {
            toast("Loading Error! Contact the site maintainer."); return;
        }

        if( !timeChart.get( 'occurrences' ) ) {
            timeChart.addAxis({
                id: 'occurrences',
                title: {
                    text: 'Dunkelflaute Events in Last Rolling Year'
                },
                lineWidth: 1,
                lineColor: "#D3A266",
                opposite: true
            })
        }

        timeChart.addSeries({
            name: 'Events of Max ' + (input["maxShare"]*100) + "% R.E. & Min " + input["days"] + "d",
            data: dbData.map(innerList => [innerList[0], innerList[1]]),
            yAxis: 'occurrences',
            color: "#C3003E"
        })

        if( !timeChart.get( 'duration' ) ) {  // undefined when not existent
            timeChart.addAxis({
                id: 'duration',
                title: {
                    text: 'Total Duration of Dunkelflaute in Last Rolling Year'
                },
                lineWidth: 1,
                lineColor: "#D4A5AF",
                opposite: false
            })
        }

        timeChart.addSeries({
            name: 'Summed Duration of Max ' + (input["maxShare"]*100) + "% R.E. & Min " + input["days"] + "d",
            data: dbData.map(innerList => [innerList[0], innerList[2]]),
            yAxis: 'duration',
            color: "#C35500"
        })

    }).catch(reason => {
        if (reason) {
            toast("Error in response because: ", reason.toString())
        }
    })

}


function getDunkelflauteInput() {
    const maxShareElem = document.getElementById("max_re_share")
    var maxShare = parseInt(maxShareElem.value) / 100  // for percentage interpretation
    var maxShareMin = parseInt(maxShareElem.min)
    var maxShareMax = parseInt(maxShareElem.max)
    const minDurationElem = document.getElementById("min_duration")
    var minDuration = parseInt(minDurationElem.value)
    var minDurationMin = parseInt(minDurationElem.min)
    var minDurationMax = parseInt(minDurationElem.max)

    if (maxShare > maxShareMax || maxShare < maxShareMin) {
        toast("Max Share of (Wind + Solar) on total load is not in its valid range!"); return undefined;
    }
    if (minDuration > minDurationMax || minDuration < minDurationMin) {
        toast("Min Duration of low (Wind + Solar) on total load is not in its valid range!"); return undefined;
    }
    const selectDataRes = document.getElementById("search_select_data_res")
    if ( !selectDataRes || ! ["hour", "day", "week"].includes( selectDataRes.value ) ) {
        toast("Data Resolution is not valid!"); return undefined;
    }
    return { 'maxShare': maxShare, 'minDuration': minDuration, 'dataRes': selectDataRes.value,
        'days': unix_time_duration( minDuration, selectDataRes.value )/1000/60/60/24 }
}
