"use strict"; // Turns on strict mode for this compilation unit

import { dunkelflauteColor, unix_time_duration, Match, timeShares } from "./setupHome.js"
import { dataResolution } from "./flask_variables.js"
export { search_dunkelflaute }
window.search_dunkelflaute = search_dunkelflaute  // needed for the button onclick

function search_dunkelflaute() {

    // Change Search Button to Loading...
    var btn = document.getElementById('btn_search_dunkelflaute')
    btn.disabled = true
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>Loading...'

    var chart = Highcharts.charts[0]
    chart.xAxis.forEach( xAxis => xAxis.removePlotBand('same') )

    for( var series of chart.series ) {
        var name = series["name"]
        if (name !== "Share of Renewables on Total Load") { continue }
        console.log( "Found Share of (Wind+Solar) series!" )

        const maxShareElem = document.getElementById("max_re_share")
        var maxShare = parseInt(maxShareElem.value) / 100  // for percentage interpretation
        var maxShareMin = parseInt(maxShareElem.min)
        var maxShareMax = parseInt(maxShareElem.max)
        const minDurationElem = document.getElementById("min_duration")
        var minDuration = parseInt(minDurationElem.value)
        var minDurationMin = parseInt(minDurationElem.min)
        var minDurationMax = parseInt(minDurationElem.max)

        if (maxShare > maxShareMax || maxShare < maxShareMin) {
            alert("Max Share of (Wind + Solar) on total load is not in its valid range"); break;
        }
        if (minDuration > minDurationMax || minDuration < minDurationMin) {
            alert("Min Duration of low (Wind + Solar) on total load is not in its valid range"); break;
        }


        var matches = []  // List of class
        var matchedShares = []

        console.log(maxShare)
        console.log(minDuration)
        console.log(typeof (minDuration))

        var begin, end
        for (const timeShare of timeShares) {  // sorted list of [unix_timestamp, share of (wind+solar)]

            if (timeShare[1] <= maxShare) {
                if (begin) {
                    console.log("End updated")
                    console.log(timeShare[1])
                    end = timeShare[0]
                    matchedShares.push(timeShare)  // TODO: further analysis
                } else { // begin is undefined
                    begin = timeShare[0]
                    end = timeShare[0]
                    console.log("Begin found: " + begin)
                }
            } else {
                if (!begin || !end)  continue;  // high share of (wind+solar) at this and last timestamp
                if (end - begin >= unix_time_duration( minDuration, dataResolution ) ) {  // undefined-undef should also work = false
                    matches.push( new Match(begin, end, structuredClone( matchedShares )) );  // begin, end reset same as discarding
                    matchedShares = []
                }
                // discard match because it wasn't long enough
                begin = undefined
                end = undefined
            }
        }

        console.log("MATCHES")
        console.log(matches)

        for (const match of matches) {
            for (const xAxis of chart.xAxis) {  // There are 2 xAxis: one for the view, one for the view finder below
                xAxis.addPlotBand(match.plotBand())
            }
        }
    }


    btn.disabled = false
    btn.innerHTML = ' Search '
}

