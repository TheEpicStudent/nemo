const SVG_NS = "http://www.w3.org/2000/svg"
const INLINED_PROPERTIES = [
  "fill", "fill-opacity", "stroke", "stroke-width", "stroke-dasharray", "stroke-opacity", "stroke-linecap",
  "stroke-linejoin", "opacity", "font-family", "font-size", "font-weight", "font-variant-numeric",
  "stop-color", "stop-opacity", "shape-rendering", "paint-order", "visibility"
]
const OVERLAYS = ".cur, .dot, .x-pill, .brush-area, .pin-mark, .selection-area, .pin-ring"
const PADDING = 24
const TITLE_SIZE = 16
const SUBTITLE_SIZE = 12.5
const LEGEND_SIZE = 12
const LEGEND_GAP = 18
const LEGEND_KEY = 10
const SCALE_GAP = 6
const SCALE_STEP_GAP = 2
const FONT_STACK = "Geist, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
const PNG_SCALE = 2

const fontCache = new Map()

const escapeXml = (value) => String(value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")

function textWidth(text, size, weight = 400) {
  const context = textWidth.canvas ||= document.createElement("canvas").getContext("2d")
  context.font = `${weight} ${size}px ${FONT_STACK}`
  return context.measureText(String(text)).width
}

export async function embeddedFont(url) {
  if (!url) return ""
  if (!fontCache.has(url)) {
    fontCache.set(url, fetch(url)
      .then((response) => (response.ok ? response.blob() : null))
      .then((blob) => (blob ? readAsDataUrl(blob) : null))
      .catch(() => null))
  }
  const dataUrl = await fontCache.get(url)
  if (!dataUrl) return ""

  return `@font-face { font-family: "Geist"; font-weight: 100 900; src: url(${dataUrl}) format("woff2"); }`
}

function readAsDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

function inlineStyles(source, clone) {
  const sourceNodes = [source, ...source.querySelectorAll("*")]
  const cloneNodes = [clone, ...clone.querySelectorAll("*")]
  sourceNodes.forEach((node, index) => {
    const style = getComputedStyle(node)
    const declarations = INLINED_PROPERTIES.map((name) => `${name}:${style.getPropertyValue(name)}`)
    cloneNodes[index].setAttribute("style", declarations.join(";"))
  })
}

function legendKey(entry, x, top) {
  switch (entry.shape) {
    case "line":
      return `<rect x="${x}" y="${top - 5.5}" width="12" height="3" rx="1.5" fill="${entry.color}"/>`
    case "dot":
      return `<circle cx="${x + LEGEND_KEY / 2}" cy="${top - LEGEND_KEY / 2 + 1}" r="${LEGEND_KEY / 2}" fill="${entry.color}"/>`
    case "dashed":
      return `<line x1="${x}" x2="${x + 12}" y1="${top - 4}" y2="${top - 4}" stroke="${entry.color}" stroke-width="2" stroke-dasharray="3 2"/>`
    default:
      return `<rect x="${x}" y="${top - LEGEND_KEY + 1}" width="${LEGEND_KEY}" height="${LEGEND_KEY}" rx="3" fill="${entry.color}"/>`
  }
}

function legendMarkup(entries, { top, foreground }) {
  let x = PADDING
  return entries.map((entry) => {
    const label = `<text x="${x + 18}" y="${top}" font-size="${LEGEND_SIZE}" fill="${foreground}">${escapeXml(entry.label)}</text>`
    const markup = legendKey(entry, x, top) + label
    x += 18 + textWidth(entry.label, LEGEND_SIZE) + LEGEND_GAP
    return markup
  }).join("")
}

function scaleMarkup({ low, high, steps, extras = [], note }, { top, muted, width }) {
  let x = PADDING
  const label = (text, fill) => {
    const markup = `<text x="${x}" y="${top}" font-size="${LEGEND_SIZE}" fill="${fill}">${escapeXml(text)}</text>`
    x += textWidth(text, LEGEND_SIZE)
    return markup
  }
  const swatch = (color, outline) => {
    const markup = `<rect x="${x}" y="${top - LEGEND_KEY + 1}" width="${LEGEND_KEY}" height="${LEGEND_KEY}" rx="2" fill="${
      color}"${outline ? ` stroke="${muted}" stroke-opacity="0.35"` : ""}/>`
    x += LEGEND_KEY
    return markup
  }

  let markup = label(low, muted)
  x += SCALE_GAP
  markup += steps.map((color, index) => {
    if (index) x += SCALE_STEP_GAP
    return swatch(color)
  }).join("")
  x += SCALE_GAP
  markup += label(high, muted)
  extras.forEach((extra) => {
    x += LEGEND_GAP
    markup += swatch(extra.color, true)
    x += SCALE_GAP
    markup += label(extra.label, muted)
  })
  if (note) {
    markup += `<text x="${width - PADDING}" y="${top}" font-size="${LEGEND_SIZE}" fill="${muted}" text-anchor="end">${
      escapeXml(note)}</text>`
  }
  return markup
}

export async function exportSvg(chartElement, { title, subtitle, legend = [], scale = null, fontUrl, colors }) {
  const source = chartElement.querySelector("svg")
  if (!source) return null

  chartElement.classList.add("is-exporting")
  void chartElement.offsetWidth
  const clone = source.cloneNode(true)
  inlineStyles(source, clone)
  chartElement.classList.remove("is-exporting")
  clone.querySelectorAll(OVERLAYS).forEach((node) => node.remove())
  ;["role", "aria-label", "class", "style"].forEach((name) => clone.removeAttribute(name))

  const chartWidth = Number(source.getAttribute("width"))
  const chartHeight = Number(source.getAttribute("height"))
  const legendTop = subtitle ? 84 : 66
  const keyed = !!scale || legend.length > 1
  const chartTop = keyed ? legendTop + 16 : legendTop - 12
  const width = Math.ceil(chartWidth + PADDING * 2)
  const height = Math.ceil(chartTop + chartHeight + PADDING)
  clone.setAttribute("x", String(PADDING))
  clone.setAttribute("y", String(chartTop))
  const font = await embeddedFont(fontUrl)

  const header = `<text x="${PADDING}" y="${PADDING + TITLE_SIZE}" font-size="${TITLE_SIZE}" font-weight="600" fill="${
    colors.foreground}">${escapeXml(title)}</text>` +
    (subtitle
      ? `<text x="${PADDING}" y="${PADDING + TITLE_SIZE + 22}" font-size="${SUBTITLE_SIZE}" fill="${colors.muted}">${
        escapeXml(subtitle)}</text>`
      : "")
  const keys = scale
    ? scaleMarkup(scale, { top: legendTop, muted: colors.muted, width })
    : legend.length > 1 ? legendMarkup(legend, { top: legendTop, foreground: colors.foreground }) : ""

  return `<svg xmlns="${SVG_NS}" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" ` +
    `font-family="${escapeXml(FONT_STACK)}">` +
    (font ? `<style>${font}</style>` : "") +
    `<rect width="${width}" height="${height}" fill="${colors.background}"/>${header}${keys}` +
    new XMLSerializer().serializeToString(clone) + "</svg>"
}

export function svgToPng(markup, { scale = PNG_SCALE } = {}) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => {
      const canvas = document.createElement("canvas")
      canvas.width = Math.round(image.naturalWidth * scale)
      canvas.height = Math.round(image.naturalHeight * scale)
      const context = canvas.getContext("2d")
      context.scale(scale, scale)
      context.drawImage(image, 0, 0)
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("png encoding failed"))), "image/png")
    }
    image.onerror = () => reject(new Error("svg rendering failed"))
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`
  })
}
