"use strict"; // Turns on strict mode for this compilation unit: No implicit global variables possible
// if there is a typo in referencing a variable, without this, there would be created a new undefined


export { bubbleChart }


const bubbleData = {
    sales_data: [
        {id: 1, name: 'Product A', duration: 120000, profit_margin: 15.5, extent: 8.2, market_share: 12.3, growth_rate: 5.2},
        {id: 2, name: 'Product B', duration: 95000, profit_margin: 22.1, extent: 9.1, market_share: 8.7, growth_rate: 12.1},
        {id: 3, name: 'Product C', duration: 180000, profit_margin: 18.9, extent: 7.8, market_share: 15.6, growth_rate: 3.4},
        {id: 4, name: 'Product D', duration: 75000, profit_margin: 28.3, extent: 9.5, market_share: 6.2, growth_rate: 18.7},
    ]
}



const dunkelflauten_features = [
    { value: "start_time", text: "Start Time" },
    { value: "end_time", text: "End Time" },
    { value: "duration_ms", text: "Duration in Milliseconds" },
    { value: "duration_days", text: "Duration in days" },
    { value: "extent", text: "Extent" },
    { value: "res_load_revenue_during_df", text: "Residual Load Revenue During Dunkelflaute" },
    { value: "extent_week_before", text: "Extent of Residual Load in Week Before Dunkelflaute" },
    { value: "res_load_revenue_before_df", text: "Residual Load Revenue in Week Before DF" },
    { value: "extent_week_after", text: "Extent of Residual Load in Week After Dunkelflaute" },
    { value: "res_load_revenue_after_df", text: "Residual Load Revenue in Week After DF" },
    { value: "avg_weighted_price_during_dunkelflaute", text: "Average with Residual Load Weighted Price During DF" },
    { value: "avg_weighted_price_before_dunkelflaute", text: "Average with Residual Load Weighted Price in Week Before Dunkelflaute" },
    { value: "avg_weighted_price_after_dunkelflaute", text: "Average with Residual Load Weighted Price in Week After Dunkelflaute" },
    { value: "avg_price_during_dunkelflaute", text: "Average Price During DF in €/MWh" },
    { value: "avg_price_week_before_dunkelflaute", text: "Average Price During Week Before DF" },
    { value: "avg_price_week_after_dunkelflaute", text: "Average Price During Week After DF" },
    { value: "price_increase_during_df", text: "Average Price Increase During Dunkelflaute in €/Mwh" },
    { value: "relative_price_increase_during_df", text: "Average Relative Price Increase During Dunkelflaute in %" },
    { value: "price_increase_during_df_weighted", text: "Avg with ResLoad Weighted Price Increase During DF in €/Mwh" },
    { value: "relative_weighted_price_increase_during_df", text: "Avg with ResLoad Weighted Relative Price Increase During DF in %" },
    { value: "dp_in_before_after_range", text: "Avg Price During Dunkelflaute in Range of Price Before and After" },
    { value: "dunkelflauten_cost", text: "Cost of Dunkelflaute in €/MWh Price Increase * MWh Extent" },
    { value: "day_of_week", text: "Day of Week of Dunkelflauten Mean Incidence" },
    { value: "month", text: "Month of Dunkelflauten Mean Incidence" },
    { value: "year", text: "Year of Dunkelflauten Mean Incidence" },
]

function populateSelect(selectId, selectedValue = '') {
    const select = document.getElementById(selectId);
    if (!select) return;

    select.innerHTML = dunkelflauten_features.map(option =>
        `<option value="${option.value}" ${option.value === selectedValue ? 'selected' : ''}>
            ${option.text}
        </option>`
    ).join('');
}

populateSelect('xAxisSelect', 'duration')
populateSelect('yAxisSelect', 'extent')
populateSelect('sizeSelect', 'dunkelflauten_cost')

let bubbleChart;

// Initialize the chart
function createChart() {
    const selectedTable = document.getElementById('tableSelect').value;
    const xColumn = document.getElementById('xAxisSelect').value;
    const yColumn = document.getElementById('yAxisSelect').value;
    const sizeColumn = document.getElementById('sizeSelect').value;

    updateChartWithRealData()
    const data = transformDataForChart(selectedTable, xColumn, yColumn, sizeColumn);

    if (bubbleChart) {
        bubbleChart.destroy();
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
                    headerFormat: '<b>{series.name}</b><br>',
                    pointFormat: `<b>{point.name}</b><br>
                        ${formatColumnName(xColumn)}: <b>{point.x}</b><br>
                        ${formatColumnName(yColumn)}: <b>{point.y}</b><br>
                        ${formatColumnName(sizeColumn)}: <b>{point.z}</b>`
                },
                animation: {
                    duration: 1000,
                    easing: 'easeOutBounce'
                }
            }
        },
        series: [{
            name: 'Data Points',
            data: data,
            colorByPoint: true,
            colors: ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD', '#98D8C8']
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
    });
}

// Transform data for the chart based on selected columns
function transformDataForChart(tableName, xCol, yCol, sizeCol) {
    const tableData = bubbleData[tableName] || bubbleData.sales_data
    return tableData.map(row => ({
        name: row.name,
        x: row[xCol],
        y: row[yCol],
        z: row[sizeCol]
    }))
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

// Initialize the chart when page loads
createChart();








        // Real-world implementation functions
        // These would replace the mock data functionality

// Function to fetch data from your PostgreSQL backend
async function fetchTableData(tableName, columns = ['*']) {
    try {
        const response = await fetch( '/enrichedDF?tableName=' + tableName )
        const data = await response.json()
        console.log(data)
        var dunkelflauten = [], rows = [], cols = []
        if(data) { cols = data["ordering"]; rows = data["series"] }
        console.log(cols)
        console.log(rows)
        for( var row of rows ){
            var dunkelflaute = {}
            for( var index in cols ){
                dunkelflaute[cols[index]] = row[index]
            }
            dunkelflauten.push(dunkelflaute)
        }
        console.log(dunkelflauten)
        return dunkelflauten
    } catch (error) {
        console.error('Error fetching data:', error)
        return []
    }
}

// Function to get column names from a table
async function getTableColumns(tableName) {
    try {
        const response = await fetch(`/enrichedDF/${tableName}`)
        const columns = await response.json()
        return columns
    } catch (error) {
        console.error('Error fetching columns:', error)
        return []
    }
}

// Function to update chart with real data
async function updateChartWithRealData() {
    const selectedTable = document.getElementById('tableSelect').value
    const xColumn = document.getElementById('xAxisSelect').value
    const yColumn = document.getElementById('yAxisSelect').value
    const sizeColumn = document.getElementById('sizeSelect').value

    const requiredColumns = [xColumn, yColumn, sizeColumn, 'name']
    const data = await fetchTableData(selectedTable, requiredColumns)

    const chartData = data.map(row => ({
        name: row.start_time,
        x: parseFloat(row[xColumn]) || 0,
        y: parseFloat(row[yColumn]) || 0,
        z: parseFloat(row[sizeColumn]) || 0
    }))

    bubbleChart.series[0].setData(chartData)
}
updateChartWithRealData()
