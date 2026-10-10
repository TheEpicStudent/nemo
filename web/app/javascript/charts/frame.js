export const MIN_WINDOW_ROWS = 5

export function minimumSpan(count) {
  return Math.min(count, MIN_WINDOW_ROWS)
}

export function clampWindow([start, end], count, minSpan = minimumSpan(count)) {
  const span = Math.min(count, Math.max(minSpan, end - start))
  const clampedStart = Math.min(Math.max(start, 0), count - span)
  return [clampedStart, clampedStart + span]
}

export function zoomWindow(window, count, factor, anchor = (window[0] + window[1]) / 2) {
  const [start, end] = window
  const span = end - start
  const nextSpan = Math.min(count, Math.max(minimumSpan(count), span * factor))
  const nextStart = anchor - (anchor - start) * (nextSpan / span)
  return clampWindow([nextStart, nextStart + nextSpan], count)
}

export function isFullWindow(window, count) {
  return !window || (window[0] <= 0.001 && window[1] >= count - 0.001)
}

export function interpolateWindow(from, to, progress) {
  return [from[0] + (to[0] - from[0]) * progress, from[1] + (to[1] - from[1]) * progress]
}
