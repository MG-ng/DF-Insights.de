"use strict"; // Turns on strict mode for this compilation unit: No implicit global variables possible
// if there is a typo in referencing a variable, without this, there would be created a new undefined


import {toast, getTurboColor} from "./script.js";

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
    { value: "repi_sqare1avg", text: "Hourly REPI: Wind Avg ^2 and Solar Avg" },
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

let bubbleChart;

function showDF( data ) {
    alert(data)
}

// Initialize the chart
function createChart() {
    const selectedTable = document.getElementById('tableSelect').value
    const xColumn = document.getElementById('xAxisSelect').value
    const yColumn = document.getElementById('yAxisSelect').value
    const sizeColumn = document.getElementById('sizeSelect').value
    const colorColumn = document.getElementById('colorSelect').value

    updateChartWithRealData()

    if (bubbleChart) {
        bubbleChart.destroy()
    }

    bubbleChart = Highcharts.chart('bubble-chart-container', {
        chart: {
            type: 'bubble',
            backgroundColor: 'transparent'
        },
        title: {
            text: `${selectedTable.replace('_', ' ').toUpperCase()} Analysis`,
            style: {
                fontSize: '18px',
                fontWeight: 'bold'
            }
        },
        xAxis: {
            title: {
                text: formatColumnName(xColumn)
            },
            gridLineColor: '#e6e6e6'
        },
        yAxis: {
            title: {
                text: formatColumnName(yColumn)
            },
            gridLineColor: '#e6e6e6',
        },
        plotOptions: {
            bubble: {
                minSize: 10,
                maxSize: 50,
                tooltip: {
                    useHTML: true,
                    hideDelay: 1500,
                    style: { pointerEvents: 'auto' },
                    headerFormat: '<b>{series.name}</b><br>',
                    pointFormat: `Start: <b>{point.name}</b><br>
                        ${formatColumnName(xColumn)}:    &#9;<b>{point.x}</b><br>
                        ${formatColumnName(yColumn)}:    &#9;<b>{point.y}</b><br>
                        ${formatColumnName(sizeColumn)}: &#9;<b>{point.z}</b><br>
                        Duration in days: <b>{point.durationDays}</b> &nbsp;&nbsp;&nbsp; 
                        <!-- TODO: Make this work a href="#" onclick="(function(){
                            alert('Hello World');
                        })()">See More</a--><br>`
                },
                animation: {
                    duration: 1000,
                    easing: 'easeOutBounce'
                }
            }
        },
        series: [{
            name: 'Dunkelflauten in Germany',
            // keys: ['x', 'y', 'z', 'colorValue'],
            colorByPoint: true,  // this option determines whether the chart should receive one color per series or one color per point
            // colors: ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD', '#98D8C8']
        }],
        responsive: {
            rules: [{
                condition: {
                    maxWidth: 500
                },
                chartOptions: {
                    legend: {
                        enabled: false
                    }
                }
            }]
        }
    })
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







// Function to fetch data from PostgreSQL backend
async function fetchTableData(tableName, columns = ['*']) {
    const minDuration = document.getElementById('minDurationSelect').value
    try {
        const response = await fetch( '/enrichedDF?tableName=' + tableName )
        const data = await response.json()
        console.log(data)
        var dunkelflauten = [], rows = [], cols = []
        if(data) { cols = data["ordering"]; rows = data["series"] }
        console.log(cols)
        console.log(rows)
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
        console.log(dunkelflauten)
        return dunkelflauten.filter(dunkelflaute => dunkelflaute["duration_days"] >= minDuration)
    } catch (error) {
        console.error('Error fetching data:', error)
        return []
    }
}


// Function to update chart with real data
async function updateChartWithRealData() {
    const selectedTable = document.getElementById('tableSelect').value
    const xColumn = document.getElementById('xAxisSelect').value
    const yColumn = document.getElementById('yAxisSelect').value
    const sizeColumn = document.getElementById('sizeSelect').value
    const colorColumn = document.getElementById('colorSelect').value

    const requiredColumns = [xColumn, yColumn, sizeColumn, 'name', 'duration_days']
    const data = await fetchTableData(selectedTable, requiredColumns)

    var chartData = data.map(row => {
        /*
        if( "dp_in_before_after_range" in [xColumn, yColumn, sizeColumn, colorColumn] ) {
            var index = [xColumn, yColumn, sizeColumn, colorColumn].findIndex("dp_in_before_after_range")
        }*/
        return ({
            name: smartTimestamp(row.start_time, 'date'),
            x: parseFloat(row[xColumn]) || 0,
            y: parseFloat(row[yColumn]) || 0,
            z: parseFloat(row[sizeColumn]) || 0,
            // colorValue: 0 || 0,  // Doesn't work :/
            durationDays: row['duration_days']
        })
    })
    bubbleChart.series[0].setData(chartData)
}
updateChartWithRealData()



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
