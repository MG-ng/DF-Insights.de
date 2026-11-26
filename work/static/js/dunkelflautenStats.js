"use strict"; // Turns on strict mode for this compilation unit: No implicit global variables possible
// if there is a typo in referencing a variable, without this, there would be created a new undefined


import {toast, getTurboColor, apiToChartTime} from "./script.js";

export { bubbleChart }

var turboStops = []
function refreshTurboStops(numStops = 50) {
    turboStops = []
    for (let i = 0; i <= numStops; i++) {
        turboStops.push([i / numStops, getTurboColor(i / numStops)]);
    }
}
refreshTurboStops(10)

const dunkelflauten_features = [
    { value: "start_time", text: "Start Time" },
    { value: "duration_days", text: "Duration in days" },
    { value: "electric_energy_consumption_during_df", text: "Electric Energy Consumption during DF in MWh" },
    { value: "extent", text: "Extent (see Usage)" },
    { value: "storage_made_electricity_value", text: "Potential Value of Electricity specifically made during DF" },
    { value: "peak_res_load_power_during_df", text: "Peak Residual Load Power during DF in MW" },
    { value: "avg_res_load_power_during_df", text: "Avg Residual Load Power during DF in MW" },
    { value: "avg_res_load_power_before_after", text: "Residual Load Power avg(week before and after the DF) in MW" },
    { value: "avg_weighted_price_during_df", text: "Average with Total Consumption Weighted Price during DF" },
    { value: "avg_price_during_dunkelflaute", text: "Average Price during DF in €/MWh" },
    { value: "avg_price_week_before_dunkelflaute", text: "Average Price during Week Before DF" },
    { value: "avg_price_week_after_dunkelflaute", text: "Average Price during Week After DF" },
    { value: "price_increase_during_df", text: "Average Price Increase during Dunkelflaute in €/MWh" },
    { value: "relative_price_increase_during_df", text: "Average Relative Price Increase during Dunkelflaute in %" },
    { value: "price_increase_during_df_weighted", text: "Avg with Total Consumption Weighted Price Increase during DF in €/MWh" },
    { value: "relative_price_increase_during_df_weighted", text: "Avg with Total Consumption Weighted Relative Price Increase during DF in %" },
    { value: "dp_in_before_after_range", text: "Avg Price during Dunkelflaute in Range of Price Before and After" },
    { value: "dunkelflauten_cost", text: "Cost of Dunkelflaute in €/MWh Price Increase * Total Consumption during DF in MWh" },
    { value: "dunkelflauten_cost_weighted", text: "Cost of Dunkelflaute in € with Total Cons. Weighted Price Inc. * Total Cons. during DF" },
    { value: "day_of_week", text: "Day of Week of Dunkelflauten Mean Incidence" },
    { value: "day_of_month", text: "Day of the Month of Dunkelflauten Mean Incidence" },
    { value: "month", text: "Month of Dunkelflauten Mean Incidence" },
    { value: "year", text: "Year of Dunkelflauten Mean Incidence" },
    { value: "hourly_repi_30mix", text: "Hourly REPI: Wind Max and /30 Solar Avg" },
    { value: "repi_power1avg", text: "Hourly REPI: Wind Avg ^3 and Solar Avg" },
    { value: "repi_square1avg", text: "Hourly REPI: Wind Avg ^2 and Solar Avg" },
    { value: "repi_power1avg2", text: "Hourly REPI: Wind Avg and 2* Solar Avg" },
    { value: "wind_speed_100_avg", text: "Avg Wind Speed in 100m Height at 6 spots across GER during DF" },
    { value: "diffuse_radiation_avg", text: "Avg Diffuse Radiation at 9 spots across GER during DF" },
    { value: "direct_radiation_avg", text: "Avg Direct Radiation at 9 spots across GER during DF" },
]

function populateSelect(selectId, selectedValue = '') {
    const select = document.getElementById(selectId);
    if (!select) return

    select.innerHTML = dunkelflauten_features.map(option =>
        `<option value="${option.value}" ${option.value === selectedValue ? 'selected' : ''}>
            ${option.text}
        </option>`
    ).join('')
}

populateSelect('xAxisSelect', 'duration_days')
populateSelect('yAxisSelect', 'extent')
populateSelect('sizeSelect', 'dunkelflauten_cost')
populateSelect('colorSelect', 'price_increase_during_df_weighted')

let bubbleChart;  // the Plotly chart div once it is drawn
const tableCache = new Map()  // tableName -> rows, so changing an axis doesn't download the table again

// Draw (or redraw) the bubble chart with the current selections
async function createChart() {
    const selectedTable = document.getElementById('tableSelect').value
    const xColumn = document.getElementById('xAxisSelect').value
    const yColumn = document.getElementById('yAxisSelect').value
    const sizeColumn = document.getElementById('sizeSelect').value
    const colorColumn = document.getElementById('colorSelect').value

    const rows = await fetchTableData(selectedTable)
    const value = (row, column) => parseFloat(row[column]) || 0
    const sizes = rows.map(row => value(row, sizeColumn))
    const colors = rows.map(row => value(row, colorColumn))

    // Bubble diameter between 10 and 50 px, linear between the smallest and the largest value (like Highcharts did)
    const zMin = Math.min(...sizes), zMax = Math.max(...sizes)
    const diameters = sizes.map(z => zMax > zMin ? 10 + (z - zMin) / (zMax - zMin) * 40 : 30)

    const trace = {
        type: 'scatter',
        mode: 'markers',
        name: 'Dunkelflauten in Germany',
        x: rows.map(row => value(row, xColumn)),
        y: rows.map(row => value(row, yColumn)),
        customdata: rows.map((row, i) => [smartTimestamp(apiToChartTime(row.start_time), 'date'), sizes[i], row['duration_days'], colors[i]]),
        marker: {
            size: diameters,
            sizemode: 'diameter',
            color: colors,
            colorscale: turboStops,
            opacity: 0.75,
            line: { width: 1, color: 'rgba(40, 40, 40, 0.6)' },
            colorbar: { title: { text: formatColumnName(colorColumn), side: 'right' }, thickness: 14 }
        },
        hovertemplate:
            'Start: <b>%{customdata[0]}</b><br>' +
            `${formatColumnName(xColumn)}: <b>%{x}</b><br>` +
            `${formatColumnName(yColumn)}: <b>%{y}</b><br>` +
            `${formatColumnName(sizeColumn)}: <b>%{customdata[1]}</b><br>` +
            `${formatColumnName(colorColumn)}: <b>%{customdata[3]}</b><br>` +
            'Duration in days: <b>%{customdata[2]}</b>' +
            '<extra>Dunkelflauten in Germany</extra>'
    }
    const layout = {
        title: { text: `${selectedTable.replace('_', ' ').toUpperCase()} Analysis`, font: { size: 18 } },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        hovermode: 'closest',
        showlegend: false,
        margin: { l: 70, r: 20, t: 60, b: 60 },
        xaxis: { title: { text: formatColumnName(xColumn) }, gridcolor: '#e6e6e6', zeroline: false },
        yaxis: { title: { text: formatColumnName(yColumn) }, gridcolor: '#e6e6e6', zeroline: false },
        transition: { duration: 500, easing: 'cubic-in-out' }
    }
    bubbleChart = document.getElementById('bubble-chart-container')
    Plotly.react(bubbleChart, [trace], layout, { responsive: true, displaylogo: false })
}

// Format column names for display
function formatColumnName(columnName) {
    return columnName
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

// Event listeners for dynamic updates
document.getElementById('tableSelect').addEventListener('change', createChart);
document.getElementById('xAxisSelect').addEventListener('change', createChart);
document.getElementById('yAxisSelect').addEventListener('change', createChart);
document.getElementById('sizeSelect').addEventListener('change', createChart);
document.getElementById('colorSelect').addEventListener('change', createChart);
document.getElementById('minDurationSelect').addEventListener('change', createChart);

// Initialize the chart when page loads
createChart();


// Function to fetch data from PostgreSQL backend, filtered by the selected min duration
async function fetchTableData(tableName) {
    const minDuration = document.getElementById('minDurationSelect').value
    try {
        if (!tableCache.has(tableName)) {
            const response = await fetch( '/enrichedDF?tableName=' + tableName )
            const data = await response.json()
            var dunkelflauten = [], rows = [], cols = []
            if(data) { cols = data["ordering"]; rows = data["series"] }
            for( var row of rows ) {
                var dunkelflaute = {}
                for( var index in cols ) {
                    // Downloaded array to convert it back to a map
                    dunkelflaute[cols[index]] = row[index]
                    if( cols[index] === "dp_in_before_after_range" ) {
                        dunkelflaute[cols[index]] = (row[index] ? 1 : 0)
                    }
                }
                dunkelflauten.push(dunkelflaute)
            }
            tableCache.set(tableName, dunkelflauten)
        }
        return tableCache.get(tableName).filter(dunkelflaute => dunkelflaute["duration_days"] >= minDuration)
    } catch (error) {
        console.error('Error fetching data:', error)
        toast("Loading Error of the Dunkelflauten table! Contact the site maintainer.")
        return []
    }
}



function smartTimestamp(timestamp, format = 'default') {
    const date = new Date(timestamp)

    switch (format) {
        case 'date':     return date.toLocaleDateString()      // "3/15/2024"
        case 'time':     return date.toLocaleTimeString()      // "10:30:45 AM"
        case 'compact':  return timestampToCompact(timestamp)  // "2024-03-15 10:30"
        case 'readable': return timestampToReadable(timestamp) // "March 15, 2024 at 10:30 AM"
        default:         return date.toLocaleString()          // "3/15/2024, 10:30:45 AM"
    }
}
