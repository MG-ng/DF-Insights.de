"use strict";

import { randomHSL } from "./script.js"
import { selector, cma_selector } from "./setupHome.js"
export { filters, translations, cma_options, reloadData, dataResolution }

    var dataResolution = JSON.parse( document.getElementById('custom-script').getAttribute("resolution") );
    var filters = JSON.parse( document.getElementById('custom-script').getAttribute("filters") );
    var translations = JSON.parse( document.getElementById('custom-script').getAttribute("translation") );
    var cma_options = [];

    var reloadData = function() {
        return function() {
            var chart = Highcharts.charts[0]

            console.log( "Series:" )
            console.log( chart.series )
            // console.log( selector.getValue() )
            // console.log( selector.items )  // The same as above
            // console.log( selector.options )  WANTED

            var selectedFilterList = []
            // Clear all existing options
            cma_selector.clear();
            cma_selector.clearOptions();
            selector.items.forEach( item => selectedFilterList.push(item) )
            var filter_names_url = selectedFilterList.join( "&filters=" )
            if (selectedFilterList.length === 0) {
                chart.series[1].remove();
                return
            }
            fetch('/api?filters=' + filter_names_url)
                .then(response => {
                    console.log("API URL: " + response.url)
                    return response.json()
                })
                .then(data => {
                    cma_options = []
                    var ordering = data['ordering']
                    var dbData = data['series']
                    // Clear all existing series first
                    while(chart.series.length > 1) {
                        chart.series[1].remove();
                    }
                    // console.log(`DATA:`)
                    // console.log(data)
                    var innerLength = dbData[0].length
                    console.log(`innerLength: ${innerLength}` )
                    for (let i = 1; i < innerLength; i++) {

                        const newList = dbData.map( innerList => [ innerList[0], innerList[i] ] );
                        chart.addSeries({
                            name: ordering[i+2],
                            data: newList,
                            yAxis: ordering[i+2].includes("price") ? 0 : 1,
                            color: randomHSL()
                        })
                        cma_selector.addOption({
                            name: ordering[i+2],
                            value: ordering[i+2],
                            data: newList,
                            class:ordering[i+2].includes("price") ? 0 : 1,
                            label: ordering[i+2]
                        })

                        // cma_selector.refreshOptions();  // Just distracts with the focus on the expanded dropdown
                    }
                    chart.setTitle({text: "1000k MWh = 1 TWh"});  // TODO ?
                });
        };
    };