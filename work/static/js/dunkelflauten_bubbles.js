Highcharts.chart('bubble-chart-container', {

    chart: {
        type: 'bubble',
        plotBorderWidth: 1,
        zooming: {
            type: 'xy'
        }
    },

    legend: {
        enabled: false
    },

    title: {
        text: 'Structure of Dunkelflauten'
    },

    xAxis: {
        gridLineWidth: 1,
        title: {
            text: 'Extent/Shortfall'
        },
        labels: {
            format: '{value} TWh'
        },
        plotLines: [{
            dashStyle: 'dot',
            width: 2,
            value: 65,
            label: {
                rotation: 0,
                y: 15,
                style: {
                    fontStyle: 'italic'
                },
                text: 'Gas Storage Rheden/GER'
            },
            zIndex: 3
        }],
    },

    yAxis: {
        startOnTick: false,
        endOnTick: false,
        title: {
            text: 'Price Delta in €/MWh'
        },
        labels: {
            format: '{value}'
        },
        maxPadding: 0.2,
        plotLines: [{
            dashStyle: 'dot',
            width: 2,
            value: 50,
            label: {
                align: 'right',
                style: {
                    fontStyle: 'italic'
                },
                text: 'Usual day/night volatility',
                x: -10
            },
            zIndex: 3
        }],
    },

    tooltip: {
        useHTML: true,
        headerFormat: '<table>',
        pointFormat: '<tr><th colspan="2"><h3>{point.year}</h3></th></tr>' +
            '<tr><th>Price Surge:</th><td>{point.x}g</td></tr>' +
            '<tr><th>Extent:</th><td>{point.y}g</td></tr>' +
            '<tr><th>Wind Speed:</th><td>{point.z}%</td></tr>',
        footerFormat: '</table>',
        followPointer: true
    },

    plotOptions: {
        series: {
            dataLabels: {
                enabled: true,
                format: '{point.name}'
            }
        }
    },

    series: [{
        data: [
            {x: 95, y: 95, z: 13.8, name: 'BE', year: 2020},
            {x: 86.5, y: 102.9, z: 14.7, name: 'DE', year: 2020},
            {x: 80.8, y: 91.5, z: 15.8, name: 'FI', year: 2020},
            {x: 80.4, y: 102.5, z: 12, name: 'NL', year: 2020},
            {x: 80.3, y: 86.1, z: 11.8, name: 'SE', year: 2020},
            {x: 78.4, y: 70.1, z: 16.6, name: 'ES', year: 2020},
            {x: 74.2, y: 68.5, z: 14.5, name: 'FR', year: 2020},
            {x: 73.5, y: 83.1, z: 50, name: 'NO', year: 2020},
            {x: 71, y: 93.2, z: 24.7, name: 'UK', year: 2020},
            {x: 69.2, y: 57.6, z: 10.4, name: 'IT', year: 2020},
            {x: 68.6, y: 20, z: 16, name: 'RU', year: 2020},
        ],
        colorByPoint: true
    }]

})