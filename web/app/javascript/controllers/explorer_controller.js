import { Controller } from "@hotwired/stimulus"
import { modalsOpen, aboveOpen, popupOpen, drawerOpen } from "lib/layers"
import { PlotGestures } from "charts/gesture"
import { Overview } from "charts/overview"
import { exportSvg, svgToPng } from "charts/export"

const OPEN_DURATION = 340
const CLOSE_DURATION = 220
const FADE_DURATION = 160
const ZOOM_DURATION = 260
const ZOOM_STEP = 0.6
const OPEN_EASING = "cubic-bezier(0.16, 1, 0.3, 1)"
const CLOSE_EASING = "cubic-bezier(0.4, 0, 0.2, 1)"
const EDITABLE = "input, textarea, select, [contenteditable]:not([contenteditable='false'])"
const INTERACTIVE = "button, a, [role='switch'], [role='separator'], input, textarea, select"
const CARD = ".card, .foldcard"
const CHART_SOURCES = [
  {
    identifier: "chart",
    selector: "[data-controller~='chart']:not([data-chart-spark-value='true'])",
    detached: ["brush", "brush-href", "brush-keys"]
  },
  { identifier: "scatter", selector: "[data-controller~='scatter']", detached: [] },
  { identifier: "treemap", selector: "[data-controller~='treemap']", detached: [] },
  { identifier: "parts", selector: "[data-controller~='parts']", detached: [] },
  { identifier: "funnel", selector: "[data-controller~='funnel']", detached: [] },
  { identifier: "lorenz", selector: "[data-controller~='lorenz']", detached: [] }
]
const DISPLAY_KEYS = ["kind", "stacked", "yScale", "zero", "fit", "format", "grid", "notes", "overview", "labels", "xScale", "sizeBy"]
const STORAGE_PREFIX = "mn-explore-"
const URL_PARAMS = { chart: "explore", from: "xfrom", to: "xto" }
const URL_WRITE_DELAY = 150
const INSPECTOR_MIN_WIDTH = 900
const VIEW_MODES = ["chart", "split", "table"]
const INSPECTOR_LABELS = { point: "Point", stats: "In view" }
const DEFAULT_SPLIT = 0.4
const SPLIT_MIN = 0.2
const SPLIT_MAX = 0.75
const SPLIT_STEP = 0.05
const CSV_FORMULA = /^[=+\-@\t\r]/
const CSV_MIME = "text/csv;charset=utf-8"
const BYTE_ORDER_MARK = "\uFEFF"
const DOWNLOAD_REVOKE_DELAY = 1000
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/
const IMAGE_TYPES = { png: "image/png", svg: "image/svg+xml" }
const DELTA_PATHS = { up: "m18 15-6-6-6 6", down: "m6 9 6 6 6-6", flat: "M5 12h14" }
const DELTA_WORDS = { up: "up", down: "down", flat: "no change" }

function csvField(value) {
  if (value == null) return ""

  let text = String(value)
  if (typeof value === "string" && CSV_FORMULA.test(text)) text = `'${text}`
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function fileSlug(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")
}

function capturePointer(target, pointerId) {
  try {
    target.setPointerCapture(pointerId)
  } catch {
    return false
  }
  return true
}

function element(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text != null) node.textContent = text
  return node
}

export default class extends Controller {
  static targets = [
    "dialog", "panel", "title", "subtitle", "body", "legend", "plot", "displayButton", "display",
    "zoomControls", "zoomInButton", "zoomOutButton", "zoomResetButton", "toolButton", "overview",
    "range", "rangeLabel", "rangeCount",
    "inspector", "inspectorButton", "point", "pinButton", "pinLabel", "announcer", "stats", "statsRange",
    "pointHeading", "statsHeading",
    "viewButton", "splitHandle", "table", "menu", "toastTemplate", "warningTemplate", "imageAction",
    "presentAction", "presentSeparator", "presentLabel", "toastRegion"
  ]

  connect() {
    this.dialog = this.dialogTarget
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)")
    this.onClick = this.onClick.bind(this)
    this.onKeydown = this.onKeydown.bind(this)
    this.onPointerdown = this.onPointerdown.bind(this)
    this.onKeyup = this.onKeyup.bind(this)
    this.onFullscreenChange = this.onFullscreenChange.bind(this)
    this.tool = "select"
    this.overview = new Overview(this.overviewTarget, {
      onWindow: (window, { animate }) => this.moveWindow(window, { animate }),
      onReset: () => this.resetZoom()
    })
    this.resizeObserver = new ResizeObserver(() => this.renderOverview())
    this.resizeObserver.observe(this.overviewTarget)
    this.element.addEventListener("click", this.onClick)
    document.addEventListener("keydown", this.onKeydown)
    document.addEventListener("keyup", this.onKeyup)
    document.addEventListener("fullscreenchange", this.onFullscreenChange)
    this.dialog.addEventListener("pointerdown", this.onPointerdown)
    this.presentActionTarget.hidden = !document.fullscreenEnabled
    this.presentSeparatorTarget.hidden = !document.fullscreenEnabled
    this.restoreFromUrl()
  }

  disconnect() {
    this.element.removeEventListener("click", this.onClick)
    document.removeEventListener("keydown", this.onKeydown)
    document.removeEventListener("keyup", this.onKeyup)
    document.removeEventListener("fullscreenchange", this.onFullscreenChange)
    this.dialog.removeEventListener("pointerdown", this.onPointerdown)
    clearTimeout(this.urlTimer)
    this.resizeObserver.disconnect()
    this.overview.destroy()
    this.hide()
    this.reset()
  }

  get isOpen() {
    return !this.dialog.hidden
  }

  open(card, trigger = null, { animate = true } = {}) {
    if (!card || this.isOpen) return

    this.card = card
    this.key = trigger?.dataset.explore || null
    this.opener = trigger || document.activeElement
    this.fillHeader(card, trigger)
    this.dialog.hidden = false
    this.coverPage()
    this.mountChart(card)
    if (animate) this.animateOpen()
    this.panelTarget.focus({ preventScroll: true })
    this.writeUrl()
  }

  restoreFromUrl() {
    const params = new URL(window.location.href).searchParams
    const key = params.get(URL_PARAMS.chart)
    if (!key) return

    const trigger = [...this.element.querySelectorAll("[data-explore]")].find((element) => element.dataset.explore === key)
    if (!trigger) return

    const from = params.get(URL_PARAMS.from)
    const to = params.get(URL_PARAMS.to)
    this.pendingRange = from && to ? [from, to] : null
    this.open(trigger.closest(CARD), trigger, { animate: false })
  }

  writeUrl() {
    clearTimeout(this.urlTimer)
    const url = new URL(window.location.href)
    const range = this.isOpen && this.zoomWindow && this.chart?.rangeOf ? this.chart.rangeOf(this.zoomWindow) : null
    if (this.isOpen && this.key) url.searchParams.set(URL_PARAMS.chart, this.key)
    else url.searchParams.delete(URL_PARAMS.chart)
    if (range) {
      url.searchParams.set(URL_PARAMS.from, range.from)
      url.searchParams.set(URL_PARAMS.to, range.to)
    } else {
      url.searchParams.delete(URL_PARAMS.from)
      url.searchParams.delete(URL_PARAMS.to)
    }
    if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url)
  }

  scheduleUrl() {
    clearTimeout(this.urlTimer)
    this.urlTimer = setTimeout(() => this.writeUrl(), URL_WRITE_DELAY)
  }

  close() {
    if (!this.isOpen || this.closing) return

    this.closing = true
    if (this.presenting) document.exitFullscreen().catch(() => {})
    const clip = this.cardClip()
    const animation = clip
      ? this.panelTarget.animate(
        [{ clipPath: this.fullClip() }, { clipPath: clip, opacity: 0.6 }],
        { duration: CLOSE_DURATION, easing: CLOSE_EASING, fill: "forwards" })
      : this.panelTarget.animate(
        [{ opacity: 1 }, { opacity: 0, transform: "scale(0.985)" }],
        { duration: this.duration(FADE_DURATION), fill: "forwards" })
    animation.finished.catch(() => {}).then(() => this.finishClose())
  }

  hide() {
    this.closing = false
    this.dialog.hidden = true
    this.uncoverPage()
  }

  coverPage() {
    const area = this.dialog.parentElement
    this.covered = [...area.children].filter((element) => element !== this.dialog && !element.inert)
    this.covered.forEach((element) => { element.inert = true })
  }

  uncoverPage() {
    this.covered?.forEach((element) => { element.inert = false })
    this.covered = []
  }

  layerAbove() {
    return modalsOpen() > 0 || aboveOpen() || drawerOpen() || popupOpen()
  }

  dismiss() {
    if (!this.displayTarget.hidden) {
      this.closeDisplay({ restoreFocus: true })
      return
    }
    if (this.gestures?.active) {
      this.gestures.cancel()
      return
    }
    if (this.pin != null) {
      this.setPin(null)
      return
    }
    this.close()
  }

  finishClose() {
    if (!this.isOpen) return

    const opener = this.opener
    this.hide()
    this.reset()
    this.writeUrl()
    if (opener?.isConnected && typeof opener.focus === "function") opener.focus({ preventScroll: true })
  }

  onClick(event) {
    const trigger = event.target.closest("[data-explore]")
    if (!trigger || this.dialog.contains(trigger)) return

    event.preventDefault()
    this.open(trigger.closest(CARD), trigger)
  }

  onPointerdown(event) {
    if (this.displayTarget.hidden) return
    if (this.displayTarget.contains(event.target) || this.displayButtonTarget.contains(event.target)) return
    this.closeDisplay()
  }

  onKeydown(event) {
    if (event.defaultPrevented) return
    if (!this.isOpen) {
      if (this.isExpandShortcut(event)) this.openFocusedCard(event)
      return
    }
    if (this.layerAbove()) return
    if (event.key === "Escape" && document.fullscreenElement) return
    if (event.key === "Escape") {
      event.preventDefault()
      this.dismiss()
      return
    }
    if (event.key === " " && !event.target.closest?.(INTERACTIVE)) {
      event.preventDefault()
      this.setSpaceHeld(true)
      return
    }

    const shortcut = this.shortcutFor(event)
    if (!shortcut) return

    event.preventDefault()
    shortcut()
  }

  shortcutFor(event) {
    if (event.metaKey || event.ctrlKey || event.altKey || event.target.closest?.(EDITABLE)) return null
    if (event.key === "Enter") return event.target.closest?.(INTERACTIVE) ? null : () => this.pinFromKeyboard()

    switch (event.key.toLowerCase()) {
      case "+": case "=": return () => this.zoomIn()
      case "-": case "_": return () => this.zoomOut()
      case "0": return () => this.resetZoom()
      case "b": return () => this.chooseTool({ params: { tool: "select" } })
      case "h": return () => this.chooseTool({ params: { tool: "pan" } })
      case "d": return () => this.toggleDisplay()
      case "g": return () => this.toggleSettingIfShown("grid")
      case "a": return () => this.toggleSettingIfShown("notes")
      case "n": return () => this.toggleSettingIfShown("overview")
      case "i": return () => this.toggleInspector()
      case "c": return () => this.copyImage()
      case "f": return () => this.togglePresentation()
      case "1": return () => this.chooseView({ params: { view: "chart" } })
      case "2": return () => this.chooseView({ params: { view: "split" } })
      case "3": return () => this.chooseView({ params: { view: "table" } })
      default: return null
    }
  }

  onKeyup(event) {
    if (event.key === " ") this.setSpaceHeld(false)
  }

  setSpaceHeld(held) {
    if (this.spaceHeld === held) return

    this.spaceHeld = held
    this.renderTool()
  }

  chooseTool({ params: { tool } }) {
    if (!this.canZoom) return

    this.tool = tool === "pan" ? "pan" : "select"
    this.renderTool()
  }

  get panMode() {
    return this.tool === "pan" || !!this.spaceHeld
  }

  renderTool() {
    this.toolButtonTargets.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.explorerToolParam === this.tool))
    })
    this.plotTarget.classList.toggle("is-pannable", this.panMode && !!this.zoomWindow)
  }

  startGestures() {
    this.gestures?.destroy()
    this.gestures = new PlotGestures(this.plotTarget, {
      panMode: () => this.panMode,
      hover: (event) => this.chart?.track(event),
      leave: () => this.chart?.clear(),
      tap: (event) => {
        if (event.pointerType === "touch") this.chart?.track(event)
        this.togglePinAt(event)
      },
      brushStart: () => {
        if (!this.canZoom) return false
        this.chart.clear()
        return true
      },
      brushMove: (start, event) => this.chart.previewSelection(this.chart.anchorAt(start), this.chart.anchorAt(event)),
      brushEnd: (start, event) => this.zoomToSelection(this.chart.anchorAt(start), this.chart.anchorAt(event)),
      pan: (dx, dy) => this.panBy(dx, dy),
      panEnd: () => this.plotTarget.classList.remove("is-panning"),
      zoom: (factor, event) => {
        if (this.canZoom) this.zoomAround(factor, this.chart.anchorAt(event))
      },
      pinchStart: (center) => {
        this.pinchOrigin = this.canZoom ? { window: this.currentWindow(), anchor: this.chart.anchorAt(center) } : null
      },
      pinch: (scale) => this.zoomFromOrigin(scale),
      doubleClick: () => {
        this.setPin(this.pinBeforeClick ?? null)
        this.resetZoom()
      },
      cancel: () => {
        this.chart?.clear()
        this.plotTarget.classList.remove("is-panning")
      }
    })
  }

  currentWindow() {
    return this.zoomWindow || this.chart?.fullWindow?.() || null
  }

  zoomToSelection(from, to) {
    this.chart.clear()
    if (from == null || to == null) return

    const target = this.chart.windowFromSelection(from, to)
    if (target) this.animateWindow(target)
  }

  panBy(dx, dy = 0) {
    if (!this.chart || !this.zoomWindow) return

    cancelAnimationFrame(this.zoomFrame)
    this.plotTarget.classList.add("is-panning")
    this.applyWindow(this.chart.panWindow(this.zoomWindow, dx, dy))
  }

  zoomAround(factor, anchor) {
    if (!this.canZoom || anchor == null) return

    cancelAnimationFrame(this.zoomFrame)
    this.applyWindow(this.chart.zoomWindowAt(this.currentWindow(), factor, anchor))
  }

  zoomFromOrigin(scale) {
    const origin = this.pinchOrigin
    if (!this.canZoom || !origin || origin.anchor == null) return

    this.applyWindow(this.chart.zoomWindowAt(origin.window, scale, origin.anchor))
  }

  isExpandShortcut(event) {
    if (event.key !== "v" && event.key !== "V") return false
    if (event.metaKey || event.ctrlKey || event.altKey) return false
    return !event.target.closest?.(EDITABLE)
  }

  openFocusedCard(event) {
    if (this.layerAbove()) return

    const trigger = this.element.querySelector(":is(.card, .foldcard):hover [data-explore]") ||
      document.activeElement?.closest?.(CARD)?.querySelector("[data-explore]")
    if (!trigger) return

    event.preventDefault()
    this.open(trigger.closest(CARD), trigger)
  }

  reset() {
    this.panelTarget.getAnimations().forEach((animation) => animation.cancel())
    this.bodyTarget.getAnimations().forEach((animation) => animation.cancel())
    this.plotTarget.replaceChildren()
    this.legendTarget.replaceChildren()
    this.legendTarget.hidden = true
    this.displayTarget.hidden = true
    this.displayButtonTarget.setAttribute("aria-expanded", "false")
    this.chart = null
    this.chartIdentifier = null
    this.chartMount = null
    this.hiddenSeries = new Set()
    this.displayOverrides = {}
    cancelAnimationFrame(this.zoomFrame)
    this.gestures?.destroy()
    this.gestures = null
    this.pinchOrigin = null
    this.zoomWindow = null
    this.tool = "select"
    this.spaceHeld = false
    this.plotTarget.classList.remove("is-pannable", "is-panning")
    this.zoomControlsTarget.hidden = true
    this.overview?.clear()
    this.overviewTarget.hidden = true
    this.rangeTarget.hidden = true
    this.pendingRange = null
    this.pin = null
    this.hoverIndex = null
    this.pinBeforeClick = null
    this.inspectorOpen = false
    this.inspectorTarget.hidden = true
    this.pointTarget.replaceChildren()
    this.statsTarget.replaceChildren()
    this.statsRangeTarget.textContent = ""
    cancelAnimationFrame(this.rangeFrame)
    this.rangeFrame = null
    this.tableTarget.replaceChildren()
    this.closeMenu()
    this.tableSort = null
    this.tableColumns = null
    this.viewMode = "chart"
    delete this.dialog.dataset.viewMode
    this.announcerTarget.textContent = ""
    this.card = null
    this.key = null
    this.opener = null
  }

  mountChart(card) {
    const kind = CHART_SOURCES.find((entry) => card.querySelector(entry.selector))
    const source = kind && card.querySelector(kind.selector)
    if (!source) {
      const empty = card.querySelector(".empty")
      this.plotTarget.replaceChildren(empty ? empty.cloneNode(true) : this.emptyState())
      return
    }

    const mount = source.cloneNode(false)
    mount.removeAttribute("id")
    kind.detached.forEach((name) => mount.removeAttribute(`data-${kind.identifier}-${name}-value`))
    this.chartIdentifier = kind.identifier
    this.chartMount = mount
    this.hiddenSeries = new Set()
    this.displayOverrides = this.loadDisplay()
    const saved = this.readPreferences()
    this.inspectorOpen = typeof saved.inspector === "boolean"
      ? saved.inspector
      : this.panelTarget.clientWidth >= INSPECTOR_MIN_WIDTH
    this.viewMode = VIEW_MODES.includes(saved.view) ? saved.view : "chart"
    this.setSplit(typeof saved.split === "number" ? saved.split : DEFAULT_SPLIT)
    this.applyViewMode()
    this.writeView()
    this.plotTarget.replaceChildren(mount)
    this.startGestures()
  }

  get view() {
    return {
      fill: true, title: this.titleTarget.textContent, legend: false, pointer: "external", hidden: [...this.hiddenSeries],
      ...this.displayOverrides, ...(this.zoomWindow ? { window: this.zoomWindow } : {}),
      ...(this.pin != null ? { pin: this.pin } : {})
    }
  }

  get display() {
    return { ...this.displayDefaults(), ...this.displayOverrides }
  }

  get canZoom() {
    return !!this.chart?.zoomable?.()
  }

  legendEntries() {
    return this.chart?.legendEntries?.() || []
  }

  displayDefaults() {
    return this.chart?.displayDefaults?.() || {}
  }

  displayOptions() {
    return this.chart?.displayOptions?.() || {}
  }

  writeView() {
    this.chartMount?.setAttribute(`data-${this.chartIdentifier}-view-value`, JSON.stringify(this.view))
  }

  chartReady(event) {
    this.chart = this.application.getControllerForElementAndIdentifier(event.target, this.chartIdentifier)
    if (!this.chart) return
    if (this.pendingRange) {
      const restored = this.chart.windowForKeys?.(...this.pendingRange)
      this.pendingRange = null
      if (restored && this.canZoom) this.applyWindow(restored)
    }
    this.labels = { ...INSPECTOR_LABELS, ...this.chart.inspectorLabels?.() }
    this.pointHeadingTarget.textContent = this.labels.point
    this.statsHeadingTarget.textContent = this.labels.stats
    this.renderLegend()
    this.renderDisplay()
    this.renderZoom()
    this.renderTool()
    this.renderOverview()
    this.renderInspector()
    this.renderStats()
    this.renderTable()
  }

  chooseView({ params: { view } }) {
    if (!this.chart || !VIEW_MODES.includes(view) || view === this.viewMode) return

    this.viewMode = view
    this.savePreferences()
    this.applyViewMode()
    this.renderOverview()
    this.renderTable()
  }

  applyViewMode() {
    this.dialog.dataset.viewMode = this.viewMode
    this.viewButtonTargets.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.explorerViewParam === this.viewMode))
    })
    this.imageActionTargets.forEach((button) => { button.disabled = this.viewMode === "table" })
  }

  setSplit(ratio) {
    this.split = Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, ratio))
    this.dialog.style.setProperty("--explorer-split", `${(this.split * 100).toFixed(1)}%`)
    this.splitHandleTarget.setAttribute("aria-valuenow", String(Math.round(this.split * 100)))
  }

  startResize(event) {
    if (event.button !== 0) return

    event.preventDefault()
    this.resizing = true
    capturePointer(this.splitHandleTarget, event.pointerId)
  }

  resize(event) {
    if (!this.resizing) return

    const area = this.splitHandleTarget.parentElement.getBoundingClientRect()
    this.setSplit((area.bottom - event.clientY) / area.height)
  }

  endResize() {
    if (!this.resizing) return

    this.resizing = false
    this.savePreferences()
  }

  resizeWithKeys(event) {
    const step = { ArrowUp: SPLIT_STEP, ArrowDown: -SPLIT_STEP }[event.key]
    if (!step) return

    event.preventDefault()
    this.setSplit(this.split + step)
    this.savePreferences()
  }

  renderTable() {
    if (this.viewMode === "chart" || !this.chart) return

    const data = this.chart.tableData(this.zoomWindow)
    if (!data) {
      this.tableTarget.replaceChildren()
      return
    }

    const scrollTop = this.tableTarget.scrollTop
    const table = element("table", "data-table explorer-data-table")
    table.append(this.tableHead(data.columns), this.tableBody(data))
    if (data.footer) table.append(this.tableFoot(data))
    this.tableTarget.replaceChildren(table)
    this.tableTarget.scrollTop = scrollTop
  }

  tableHead(columns) {
    const head = element("thead")
    const row = element("tr")
    columns.forEach((column) => {
      const cell = element("th", column.numeric ? "col-num" : null)
      cell.scope = "col"
      const sorted = this.tableSort?.key === column.key
      cell.setAttribute("aria-sort", sorted ? (this.tableSort.direction > 0 ? "ascending" : "descending") : "none")
      const button = element("button", "explorer-sort")
      button.type = "button"
      button.dataset.action = "explorer#sortTable"
      button.dataset.explorerColumnParam = column.key
      if (column.colorClass) {
        const key = element("i", `explorer-legend-key is-${column.shape} ${column.colorClass}`)
        if (column.color) key.style.color = column.color
        button.append(key)
      }
      button.append(element("span", null, column.label || ""))
      if (!column.label) button.append(element("span", "visually-hidden", "Row"))
      if (sorted) button.append(element("span", "explorer-sort-mark", this.tableSort.direction > 0 ? "↑" : "↓"))
      cell.append(button)
      row.append(cell)
    })
    head.append(row)
    this.tableColumns = columns
    return head
  }

  tableBody(data) {
    const body = element("tbody")
    this.sortedRows(data.rows).forEach((entry) => {
      const row = element("tr")
      row.dataset.index = String(entry.index)
      row.classList.toggle("is-pinned", entry.index === this.pin)
      row.classList.toggle("is-active", entry.index === this.hoverIndex)
      data.columns.forEach((column) => {
        const cell = element("td", column.numeric ? "col-num" : null, entry.display[column.key])
        if (!column.numeric && entry.note) cell.append(element("span", "explorer-row-note", entry.note))
        row.append(cell)
      })
      body.append(row)
    })
    return body
  }

  tableFoot(data) {
    const foot = element("tfoot")
    const row = element("tr")
    data.columns.forEach((column, index) => {
      const text = index === 0 ? data.footer.label : data.footer.values[column.key] || ""
      row.append(element("td", column.numeric ? "col-num" : null, text))
    })
    foot.append(row)
    return foot
  }

  sortedRows(rows) {
    const sort = this.tableSort
    if (!sort) return rows

    return [...rows].sort((a, b) => {
      const left = a.values[sort.key]
      const right = b.values[sort.key]
      if (left == null && right == null) return 0
      if (left == null) return 1
      if (right == null) return -1
      return (left < right ? -1 : left > right ? 1 : 0) * sort.direction
    })
  }

  sortTable({ params: { column } }) {
    const numeric = this.tableColumns?.find((entry) => entry.key === column)?.numeric
    const first = numeric ? -1 : 1
    const current = this.tableSort
    if (current?.key !== column) this.tableSort = { key: column, direction: first }
    else if (current.direction === first) this.tableSort = { key: column, direction: -first }
    else this.tableSort = null
    this.renderTable()
  }

  hoverRow(event) {
    const row = event.target.closest("tbody tr[data-index]")
    if (!row || !this.chart) return

    const index = Number(row.dataset.index)
    if (index !== this.hoverIndex) this.chart.showIndex(index)
  }

  leaveTable() {
    this.chart?.clear()
  }

  clickRow(event) {
    const row = event.target.closest("tbody tr[data-index]")
    if (!row) return

    const index = Number(row.dataset.index)
    this.setPin(index === this.pin ? null : index)
  }

  syncTableRows({ scroll = false } = {}) {
    if (this.viewMode === "chart") return

    this.tableTarget.querySelectorAll("tbody tr").forEach((row) => {
      const index = Number(row.dataset.index)
      row.classList.toggle("is-pinned", index === this.pin)
      row.classList.toggle("is-active", index === this.hoverIndex)
    })
    if (!scroll) return

    const target = this.pin ?? this.hoverIndex
    this.tableTarget.querySelector(`tbody tr[data-index="${target}"]`)?.scrollIntoView({ block: "nearest" })
  }

  buildCsv() {
    const data = this.chart?.tableData(this.zoomWindow)
    if (!data) return null

    const rows = this.sortedRows(data.rows)
    const withNotes = rows.some((row) => row.note)
    const header = data.columns.map((column) => column.label || "label")
    if (withNotes) header.push("note")
    const lines = [header.map(csvField).join(",")]
    rows.forEach((row) => {
      const fields = data.columns.map((column) => row.values[column.key])
      if (withNotes) fields.push(row.note)
      lines.push(fields.map(csvField).join(","))
    })
    return lines.join("\r\n")
  }

  exportFilename(extension) {
    const range = this.chart.rangeOf?.(this.zoomWindow)
    const base = fileSlug(this.key || this.titleTarget.textContent || "chart") || "chart"
    return range ? `${base}_${fileSlug(range.from)}_${fileSlug(range.to)}.${extension}` : `${base}.${extension}`
  }

  async exportImage({ params: { format } }) {
    this.closeMenu()
    if (!IMAGE_TYPES[format]) return

    try {
      const markup = await this.exportMarkup()
      if (!markup) throw new Error("nothing to export")

      const blob = format === "png" ? await svgToPng(markup) : new Blob([markup], { type: IMAGE_TYPES.svg })
      this.downloadFile(blob, this.exportFilename(format))
    } catch {
      this.showToast("Export failed", { warning: true })
    }
  }

  copyImage() {
    this.closeMenu()
    if (!this.chart || this.viewMode === "table") return
    if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
      this.showToast("Clipboard unavailable", { warning: true })
      return
    }

    let renderFailed = false
    const png = Promise.resolve(this.exportMarkup()).then((markup) => {
      if (!markup) throw new Error("nothing to export")
      return svgToPng(markup)
    }).catch((error) => {
      renderFailed = true
      throw error
    })
    navigator.clipboard.write([new ClipboardItem({ [IMAGE_TYPES.png]: png })])
      .then(() => this.showToast("Copied image"))
      .catch(() => this.showToast(renderFailed ? "Export failed" : "Clipboard unavailable", { warning: true }))
  }

  exportMarkup() {
    const chartElement = this.chartMount?.querySelector(":scope > :is(.chart, .tree)")
    if (!this.chart || !chartElement || this.viewMode === "table") return null

    this.chart.clear()
    return exportSvg(chartElement, {
      title: this.titleTarget.textContent,
      subtitle: this.exportSubtitle(),
      ...this.exportLegend(),
      fontUrl: this.dialog.dataset.exportFont,
      colors: {
        background: getComputedStyle(this.panelTarget).backgroundColor,
        foreground: getComputedStyle(this.titleTarget).color,
        muted: getComputedStyle(this.subtitleTarget).color
      }
    })
  }

  exportLegend() {
    const probe = element("span")
    this.panelTarget.append(probe)
    const resolve = (colorClass, color) => {
      probe.className = colorClass || ""
      probe.style.color = color || ""
      return getComputedStyle(probe).color
    }
    const scale = this.chart.legendScale?.()
    const legend = scale
      ? {
        scale: {
          low: scale.low, high: scale.high, note: scale.note,
          steps: scale.steps.map((color) => resolve(null, color)),
          extras: (scale.extras || []).map((extra) => ({ label: extra.label, color: resolve(null, extra.color) }))
        }
      }
      : {
        legend: this.legendEntries()
          .filter((entry) => !this.hiddenSeries.has(entry.key))
          .map((entry) => ({ label: entry.label, shape: entry.shape, color: resolve(entry.colorClass, entry.color) }))
      }
    probe.remove()
    return legend
  }

  exportSubtitle() {
    const range = this.chart.rangeOf?.(this.zoomWindow)
    if (!range) return this.subtitleTarget.textContent

    const describe = (key, label) => (range.daily && ISO_DAY.test(key)
      ? new Date(`${key}T00:00:00Z`).toLocaleDateString("en-US", {
        month: "short", day: "numeric", year: "numeric", timeZone: "UTC"
      })
      : label)
    const from = describe(range.from, range.fromLabel)
    const to = describe(range.to, range.toLabel)
    return from === to ? from : `${from} to ${to}`
  }

  downloadFile(blob, filename) {
    const url = URL.createObjectURL(blob)
    const link = element("a")
    link.href = url
    link.download = filename
    link.hidden = true
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), DOWNLOAD_REVOKE_DELAY)
  }

  async copyCsv() {
    this.closeMenu()
    const csv = this.buildCsv()
    if (!csv) return

    try {
      await navigator.clipboard.writeText(csv)
      this.showToast("Copied CSV")
    } catch {
      this.showToast("Clipboard unavailable", { warning: true })
    }
  }

  downloadCsv() {
    this.closeMenu()
    const csv = this.buildCsv()
    if (!csv) return

    this.downloadFile(new Blob([BYTE_ORDER_MARK, csv], { type: CSV_MIME }), this.exportFilename("csv"))
  }

  get presenting() {
    return document.fullscreenElement === this.dialog
  }

  async togglePresentation() {
    this.closeMenu()
    if (!this.isOpen || !document.fullscreenEnabled) return

    try {
      if (this.presenting) await document.exitFullscreen()
      else await this.dialog.requestFullscreen()
    } catch {
      this.showToast("Fullscreen unavailable", { warning: true })
    }
  }

  onFullscreenChange() {
    const presenting = this.presenting
    this.presentLabelTarget.textContent = presenting ? "Stop presenting" : "Present"
    this.dialog.classList.toggle("is-presenting", presenting)
  }

  closeMenu() {
    if (this.hasMenuTarget) this.menuTarget.open = false
  }

  showToast(text, { warning = false } = {}) {
    const region = this.presenting ? this.toastRegionTarget : document.querySelector(".topbar-msgs:not(.explorer *)")
    const template = warning ? this.warningTemplateTarget : this.toastTemplateTarget
    if (!region || !template) return

    const toast = template.content.firstElementChild.cloneNode(true)
    const title = toast.querySelector(".flash-title")
    if (title) title.textContent = text
    region.append(toast)
  }

  rememberPin(event) {
    if (event.detail === 1) this.pinBeforeClick = this.pin
  }

  chartPoint(event) {
    const { index, source } = event.detail
    this.hoverIndex = index
    if (source === "keyboard" && this.pin != null && index != null) {
      this.setPin(index)
      return
    }
    this.renderInspector()
    this.syncTableRows({ scroll: source === "keyboard" })
  }

  togglePin() {
    this.setPin(this.pin != null ? null : this.hoverIndex)
  }

  togglePinAt(event) {
    const index = this.chart?.spot(event)
    this.setPin(index == null || index === this.pin ? null : index)
  }

  pinFromKeyboard() {
    if (this.hoverIndex != null) this.setPin(this.pin === this.hoverIndex ? null : this.hoverIndex)
    else if (this.pin != null) this.setPin(null)
  }

  setPin(index) {
    const next = Number.isInteger(index) ? index : null
    if (next === this.pin) return

    this.pin = next
    this.writeView()
    this.renderInspector()
    this.syncTableRows({ scroll: true })
    const details = next == null ? null : this.chart?.pointDetails(next)
    this.announcerTarget.textContent = details ? `Pinned ${details.title}` : "Unpinned"
  }

  toggleInspector() {
    if (!this.chart) return

    this.inspectorOpen = !this.inspectorOpen
    this.savePreferences()
    this.renderInspector()
    this.renderStats()
  }

  pinRow({ params: { index } }) {
    this.setPin(index)
  }

  scheduleRangeViews() {
    if (this.rangeFrame) return

    this.rangeFrame = requestAnimationFrame(() => {
      this.rangeFrame = null
      this.renderStats()
      this.renderTable()
    })
  }

  renderStats() {
    if (!this.inspectorOpen || !this.chart) return

    const stats = this.chart.rangeStats(this.zoomWindow)
    if (!stats) {
      this.statsRangeTarget.textContent = ""
      this.statsTarget.replaceChildren()
      return
    }

    if (stats.summary) {
      this.statsRangeTarget.textContent = stats.rangeLabel || ""
      this.statsTarget.replaceChildren(this.summaryList(stats.summary))
      return
    }

    this.statsRangeTarget.textContent = stats.fromLabel === stats.toLabel
      ? stats.fromLabel
      : `${stats.fromLabel} to ${stats.toLabel}`
    const filled = stats.series.filter((entry) => !entry.empty)
    if (!filled.length) {
      this.statsTarget.replaceChildren(element("p", "explorer-point-empty", "No values in view"))
      return
    }

    const nodes = [this.statsTable(stats, filled)]
    if (stats.hasPrevious && filled.some((entry) => entry.change)) nodes.push(this.changeList(filled))
    this.statsTarget.replaceChildren(...nodes)
  }

  summaryList(items) {
    const list = element("dl", "explorer-stats-summary")
    items.forEach(({ label, value }) => {
      const row = element("div", "explorer-stats-summary-row")
      row.append(element("dt", null, label), element("dd", null, value))
      list.append(row)
    })
    return list
  }

  statsTable(stats, series) {
    const columns = stats.percent
      ? [["Mean", (entry) => entry.mean], ["Min", (entry) => this.pickButton(entry.min)], ["Max", (entry) => this.pickButton(entry.max)]]
      : [["Total", (entry) => entry.total], ["Mean", (entry) => entry.mean], ["Max", (entry) => this.pickButton(entry.max)]]
    const table = element("table", "explorer-stats-table")
    const head = element("tr")
    const corner = element("th")
    corner.scope = "col"
    corner.append(element("span", "visually-hidden", "Series"))
    head.append(corner, ...columns.map(([name]) => Object.assign(element("th", null, name), { scope: "col" })))
    const body = element("tbody")
    series.forEach((entry) => {
      const row = element("tr")
      const name = Object.assign(element("th"), { scope: "row" })
      name.append(this.seriesLabel(entry))
      row.append(name, ...columns.map(([, cell]) => {
        const td = element("td")
        const content = cell(entry)
        td.append(typeof content === "string" ? document.createTextNode(content) : content)
        return td
      }))
      body.append(row)
    })
    const thead = element("thead")
    thead.append(head)
    table.append(thead, body)
    return table
  }

  changeList(series) {
    const list = element("div", "explorer-stats-change")
    list.append(element("p", "explorer-stats-caption", "Change from previous period"))
    series.forEach((entry) => {
      const row = element("div", "explorer-stats-change-row")
      row.append(this.seriesLabel(entry),
        entry.change ? this.deltaView(entry.change, "from the previous period") : element("span", "explorer-stats-na", "n/a"))
      list.append(row)
    })
    return list
  }

  seriesLabel(entry) {
    const label = element("span", "explorer-stats-series")
    const key = element("i", `explorer-legend-key is-${entry.shape} ${entry.colorClass}`)
    if (entry.color) key.style.color = entry.color
    label.append(key, element("span", "explorer-stats-name", entry.label))
    return label
  }

  pickButton(point) {
    const button = element("button", "explorer-stats-pick", point.value)
    button.type = "button"
    button.dataset.action = "explorer#pinRow"
    button.dataset.explorerIndexParam = String(point.index)
    return button
  }

  renderInspector() {
    const open = !!this.inspectorOpen && !!this.chart
    this.inspectorTarget.hidden = !open
    this.inspectorButtonTarget.setAttribute("aria-pressed", String(!!this.inspectorOpen))
    if (!open) return

    const index = this.pin ?? this.hoverIndex
    const details = index == null ? null : this.chart.pointDetails(index)
    const pinned = this.pin != null
    this.pinButtonTarget.hidden = !details
    this.pinButtonTarget.setAttribute("aria-pressed", String(pinned))
    this.pinLabelTarget.textContent = pinned ? "Pinned" : "Pin"
    this.pointTarget.replaceChildren(details ? this.pointView(details) : element("p", "explorer-point-empty",
      `No ${(this.labels?.point || INSPECTOR_LABELS.point).toLowerCase()} selected`))
  }

  pointView(details) {
    const fragment = document.createDocumentFragment()
    const title = element("p", "explorer-point-title")
    title.append(element("span", null, details.title))
    if (details.qualifier) title.append(element("span", "explorer-point-day", details.qualifier))
    fragment.append(title)
    if (details.tags.length) {
      const tags = element("div", "explorer-point-tags")
      details.tags.forEach((tag) => tags.append(element("span", "explorer-point-tag", tag)))
      fragment.append(tags)
    }

    const rows = element("div", "explorer-point-rows")
    details.values.forEach((value) => rows.append(this.pointRow(value)))
    if (details.total) {
      const total = element("div", "explorer-point-row is-total")
      total.append(element("i"), element("span", "explorer-point-label", "total"),
        element("b", "explorer-point-value", details.total))
      rows.append(total)
    }
    fragment.append(rows)
    if (details.note) fragment.append(element("p", "explorer-point-note", details.note))
    return fragment
  }

  pointRow(value) {
    const row = element("div", "explorer-point-row")
    const key = element("i", `explorer-legend-key is-${value.shape} ${value.colorClass}`)
    if (value.color) key.style.color = value.color
    row.append(key, element("span", "explorer-point-label", value.label), element("b", "explorer-point-value", value.value))

    const meta = element("div", "explorer-point-meta")
    if (value.change) meta.append(this.deltaView(value.change, value.comparison || "from the previous point"))
    if (value.share) meta.append(element("span", "explorer-point-share", `${value.share} of total`))
    if (meta.childElementCount) row.append(meta)
    return row
  }

  deltaView({ value, unit }, comparison) {
    const direction = Math.abs(value) < 0.05 ? "flat" : value > 0 ? "up" : "down"
    const delta = element("span", `delta delta-${direction}`)
    delta.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ` +
      `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${DELTA_PATHS[direction]}"/></svg>`
    delta.append(element("span", "visually-hidden", DELTA_WORDS[direction]),
      document.createTextNode(`${Math.abs(value).toFixed(1)}${unit === "pts" ? " pts" : "%"}`),
      element("span", "visually-hidden", ` ${comparison}`))
    return delta
  }

  moveWindow(window, { animate = false } = {}) {
    if (animate) {
      this.animateWindow(window)
      return
    }
    cancelAnimationFrame(this.zoomFrame)
    this.applyWindow(window)
  }

  renderOverview() {
    const shown = this.canZoom && typeof this.chart.overviewSeries === "function" &&
      this.display.overview !== false && this.isOpen &&
      this.viewMode !== "table"
    this.overviewTarget.hidden = !shown
    if (!shown) return

    const bounds = this.chart.plotBounds()
    if (!bounds) return

    this.overview.render({
      count: this.chart.rowCount(), window: this.zoomWindow, bounds, series: this.chart.overviewSeries()
    })
  }

  zoomIn() {
    this.zoomBy(ZOOM_STEP)
  }

  zoomOut() {
    this.zoomBy(1 / ZOOM_STEP)
  }

  resetZoom() {
    if (this.zoomWindow) this.animateWindow(null)
  }

  zoomBy(factor) {
    if (!this.canZoom) return

    this.animateWindow(this.chart.zoomWindowAt(this.currentWindow(), factor))
  }

  animateWindow(target) {
    const from = this.currentWindow()
    const to = target || this.chart.fullWindow()
    cancelAnimationFrame(this.zoomFrame)
    if (this.reducedMotion.matches) {
      this.applyWindow(to)
      return
    }

    const startedAt = performance.now()
    const tick = (now) => {
      const progress = Math.min(1, (now - startedAt) / ZOOM_DURATION)
      const eased = 1 - (1 - progress) ** 3
      this.applyWindow(progress < 1 ? this.chart.interpolateWindow(from, to, eased) : to)
      if (progress < 1) this.zoomFrame = requestAnimationFrame(tick)
    }
    this.zoomFrame = requestAnimationFrame(tick)
  }

  applyWindow(window) {
    if (!this.chart) return

    this.zoomWindow = this.chart.isFullWindow(window) ? null : window
    this.writeView()
    this.renderZoom()
    this.renderTool()
    this.renderOverview()
    this.renderRange()
    this.scheduleRangeViews()
    this.scheduleUrl()
  }

  renderRange() {
    const summary = this.zoomWindow && this.chart ? this.chart.windowLabel(this.zoomWindow) : null
    this.rangeTarget.hidden = !summary
    if (!summary) return

    this.rangeLabelTarget.textContent = summary.label
    this.rangeCountTarget.textContent = summary.detail || ""
  }

  renderZoom() {
    const zoomable = this.canZoom
    this.zoomControlsTarget.hidden = !zoomable
    if (!zoomable) return

    this.zoomInButtonTarget.disabled = !this.chart.canZoomIn(this.currentWindow())
    this.zoomOutButtonTarget.disabled = !this.zoomWindow
    this.zoomResetButtonTarget.disabled = !this.zoomWindow
  }

  renderLegend() {
    const scale = this.chart?.legendScale?.()
    if (scale) {
      this.legendTarget.hidden = false
      this.legendTarget.replaceChildren(...this.legendScaleView(scale))
      return
    }

    const entries = this.legendEntries()
    const focused = this.legendTarget.contains(document.activeElement) ? document.activeElement.dataset.series : null
    this.legendTarget.hidden = entries.length < 2
    this.legendTarget.replaceChildren(...(entries.length < 2 ? [] : entries.map((entry) => this.legendItem(entry))))
    if (focused) this.legendTarget.querySelector(`[data-series="${focused}"]`)?.focus({ preventScroll: true })
  }

  legendScaleView({ low, high, steps, extras = [], note }) {
    const ramp = element("span", "explorer-legend-scale")
    ramp.append(element("span", null, low))
    steps.forEach((color) => {
      const swatch = element("i", "explorer-legend-key is-box")
      swatch.style.color = color
      ramp.append(swatch)
    })
    ramp.append(element("span", null, high))
    const nodes = [ramp]
    extras.forEach((extra) => {
      const item = element("span", "explorer-legend-scale")
      const swatch = element("i", "explorer-legend-key is-box is-outlined")
      swatch.style.color = extra.color
      item.append(swatch, element("span", null, extra.label))
      nodes.push(item)
    })
    if (note) nodes.push(element("span", "explorer-legend-note", note))
    return nodes
  }

  legendItem(entry) {
    const item = document.createElement("button")
    item.type = "button"
    item.className = "explorer-legend-item"
    item.dataset.series = entry.key
    item.dataset.action = "explorer#toggleSeries mouseenter->explorer#highlightSeries " +
      "mouseleave->explorer#clearHighlight focus->explorer#highlightSeries blur->explorer#clearHighlight"
    item.setAttribute("aria-pressed", String(!this.hiddenSeries.has(entry.key)))
    const key = document.createElement("i")
    key.className = `explorer-legend-key is-${entry.shape} ${entry.colorClass}`
    if (entry.color) key.style.color = entry.color
    const label = document.createElement("span")
    label.textContent = entry.label
    item.append(key, label)
    return item
  }

  toggleSeries(event) {
    const key = event.currentTarget.dataset.series
    const keys = this.legendEntries().map((entry) => entry.key)
    if (event.altKey || event.metaKey) {
      const isolated = keys.every((other) => (other === key) !== this.hiddenSeries.has(other))
      this.hiddenSeries = new Set(isolated ? [] : keys.filter((other) => other !== key))
    } else if (this.hiddenSeries.has(key)) {
      this.hiddenSeries.delete(key)
    } else {
      this.hiddenSeries.add(key)
    }
    this.clearHighlight()
    this.writeView()
    this.renderLegend()
  }

  highlightSeries(event) {
    const key = event.currentTarget.dataset.series
    if (!this.chartMount || this.hiddenSeries.has(key)) return

    this.chartMount.dataset.highlight = key
  }

  clearHighlight() {
    if (this.chartMount) delete this.chartMount.dataset.highlight
  }

  toggleDisplay() {
    if (this.displayTarget.hidden) this.openDisplay()
    else this.closeDisplay({ restoreFocus: true })
  }

  openDisplay() {
    if (!this.chart) return

    this.renderDisplay()
    this.displayTarget.hidden = false
    this.displayButtonTarget.setAttribute("aria-expanded", "true")
    this.displayTarget.focus({ preventScroll: true })
  }

  closeDisplay({ restoreFocus = false } = {}) {
    if (this.displayTarget.hidden) return

    const hadFocus = this.displayTarget.contains(document.activeElement)
    this.displayTarget.hidden = true
    this.displayButtonTarget.setAttribute("aria-expanded", "false")
    if (restoreFocus || hadFocus) this.displayButtonTarget.focus({ preventScroll: true })
  }

  chooseSetting({ params: { setting, choice } }) {
    this.setDisplay(setting, choice)
  }

  toggleSetting({ params: { setting } }) {
    this.setDisplay(setting, !this.display[setting])
  }

  toggleSettingIfShown(setting) {
    if (this.displayOptions()[setting]) this.setDisplay(setting, !this.display[setting])
  }

  resetDisplay() {
    this.displayOverrides = {}
    this.savePreferences()
    this.writeView()
    this.renderDisplay()
  }

  setDisplay(key, value) {
    if (!this.chart || !DISPLAY_KEYS.includes(key)) return

    if (value === this.displayDefaults()[key]) delete this.displayOverrides[key]
    else this.displayOverrides[key] = value
    if (key === "xScale") this.zoomWindow = null
    this.savePreferences()
    this.writeView()
    this.renderDisplay()
  }

  renderDisplay() {
    if (!this.chart) return

    const options = this.displayOptions()
    const display = this.display
    const line = display.kind === "line"
    const shown = (key) => options[key] && !(key === "zero" && !line) && !(key === "stacked" && line)
    const effective = (key) => (key === "yScale" && !line ? "linear" : display[key])
    this.displayTarget.querySelectorAll("[data-setting]").forEach((row) => {
      const key = row.dataset.setting
      row.hidden = !shown(key)
      row.querySelectorAll("[data-explorer-choice-param]").forEach((button) => {
        const choice = button.dataset.explorerChoiceParam
        button.setAttribute("aria-pressed", String(effective(key) === choice))
        button.disabled = key === "yScale" && choice === "log" && !line
      })
      row.querySelector("[role='switch']")?.setAttribute("aria-checked", String(!!display[key]))
    })
    this.displayTarget.querySelectorAll("[data-settings-group]").forEach((group) => {
      group.hidden = !group.querySelector("[data-setting]:not([hidden])")
    })
  }

  get storageKey() {
    return this.key ? `${STORAGE_PREFIX}${this.key}` : null
  }

  readPreferences() {
    if (!this.storageKey) return {}

    try {
      return JSON.parse(localStorage.getItem(this.storageKey) || "{}") || {}
    } catch {
      return {}
    }
  }

  loadDisplay() {
    const saved = this.readPreferences().display || {}
    return Object.fromEntries(Object.entries(saved).filter(([key]) => DISPLAY_KEYS.includes(key)))
  }

  savePreferences() {
    if (!this.storageKey) return

    try {
      localStorage.setItem(this.storageKey,
        JSON.stringify({
          display: this.displayOverrides, inspector: !!this.inspectorOpen, view: this.viewMode, split: this.split
        }))
    } catch {
      return
    }
  }

  emptyState() {
    const empty = document.createElement("div")
    empty.className = "empty"
    empty.innerHTML = '<p class="empty-title">No data</p>'
    return empty
  }

  fillHeader(card, trigger) {
    const title = trigger?.dataset.exploreTitle || card.querySelector(".card-title, .fold-title")?.textContent.trim() || ""
    const subtitle = card.querySelector(".card-sub")?.textContent.trim() || ""
    this.titleTarget.textContent = title
    this.subtitleTarget.textContent = subtitle
    this.subtitleTarget.hidden = !subtitle
  }

  animateOpen() {
    const clip = this.cardClip()
    if (!clip) {
      this.panelTarget.animate(
        [{ opacity: 0, transform: "scale(0.985)" }, { opacity: 1, transform: "none" }],
        { duration: this.duration(FADE_DURATION), easing: "ease-out" })
      return
    }

    this.panelTarget.animate([{ clipPath: clip }, { clipPath: this.fullClip() }],
      { duration: OPEN_DURATION, easing: OPEN_EASING })
    this.bodyTarget.animate([{ opacity: 0.35 }, { opacity: 1 }],
      { duration: OPEN_DURATION - 60, easing: "ease-out" })
  }

  cardClip() {
    if (this.reducedMotion.matches || !this.card?.isConnected) return null

    const card = this.card.getBoundingClientRect()
    const panel = this.panelTarget.getBoundingClientRect()
    if (!card.width || card.bottom < 0 || card.top > window.innerHeight) return null

    const top = Math.max(0, card.top - panel.top)
    const right = Math.max(0, panel.right - card.right)
    const bottom = Math.max(0, panel.bottom - card.bottom)
    const left = Math.max(0, card.left - panel.left)
    return `inset(${top}px ${right}px ${bottom}px ${left}px round ${this.cardRadius()})`
  }

  fullClip() {
    return `inset(0px 0px 0px 0px round ${this.panelRadius()})`
  }

  cardRadius() {
    return getComputedStyle(this.card).borderTopLeftRadius || "0px"
  }

  panelRadius() {
    return getComputedStyle(this.dialog.parentElement).borderTopLeftRadius || "0px"
  }

  duration(ms) {
    return this.reducedMotion.matches ? 1 : ms
  }
}
