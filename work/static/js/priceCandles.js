"use strict";

/**
 * Candlestick chart of the day-ahead market prices.
 *
 * Every candle is one day (cut at midnight Europe/Berlin), built by /ohlc from the hourly prices:
 * open = first hour, close = last hour, high/low = the most expensive and the cheapest hour of the day.
 * Long wicks show days with a large intraday spread (e.g. cheap solar noon vs. expensive evening peak),
 * short and high candles are typical for Dunkelflauten with expensive power around the clock.
 */
import { utcMsToBerlin, berlinToUtcMs } from "./berlinTime.js"
import { fitYRange, RANGE_SELECTOR_BUTTONS } from "./plotlyTimeChart.js"
import { toast } from "./script.js"
export { priceCandles }

const DEFAULT_PRICE_FILTER = 'Market_Price_GER_LUX'
const YEAR_MS = 365 * 24 * 60 * 60 * 1000

const priceCandles = {
    div: document.getElementById('candlestick-container'),
    select: document.getElementById('select-candle-price'),
    days: [], xMs: [], open: [], high: [], low: [], close: [],
    name: '',
    bands: [],
    xRange: null,
    listening: false,

    addBand(from, to, color) { this.bands.push({ from, to, color }); this.render() },
    removeBands() { this.bands = []; this.render() },

    load() {
        if (!this.div || !this.select) return
        this.div.classList.add('chart-loading')
        fetch('/ohlc?filter=' + encodeURIComponent(this.select.value))
            .then(response => {
                if (!response.ok) throw new Error(response.status)
                return response.json()
            })
            .then(data => {
                const rows = data['series'] ?? []
                this.name = data['name'] ?? ''
                this.xMs = rows.map(row => row[0])  // UTC ms
                this.days = this.xMs.map(ms => utcMsToBerlin(ms).slice(0, 10))
                this.open = rows.map(row => row[1])
                this.high = rows.map(row => row[2])
                this.low = rows.map(row => row[3])
                this.close = rows.map(row => row[4])
                if (!this.xRange && this.xMs.length) {
                    const last = this.xMs[this.xMs.length - 1]
                    this.xRange = [utcMsToBerlin(Math.max(this.xMs[0], last - YEAR_MS)), utcMsToBerlin(last + 12 * 3600 * 1000)]
                }
                if (!rows.length) toast("No hourly prices found for " + this.select.selectedOptions[0]?.text)
                this.render()
            })
            .catch(error => {
                console.error(error)
                toast("Loading Error of the price candles! Contact the site maintainer.")
            })
            .finally(() => this.div.classList.remove('chart-loading'))
    },

    render() {
        if (!this.div || typeof Plotly === 'undefined') return
        const visibleMs = this.xRange?.map(berlinToUtcMs)
        const yRange = visibleMs ? fitYRange(this.xMs, [this.low, this.high], visibleMs[0] - 12 * 3600 * 1000, visibleMs[1]) : null

        const trace = {
            type: 'candlestick',
            name: this.select.selectedOptions[0]?.text ?? this.name,
            x: this.days, open: this.open, high: this.high, low: this.low, close: this.close,
            increasing: { line: { color: '#2E9E5B' } },
            decreasing: { line: { color: '#D6304A' } },
            xhoverformat: '%a, %b %e %Y'
        }
        const layout = {
            uirevision: 'keep',
            margin: { l: 70, r: 30, t: 50, b: 40 },
            showlegend: false,
            hovermode: 'x',
            xaxis: {
                type: 'date',
                range: this.xRange ?? undefined,
                autorange: !this.xRange,
                rangeselector: { buttons: RANGE_SELECTOR_BUTTONS, x: 0, y: 1.1 },
                rangeslider: { visible: true, thickness: 0.1, yaxis: { rangemode: 'auto' } }
            },
            yaxis: {
                title: { text: 'Day-ahead price (€/MWh)' },
                fixedrange: true,
                ...(yRange ? { range: yRange, autorange: false } : { autorange: true })
            },
            shapes: this.bands.map(b => ({
                type: 'rect', xref: 'x', yref: 'paper', y0: 0, y1: 1, layer: 'below',
                x0: utcMsToBerlin(b.from), x1: utcMsToBerlin(b.to), fillcolor: b.color, line: { width: 0 }
            }))
        }
        Plotly.react(this.div, [trace], layout, { responsive: true, displaylogo: false, scrollZoom: true })

        if (!this.listening) {
            this.listening = true
            this.div.on('plotly_relayout', event => {
                if (!Object.keys(event).some(key => key.startsWith('xaxis'))) return
                const range = this.div._fullLayout.xaxis.range
                this.xRange = [String(range[0]), String(range[1])]
                this.render()  // re-fit the price axis to the visible days
            })
        }
    }
}

/** Price zones for the selector: all SMARD market prices except the duplicated Polish fields */
function populatePriceSelect() {
    const script = document.getElementById('custom-script')
    if (!priceCandles.select || !script) return
    const filters = JSON.parse(script.getAttribute("filters"))          // { filter-id: german-filter-name }
    const translations = JSON.parse(script.getAttribute("translation")) // { german-filter-name: english-filter-name }
    const options = Object.entries(filters)
        .filter(([, german]) => german.startsWith("Marktpreis") && !german.includes("DON'T USE"))
        .map(([id, german]) => ({ id, english: translations[german] }))
    priceCandles.select.innerHTML = options.map(option =>
        `<option value="${option.id}" ${option.english === DEFAULT_PRICE_FILTER ? 'selected' : ''}>
            ${option.english.replace('Market_Price_', '').replaceAll('_', ' ')}
        </option>`).join('')
    priceCandles.select.addEventListener('change', () => priceCandles.load())
}

populatePriceSelect()
priceCandles.load()
