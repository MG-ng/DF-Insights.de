"use strict";

/**
 * Dunkelflaute outlook and backtest charts on /prediction.
 *   /dunkelflaute-outlook   15-day probabilities from three weather ensembles (prediction/live.py)
 *   /dunkelflaute-backtest  honest scores of the method on past data (prediction/train.py)
 */

const COLORS = {
    risk: ['#2E9E5B', '#E0A800', '#D6304A'],
    share: '#3366CC',
    band: 'rgba(51, 102, 204, 0.15)',
    threshold: '#555555',
    model: '#3366CC',
    persistence: '#999999',
    tso: '#E07B00',
    era5: '#2E9E5B',
}
// Blocking regimes (calm, Dunkelflaute-prone) in warm colours, windy westerly regimes in cool colours
const REGIME_COLORS = [
    ['European blocking', '#D6304A'], ['Scandinavian blocking', '#7B3294'], ['Northern blocking', '#F4A582'],
    ['Greenland blocking', '#C2A5CF'], ['Atlantic ridge', '#3366CC'], ['Zonal', '#008837'],
    ['Trough', '#66C2A5'], ['No clear regime', '#BBBBBB'],
]
const regimeColor = name => REGIME_COLORS.find(([prefix]) => name.startsWith(prefix))?.[1] ?? '#888888'
const PLOT_CONFIG = { responsive: true, displaylogo: false }
const BASE_LAYOUT = { margin: { l: 60, r: 60, t: 30, b: 50 }, font: { family: 'system-ui, sans-serif', size: 13 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', hovermode: 'x unified' }

const select = document.getElementById('df-threshold')
let outlook = null
let backtest = null

const percent = value => value === null || value === undefined ? '–' : `${Math.round(value * 100)}%`
const weekday = date => new Date(date + 'T12:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })

function riskColor(p) {
    return p >= 0.5 ? COLORS.risk[2] : p >= 0.2 ? COLORS.risk[1] : COLORS.risk[0]
}

function renderOutlook() {
    const chart = document.getElementById('df-outlook-chart')
    if (!outlook || !chart || typeof Plotly === 'undefined') return
    const threshold = select.value
    const days = outlook.days
    const x = days.map(d => d.date)
    const p = days.map(d => d.probability[threshold])
    const traces = [
        { type: 'bar', name: 'Dunkelflaute probability', x, y: p.map(v => v * 100), marker: { color: p.map(riskColor) },
          hovertemplate: '%{y:.0f}%', yaxis: 'y' },
        { type: 'scatter', mode: 'lines', name: 'Renewable share, 90th percentile', x, y: days.map(d => d.share.p90 * 100),
          line: { width: 0 }, yaxis: 'y2', hoverinfo: 'skip', showlegend: false },
        { type: 'scatter', mode: 'lines', name: 'Renewable share, 10–90 % range', x, y: days.map(d => d.share.p10 * 100),
          fill: 'tonexty', fillcolor: COLORS.band, line: { width: 0 }, yaxis: 'y2', hoverinfo: 'skip' },
        { type: 'scatter', mode: 'lines+markers', name: 'Renewable share (median)', x, y: days.map(d => d.share.p50 * 100),
          line: { color: COLORS.share, width: 2 }, yaxis: 'y2', hovertemplate: '%{y:.0f}%' },
    ]
    const layout = {
        ...BASE_LAYOUT,
        legend: { orientation: 'h', y: -0.2 },
        xaxis: { type: 'date', tickformat: '%a %d %b' },
        yaxis: { title: { text: 'Dunkelflaute probability (%)' }, range: [0, 100], fixedrange: true },
        yaxis2: { title: { text: 'Renewable share of demand (%)' }, overlaying: 'y', side: 'right', range: [0, 100],
                  fixedrange: true, showgrid: false },
        shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y2', y0: threshold * 100, y1: threshold * 100,
                   line: { color: COLORS.threshold, width: 1.5, dash: 'dash' } }],
        annotations: [{ xref: 'paper', x: 1, yref: 'y2', y: threshold * 100, xanchor: 'right', yanchor: 'bottom',
                        text: `threshold ${Math.round(threshold * 100)}%`, showarrow: false, font: { size: 11, color: COLORS.threshold } }],
    }
    Plotly.react(chart, traces, layout, PLOT_CONFIG)

    const worst = days.reduce((a, b) => (b.probability[threshold] > a.probability[threshold] ? b : a), days[0])
    const risky = days.filter(d => d.probability[threshold] >= 0.5)
    const members = outlook.ensembles.map(e => `${e.name} (${e.members})`).join(', ')
    document.getElementById('df-outlook-summary').innerHTML =
        `Highest risk: <b>${weekday(worst.date)}</b> with <b>${percent(worst.probability[threshold])}</b>. ` +
        `${risky.length ? `${risky.length} of ${days.length} days are more likely than not to be Dunkelflaute days.` :
                          'No day is more likely than not to be a Dunkelflaute day.'}` +
        `<br><small class="text-muted">Ensembles: ${members}. Issued ${new Date(outlook.issued).toLocaleString('en-GB', { timeZone: 'Europe/Berlin' })} (Berlin time).</small>`

    const table = document.getElementById('df-outlook-table')
    table.innerHTML = '<thead><tr><th>Day</th><th>Probability</th><th>Renewable share (10–90 %)</th>' +
        '<th>Wind on/offshore</th><th>Solar</th><th>Demand</th></tr></thead><tbody>' +
        days.map(d => `<tr><td>${weekday(d.date)}</td>` +
            `<td><span class="df-dot" style="background:${riskColor(d.probability[threshold])}"></span>${percent(d.probability[threshold])}</td>` +
            `<td>${percent(d.share.p50)} (${percent(d.share.p10)}–${percent(d.share.p90)})</td>` +
            `<td>${Math.round(d.gwh.wind_on)} / ${Math.round(d.gwh.wind_off)} GWh</td><td>${Math.round(d.gwh.pv)} GWh</td>` +
            `<td>${Math.round(d.gwh.load)} GWh</td></tr>`).join('') + '</tbody>'
}

function renderRegimes() {
    const chart = document.getElementById('df-regime-chart')
    if (!chart || !outlook?.regimes || typeof Plotly === 'undefined') {
        if (chart) chart.closest('.df-block').style.display = 'none'
        return
    }
    const { names, days } = outlook.regimes
    const rates = backtest?.regimes?.table ?? []
    const traces = names.map((name, k) => ({
        type: 'bar', name: rates[k]?.df_rate_winter ? `${name} (winter Dunkelflaute rate ${percent(rates[k].df_rate_winter[select.value])})` : name,
        x: days.map(d => d.date), y: days.map(d => d.probabilities[k] * 100),
        marker: { color: regimeColor(name) }, hovertemplate: '%{y:.0f}%',
    }))
    Plotly.react(chart, traces, { ...BASE_LAYOUT, barmode: 'stack', legend: { orientation: 'h', y: -0.25 },
        xaxis: { type: 'date', tickformat: '%a %d %b' },
        yaxis: { title: { text: 'Share of ECMWF members (%)' }, range: [0, 100], fixedrange: true } }, PLOT_CONFIG)
}

function renderBacktest() {
    if (!backtest || typeof Plotly === 'undefined') return
    const threshold = select.value
    const leads = backtest.nwp_leads ?? []
    const bss = (entry, key) => entry?.thresholds?.[threshold]?.[key]?.bss ?? null
    const skillChart = document.getElementById('df-skill-chart')
    const era5 = backtest.era5_dunkelflaute?.[threshold]?.model?.bss
    const traces = [
        { type: 'scatter', mode: 'lines+markers', name: 'This model with archived ECMWF forecasts', x: leads.map(l => l.lead),
          y: leads.map(l => bss(l, 'model')), line: { color: COLORS.model, width: 3 } },
        { type: 'scatter', mode: 'lines+markers', name: 'Persistence (today\'s situation continues)', x: leads.map(l => l.lead),
          y: leads.map(l => bss(l, 'persistence')), line: { color: COLORS.persistence, dash: 'dot' } },
    ]
    const tso = leads.find(l => l.lead === 1)?.thresholds?.[threshold]
    if (tso?.tso_day_ahead) {
        traces.push({ type: 'scatter', mode: 'markers', name: 'Grid operators\' day-ahead forecast (SMARD)', x: [1],
            y: [tso.tso_day_ahead.bss], marker: { color: COLORS.tso, size: 12, symbol: 'diamond' } })
    }
    const longRange = backtest.regimes?.long_range ?? []
    if (longRange.length) {
        traces.push({ type: 'scatter', mode: 'lines+markers', name: 'Weather regime of today only', x: longRange.map(r => r.lead),
            y: longRange.map(r => r.bss), line: { color: '#7B3294', dash: 'dash' } })
    }
    const shapes = era5 === undefined ? [] : [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: era5, y1: era5,
        line: { color: COLORS.era5, dash: 'dash', width: 1.5 } }]
    Plotly.react(skillChart, traces, { ...BASE_LAYOUT, hovermode: 'closest', legend: { orientation: 'h', y: -0.3 },
        xaxis: { title: { text: 'Lead time (days ahead)' }, type: 'log', tickvals: [1, 2, 3, 5, 7, 10, 14, 21, 28] },
        yaxis: { title: { text: 'Brier skill score vs. climatology' }, range: [-0.2, 1], zeroline: true },
        shapes, annotations: era5 === undefined ? [] : [{ xref: 'paper', x: 0, y: era5, xanchor: 'left', yanchor: 'bottom',
            showarrow: false, text: 'with perfect weather knowledge (ERA5)', font: { size: 11, color: COLORS.era5 } }] }, PLOT_CONFIG)

    const reliabilityChart = document.getElementById('df-reliability-chart')
    const reliabilityTraces = [{ type: 'scatter', mode: 'lines', x: [0, 1], y: [0, 1], name: 'perfect', line: { color: '#BBBBBB', dash: 'dot' } }]
    for (const lead of leads.filter(l => [1, 3, 7].includes(l.lead))) {
        const rows = lead.thresholds?.[String(backtest.main_threshold)]?.reliability ?? []
        reliabilityTraces.push({ type: 'scatter', mode: 'lines+markers', name: `${lead.lead} day${lead.lead > 1 ? 's' : ''} ahead`,
            x: rows.map(r => r.forecast), y: rows.map(r => r.observed), text: rows.map(r => `${r.n} days`) })
    }
    Plotly.react(reliabilityChart, reliabilityTraces, { ...BASE_LAYOUT, hovermode: 'closest', legend: { orientation: 'h', y: -0.3 },
        xaxis: { title: { text: 'Forecast probability' }, range: [0, 1] },
        yaxis: { title: { text: 'Observed frequency' }, range: [0, 1] } }, PLOT_CONFIG)

    const rows = leads.map(l => {
        const t = l.thresholds?.[threshold] ?? {}
        return `<tr><td>${l.lead}</td><td>${t.model?.bss ?? '–'}</td><td>${t.model?.auc ?? '–'}</td>` +
            `<td>${percent(t.model?.hit_rate)}</td><td>${percent(t.model?.false_alarm_ratio)}</td>` +
            `<td>${t.persistence?.bss ?? '–'}</td><td>${t.model?.events ?? '–'} / ${t.model?.days ?? '–'}</td>` +
            `<td>${(l.mae_share * 100).toFixed(1)} pp</td></tr>`
    }).join('')
    document.getElementById('df-skill-table').innerHTML = '<thead><tr><th>Days ahead</th><th>Brier skill</th><th>ROC AUC</th>' +
        '<th>Hit rate</th><th>False alarms</th><th>Persistence skill</th><th>Dunkelflaute days / days</th><th>Share error (MAE)</th></tr></thead>' +
        `<tbody>${rows || '<tr><td colspan="8">No archived forecasts in this backtest.</td></tr>'}</tbody>`

    const components = backtest.energy_model_era5?.components ?? {}
    const labels = { wind_on: 'Onshore wind', wind_off: 'Offshore wind', pv: 'Solar', load: 'Demand (grid load)', re_share: 'Renewable share' }
    document.getElementById('df-energy-table').innerHTML = '<thead><tr><th>Daily value</th><th>R²</th><th>Mean abs. error</th></tr></thead><tbody>' +
        Object.entries(labels).filter(([k]) => components[k]).map(([k, label]) => `<tr><td>${label}</td><td>${components[k].r2}</td>` +
            `<td>${k === 're_share' ? (components[k].mae * 100).toFixed(1) + ' pp' : Math.round(components[k].mae / 1000) + ' GWh'}</td></tr>`).join('') +
        '</tbody>'
    document.getElementById('df-energy-period').textContent = backtest.energy_model_era5?.period ?? ''

    const regimeRows = (backtest.regimes?.table ?? []).map(r => `<tr><td><span class="df-dot" style="background:${regimeColor(r.name)}"></span>${r.name}</td>` +
        `<td>${percent(r.winter_frequency)}</td><td>${percent(r.mean_share_winter)}</td><td>${percent(r.df_rate_winter?.[threshold])}</td>` +
        `<td>${r.persistence_days} days</td></tr>`).join('')
    document.getElementById('df-regime-table').innerHTML = '<thead><tr><th>Weather regime</th><th>Frequency (Oct–Mar)</th>' +
        '<th>Mean renewable share</th><th>Dunkelflaute days</th><th>Typical duration</th></tr></thead>' + `<tbody>${regimeRows}</tbody>`
}

function renderAll() {
    renderOutlook()
    renderRegimes()
    renderBacktest()
    document.querySelectorAll('.df-threshold-value').forEach(el => { el.textContent = `${Math.round(select.value * 100)}%` })
}

async function load() {
    if (!select) return
    select.addEventListener('change', renderAll)
    const chart = document.getElementById('df-outlook-chart')
    chart?.classList.add('chart-loading')
    const [outlookResult, backtestResult] = await Promise.allSettled([
        fetch('/dunkelflaute-outlook').then(r => { if (!r.ok) throw new Error(r.status); return r.json() }),
        fetch('/dunkelflaute-backtest').then(r => { if (!r.ok) throw new Error(r.status); return r.json() }),
    ])
    chart?.classList.remove('chart-loading')
    if (backtestResult.status === 'fulfilled') backtest = backtestResult.value
    if (outlookResult.status === 'fulfilled') outlook = outlookResult.value
    else document.getElementById('df-outlook-summary').textContent =
        'The weather ensembles could not be loaded right now. Please try again in a few minutes.'
    renderAll()
}

load()
