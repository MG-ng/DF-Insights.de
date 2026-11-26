"use strict";

/**
 * Small wrapper around Plotly for the big time series chart.
 *
 * It keeps the state (series, y axes, highlighted periods) itself and re-renders with Plotly.react,
 * so the rest of the code can add/remove series similar to the former Highcharts stock chart:
 *   addSeries, clearSeries, setSeriesData, addAxis/hasAxis, addBand/removeBands, setTitle, getRange
 * Timestamps are always UTC ms; they are shown in Europe/Berlin local time.
 */
import { utcMsToBerlin, berlinToUtcMs } from "./berlinTime.js"
export { TimeChart, fitYRange, RANGE_SELECTOR_BUTTONS }

const AXIS_STEP = 0.055  // horizontal space per additional y axis (fraction of the plot width)
const YEAR_MS = 365 * 24 * 60 * 60 * 1000

const RANGE_SELECTOR_BUTTONS = [
    { count: 1, label: '1m', step: 'month', stepmode: 'backward' },
    { count: 3, label: '3m', step: 'month', stepmode: 'backward' },
    { count: 6, label: '6m', step: 'month', stepmode: 'backward' },
    { count: 1, label: 'YTD', step: 'year', stepmode: 'todate' },
    { count: 1, label: '1y', step: 'year', stepmode: 'backward' },
    { step: 'all', label: 'All' }
]

/** Min/max of the values in [x0, x1] with 5 % padding; null if nothing is visible */
function fitYRange(xs, ysList, x0, x1) {
    let min = Infinity, max = -Infinity
    for (let i = 0; i < xs.length; i++) {
        if (xs[i] < x0 || xs[i] > x1) continue
        for (const ys of ysList) {
            const v = ys[i]
            if (v === null || v === undefined || Number.isNaN(v)) continue
            if (v < min) min = v
            if (v > max) max = v
        }
    }
    if (min === Infinity) return null
    const pad = (max - min) * 0.05 || Math.abs(max) * 0.05 || 1
    return [min - pad, max + pad]
}

class TimeChart {
    /**
     * @param divId   id of the container element
     * @param axes    { axisId: {title, color, side: 'left'|'right', visible, tickformat, hoverformat} } in display order
     * @param options { onRangeChange(minUtcMs, maxUtcMs), initialRangeMs }
     */
    constructor(divId, axes, options = {}) {
        this.div = document.getElementById(divId)
        this.axes = new Map(Object.entries(axes))
        this.series = []          // { id, name, data: [[utcMs, value]], yAxis, color, x, xMs, y }
        this.bands = []           // { from, to, color } in UTC ms
        this.title = ''
        this.xRange = null        // current visible range as Berlin strings (Plotly axis values)
        this.colorMemory = new Map()
        this.onRangeChange = options.onRangeChange
        this.initialRangeMs = options.initialRangeMs ?? YEAR_MS
        this.renderScheduled = false
        this.listening = false
    }

    // ----- Highcharts-like API used by the other modules -----

    addSeries({ id, name, data, yAxis, color }) {
        name = name ?? id
        yAxis = String(yAxis)  // Highcharts style numeric axis indices are accepted too
        if (!this.axes.has(yAxis)) yAxis = this.axes.keys().next().value
        color = this.colorMemory.get(name) ?? color  // keep the color of a series across reloads
        this.colorMemory.set(name, color)
        const series = { id: id ?? name, name, yAxis, color }
        this.series.push(series)
        this.#setData(series, data)
        this.scheduleRender()
        return series
    }

    get(id) {
        return this.series.find(s => s.id === id) ?? (this.axes.has(id) ? this.axes.get(id) : undefined)
    }

    clearSeries() {
        this.series = []
        this.scheduleRender()
    }

    setSeriesData(name, data) {
        const series = this.series.find(s => s.name === name)
        if (series) { this.#setData(series, data); this.scheduleRender() }
    }

    hasAxis(id) { return this.axes.has(String(id)) }

    addAxis(id, { title, color, side = 'right' }) {
        if (!this.axes.has(String(id))) this.axes.set(String(id), { title, color, side })
        this.scheduleRender()
    }

    addBand(from, to, color) {
        this.bands.push({ from, to, color })
        this.scheduleRender()
    }

    removeBands() {
        this.bands = []
        this.scheduleRender()
    }

    setTitle(text) {
        this.title = text
        this.scheduleRender()
    }

    /** Visible x range in UTC ms; the full data extent when nothing has been zoomed yet */
    getRange() {
        if (this.xRange) return this.xRange.map(berlinToUtcMs)
        const extent = this.#dataExtent()
        return extent ?? [1000000000000, 2000000000000]
    }

    /** All series as CSV, one row per timestamp (local German time) */
    toCSV() {
        const rows = new Map()
        this.series.forEach((s, col) => {
            s.data.forEach(([t, v]) => {
                if (!rows.has(t)) rows.set(t, new Array(this.series.length).fill(''))
                rows.get(t)[col] = v ?? ''
            })
        })
        const escape = text => `"${String(text).replace(/"/g, '""')}"`
        const lines = [['Time (Europe/Berlin)', ...this.series.map(s => s.name)].map(escape).join(',')]
        ;[...rows.keys()].sort((a, b) => a - b).forEach(t => lines.push([utcMsToBerlin(t), ...rows.get(t)].join(',')))
        return lines.join('\n')
    }

    // ----- Rendering -----

    #setData(series, data) {
        const sorted = (data ?? []).filter(p => p && p[0] !== null && p[0] !== undefined)
            .slice().sort((a, b) => a[0] - b[0])
        series.data = sorted
        series.xMs = sorted.map(p => p[0])
        series.x = series.xMs.map(utcMsToBerlin)
        series.y = sorted.map(p => p[1])
    }

    #dataExtent() {
        let min = Infinity, max = -Infinity
        for (const s of this.series) {
            if (!s.xMs.length) continue
            min = Math.min(min, s.xMs[0])
            max = Math.max(max, s.xMs[s.xMs.length - 1])
        }
        return min === Infinity ? null : [min, max]
    }

    scheduleRender() {
        if (this.renderScheduled) return
        this.renderScheduled = true
        requestAnimationFrame(() => { this.renderScheduled = false; this.render() })
    }

    /** Assigns Plotly axis names (y, y2, …) to the axes that currently have series */
    #axisLayout() {
        const used = [...this.axes.keys()].filter(id => this.series.some(s => s.yAxis === id))
        const names = new Map(used.map((id, i) => [id, i === 0 ? 'y' : 'y' + (i + 1)]))
        const shown = used.filter(id => this.axes.get(id).visible !== false)
        const left = shown.filter(id => (this.axes.get(id).side ?? 'left') === 'left')
        const right = shown.filter(id => this.axes.get(id).side === 'right')
        const domain = [Math.max(0, left.length - 1) * AXIS_STEP, 1 - Math.max(0, right.length - 1) * AXIS_STEP]
        return { used, names, left, right, domain }
    }

    #visibleRangeMs() {
        if (this.xRange) return this.xRange.map(berlinToUtcMs)
        const extent = this.#dataExtent()
        if (!extent) return null
        return [Math.max(extent[0], extent[1] - this.initialRangeMs), extent[1]]
    }

    render() {
        if (!this.div) return
        const { used, names, left, right, domain } = this.#axisLayout()
        const visibleMs = this.#visibleRangeMs()
        if (visibleMs && !this.xRange) this.xRange = visibleMs.map(utcMsToBerlin)

        const layout = {
            title: { text: this.title },
            uirevision: 'keep',
            margin: { l: 70, r: 70, t: 70, b: 40 },
            hovermode: 'x unified',
            legend: { orientation: 'h', x: 0, y: -0.32, yanchor: 'top' },
            xaxis: {
                type: 'date',
                domain,
                range: this.xRange ?? undefined,
                autorange: !this.xRange,
                hoverformat: '%a, %b %e %Y, %H:%M',
                showspikes: true, spikemode: 'across', spikethickness: 1, spikedash: 'dot', spikecolor: '#999',
                rangeselector: { buttons: RANGE_SELECTOR_BUTTONS, x: 0, y: 1.08 },
                rangeslider: { visible: true, thickness: 0.1 }
            },
            shapes: this.bands.map(b => ({
                type: 'rect', xref: 'x', yref: 'paper', y0: 0, y1: 1, layer: 'below',
                x0: utcMsToBerlin(b.from), x1: utcMsToBerlin(b.to), fillcolor: b.color, line: { width: 0 }
            }))
        }

        used.forEach(id => {
            const axis = this.axes.get(id)
            const name = names.get(id)
            const key = name === 'y' ? 'yaxis' : 'yaxis' + name.slice(1)
            const side = axis.side ?? 'left'
            const sideList = side === 'left' ? left : right
            const index = sideList.indexOf(id)
            const ys = this.series.filter(s => s.yAxis === id)
            layout[key] = {
                title: { text: axis.title ?? '', font: { color: axis.color } },
                tickfont: { color: axis.color },
                tickformat: axis.tickformat,
                visible: axis.visible !== false,
                side,
                overlaying: name === 'y' ? undefined : 'y',
                anchor: index > 0 ? 'free' : 'x',
                position: index > 0 ? (side === 'left' ? domain[0] - index * AXIS_STEP : domain[1] + index * AXIS_STEP) : undefined,
                showgrid: name === 'y',
                zeroline: false,
                fixedrange: true,
                ...this.#yRange(ys, visibleMs)
            }
            layout.xaxis.rangeslider[key] = { rangemode: 'auto' }
        })

        const traces = this.series.map(s => {
            const axis = this.axes.get(s.yAxis)
            return {
                type: 'scatter', mode: 'lines',
                name: s.name, x: s.x, y: s.y,
                yaxis: names.get(s.yAxis),
                line: { color: s.color, width: 1.5 },
                connectgaps: false,
                hovertemplate: `%{y:${axis.hoverformat ?? ',.2f'}}`
            }
        })

        Plotly.react(this.div, traces, layout, {
            responsive: true,
            displaylogo: false,
            scrollZoom: true,
            modeBarButtonsToAdd: [{
                name: 'Download data as CSV',
                icon: Plotly.Icons.disk,
                click: () => downloadText(this.toCSV(), 'df-insights-timeseries.csv', 'text/csv')
            }]
        })
        this.#listen()
    }

    #yRange(seriesOnAxis, visibleMs) {
        if (!visibleMs || !seriesOnAxis.length) return { autorange: true }
        let range = null
        for (const s of seriesOnAxis) {
            const r = fitYRange(s.xMs, [s.y], visibleMs[0], visibleMs[1])
            if (!r) continue
            range = range ? [Math.min(range[0], r[0]), Math.max(range[1], r[1])] : r
        }
        return range ? { range, autorange: false } : { autorange: true }
    }

    #listen() {
        if (this.listening) return
        this.listening = true
        let timer
        this.div.on('plotly_relayout', event => {
            if (!Object.keys(event).some(key => key.startsWith('xaxis'))) return  // our own y axis updates
            const range = this.div._fullLayout.xaxis.range
            this.xRange = [String(range[0]), String(range[1])]
            this.render()  // re-fits the y axes to the visible window
            clearTimeout(timer)
            timer = setTimeout(() => this.onRangeChange?.(...this.getRange()), 400)
        })
    }
}

function downloadText(text, fileName, mimeType) {
    const url = URL.createObjectURL(new Blob([text], { type: mimeType }))
    const link = Object.assign(document.createElement('a'), { href: url, download: fileName })
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
}
