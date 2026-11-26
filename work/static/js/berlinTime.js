"use strict";

/**
 * Time helpers for the Plotly charts.
 *
 * The API delivers unix timestamps in seconds (UTC), apiToChartTime in script.js turns them into ms. Plotly has no timezone setting for date axes,
 * so the timestamps are converted to Europe/Berlin wall clock strings ("YYYY-MM-DD HH:MM:SS")
 * before they are handed to Plotly. CET/CEST switches are handled by Intl.
 */
export { BERLIN_TZ, berlinOffsetMs, utcMsToBerlin, berlinToUtcMs }

const BERLIN_TZ = 'Europe/Berlin'
const HOUR_MS = 60 * 60 * 1000

const offsetFormatter = new Intl.DateTimeFormat('en-US', {
    timeZone: BERLIN_TZ, hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'
})
const offsetCache = new Map()  // offsets only change at DST switches, so cache them per UTC hour

/** Offset of Europe/Berlin to UTC in ms (3600000 in winter, 7200000 in summer) at the given UTC instant */
function berlinOffsetMs(utcMs) {
    const hourKey = Math.floor(utcMs / HOUR_MS)
    let offset = offsetCache.get(hourKey)
    if (offset === undefined) {
        const parts = {}
        for (const part of offsetFormatter.formatToParts(new Date(hourKey * HOUR_MS))) {
            parts[part.type] = part.value
        }
        const wallMs = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second)
        offset = wallMs - hourKey * HOUR_MS
        offsetCache.set(hourKey, offset)
    }
    return offset
}

/** UTC ms -> "YYYY-MM-DD HH:MM:SS" in Berlin local time (what Plotly shows on the axis) */
function utcMsToBerlin(utcMs) {
    return new Date(utcMs + berlinOffsetMs(utcMs)).toISOString().slice(0, 19).replace('T', ' ')
}

/** Plotly axis value (Berlin wall clock string or Date) -> UTC ms */
function berlinToUtcMs(axisValue) {
    let wallMs
    if (typeof axisValue === 'number') {
        wallMs = axisValue
    } else {
        // Plotly may return "2024-01-01", "2024-01-01 13:00" or "2024-01-01 13:00:00.1234"
        const [datePart, timePart = '00:00:00'] = String(axisValue).trim().split(/[ T]/)
        const [h = '00', m = '00', s = '00'] = timePart.split(':')
        const seconds = parseFloat(s) || 0
        const [year, month, day] = datePart.split('-').map(Number)
        wallMs = Date.UTC(year, (month || 1) - 1, day || 1, +h, +m, 0) + Math.round(seconds * 1000)
    }
    const guess = wallMs - berlinOffsetMs(wallMs)
    return wallMs - berlinOffsetMs(guess)
}
