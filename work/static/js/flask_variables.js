"use strict";

console.log("Executing Flask Variables……")

import { randomHSL, toast, loadingToast } from "./script.js"
import { timeChart, selectorFilter, selectorRes, cma_selector } from "./setupHome.js"
export { filters, translations, cma_options, reloadData, dataResolution, resolutions, closeLoadingToast, toasts }


var dataResolution = JSON.parse( document.getElementById('custom-script').getAttribute("resolution") )
var resolutions = JSON.parse( document.getElementById('custom-script').getAttribute("resolutions") )
var filters = JSON.parse( document.getElementById('custom-script').getAttribute("filters") )
var translations = JSON.parse( document.getElementById('custom-script').getAttribute("translation") )
var cma_options = []
var toasts = []


var closeLoadingToast = function ( toast ) {
    var elem = toast.toastElement.lastChild
    elem.click.apply(elem)
}

var reloadData = function() {
    return function() {
        console.log( "Series:" )
        console.log( timeChart.series )
        // console.log( selector.getValue() )
        // console.log( selector.items )  // The same as above
        // console.log( selector.options )  WANTED

        var selectedFilterList = []
        // Clear all existing options
        cma_selector.clear();
        cma_selector.clearOptions();
        selectorFilter.items.forEach(item => selectedFilterList.push(item) )
        var filter_names_url = selectedFilterList.join( "&filters=" )
        console.log( "selectorRes.item() = " + selectorRes.items )
        if (selectedFilterList.length === 0) {
            toast("No Time Series Selected!"); return
        }
        var previousMin = (timeChart.xAxis[0].min).toFixed(0) // Upper x Axis (Result of the viewfinder)
        var previousMax = (timeChart.xAxis[0].max).toFixed(0)
        var timeFilter = "&startTime=" + previousMin + "&endTime=" + previousMax
        var cut4Speed = (['quarterhour', 'hour'].includes( selectorRes.items[0] )) ? timeFilter : ""
        toasts.push( loadingToast() )
        toasts[toasts.length-1].showToast()
        fetch( '/api?filters=' + filter_names_url + "&resolution=" + selectorRes.items[0] + cut4Speed )
            .then(response => {
                console.log("API URL: " + response.url)
                closeLoadingToast(toasts.pop())

                try {
                    var data = response.json()
                } catch (e) {
                    toast("Error :/")
                }
                return data
            })
            .then(data => {
                cma_options = []
                var ordering = data['ordering']
                var dbData = data['series']
                // Clear all existing series first
                while(timeChart.series.length >= 1) {
                    timeChart.series[0].remove()
                }
                // console.log(`DATA:`)
                // console.log(data)
                if (dbData[0] === undefined) {
                    toast("Loading Error! Contact the site maintainer.")
                    return
                }
                var innerLength = dbData[0].length  // Number of columns
                console.log(`innerLength: ${innerLength}` )
                for (let i = 1; i < innerLength; i++) {
                    // duplicate the timestamp to each series (innerList[0])
                    const newList = dbData.map( innerList => [ innerList[0], innerList[i] ] )
                    timeChart.addSeries({
                        id: ordering[i+2],
                        name: ordering[i+2],
                        data: newList,
                        yAxis: ordering[i+2].includes("Share") || ordering[i+2].includes("Rel") ? 2 :
                            ordering[i+2].toLowerCase().includes("price") ? 0 : 1,  // TODO: Enhance Logic and correctness
                        color: randomHSL()
                    })
                    cma_selector.addOption({
                        name: ordering[i+2],
                        value: ordering[i+2],
                        data: newList,
                        class: ordering[i+2].toLowerCase().includes("price") ? 0 : 1,
                        label: ordering[i+2]
                    })

                    // cma_selector.refreshOptions();  // Just distracts with the focus on the expanded dropdown
                }
                timeChart.setTitle({text: "1000k MWh = 1 TWh"});  // TODO ?
            });
    };
};