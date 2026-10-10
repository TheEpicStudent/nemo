import { Controller } from "@hotwired/stimulus"
import { modalsOpen, aboveOpen, popupOpen, drawerOpen } from "lib/layers"
import { zoomWindow, isFullWindow, interpolateWindow, minimumSpan } from "charts/frame"

const OPEN_DURATION = 340
const CLOSE_DURATION = 220
const FADE_DURATION = 160
const ZOOM_DURATION = 260
const ZOOM_STEP = 0.6
const OPEN_EASING = "cubic-bezier(0.16, 1, 0.3, 1)"
const CLOSE_EASING = "cubic-bezier(0.4, 0, 0.2, 1)"
const EDITABLE = "input, textarea, select, [contenteditable]:not([contenteditable='false'])"
const CHART_SOURCE = "[data-controller~='chart']:not([data-chart-spark-value='true'])"
const DETACHED_VALUES = ["brush", "brush-href", "brush-keys"]
const DISPLAY_KEYS = ["kind", "stacked", "yScale", "zero", "fit", "format", "grid", "notes"]
const STORAGE_PREFIX = "mn-explore-"

export default class extends Controller {
  static targets = [
    "dialog", "panel", "title", "subtitle", "body", "legend", "plot", "displayButton", "display",
    "zoomControls", "zoomInButton", "zoomOutButton", "zoomResetButton"
  ]

  connect() {
    this.dialog = this.dialogTarget
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)")
    this.onClick = this.onClick.bind(this)
    this.onKeydown = this.onKeydown.bind(this)
    this.onPointerdown = this.onPointerdown.bind(this)
    this.element.addEventListener("click", this.onClick)
    document.addEventListener("keydown", this.onKeydown)
    this.dialog.addEventListener("pointerdown", this.onPointerdown)
  }

  disconnect() {
    this.element.removeEventListener("click", this.onClick)
    document.removeEventListener("keydown", this.onKeydown)
    this.dialog.removeEventListener("pointerdown", this.onPointerdown)
    this.hide()
    this.reset()
  }

  get isOpen() {
    return !this.dialog.hidden
  }

  open(card, trigger = null) {
    if (!card || this.isOpen) return

    this.card = card
    this.key = trigger?.dataset.explore || null
    this.opener = trigger || document.activeElement
    this.fillHeader(card, trigger)
    this.dialog.hidden = false
    this.coverPage()
    this.mountChart(card)
    this.animateOpen()
    this.panelTarget.focus({ preventScroll: true })
  }

  close() {
    if (!this.isOpen || this.closing) return

    this.closing = true
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
    this.close()
  }

  finishClose() {
    if (!this.isOpen) return

    const opener = this.opener
    this.hide()
    this.reset()
    if (opener?.isConnected && typeof opener.focus === "function") opener.focus({ preventScroll: true })
  }

  onClick(event) {
    const trigger = event.target.closest("[data-explore]")
    if (!trigger || this.dialog.contains(trigger)) return

    event.preventDefault()
    this.open(trigger.closest(".card"), trigger)
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
    if (event.key === "Escape") {
      event.preventDefault()
      this.dismiss()
      return
    }

    const shortcut = this.shortcutFor(event)
    if (!shortcut) return

    event.preventDefault()
    shortcut()
  }

  shortcutFor(event) {
    if (event.metaKey || event.ctrlKey || event.altKey || event.target.closest?.(EDITABLE)) return null

    switch (event.key.toLowerCase()) {
      case "+": case "=": return () => this.zoomIn()
      case "-": case "_": return () => this.zoomOut()
      case "0": return () => this.resetZoom()
      case "d": return () => this.toggleDisplay()
      case "g": return () => this.toggleSettingIfShown("grid")
      case "a": return () => this.toggleSettingIfShown("notes")
      default: return null
    }
  }

  isExpandShortcut(event) {
    if (event.key !== "v" && event.key !== "V") return false
    if (event.metaKey || event.ctrlKey || event.altKey) return false
    return !event.target.closest?.(EDITABLE)
  }

  openFocusedCard(event) {
    if (this.layerAbove()) return

    const trigger = this.element.querySelector(".card:hover [data-explore]") ||
      document.activeElement?.closest?.(".card")?.querySelector("[data-explore]")
    if (!trigger) return

    event.preventDefault()
    this.open(trigger.closest(".card"), trigger)
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
    this.chartMount = null
    this.hiddenSeries = new Set()
    this.displayOverrides = {}
    cancelAnimationFrame(this.zoomFrame)
    this.zoomWindow = null
    this.zoomControlsTarget.hidden = true
    this.card = null
    this.key = null
    this.opener = null
  }

  mountChart(card) {
    const source = card.querySelector(CHART_SOURCE)
    if (!source) {
      const empty = card.querySelector(".empty")
      this.plotTarget.replaceChildren(empty ? empty.cloneNode(true) : this.emptyState())
      return
    }

    const mount = source.cloneNode(false)
    mount.removeAttribute("id")
    DETACHED_VALUES.forEach((name) => mount.removeAttribute(`data-chart-${name}-value`))
    this.chartMount = mount
    this.hiddenSeries = new Set()
    this.displayOverrides = this.loadDisplay()
    this.writeView()
    this.plotTarget.replaceChildren(mount)
  }

  get view() {
    return {
      fill: true, title: this.titleTarget.textContent, legend: false, hidden: [...this.hiddenSeries],
      ...this.displayOverrides, ...(this.zoomWindow ? { window: this.zoomWindow } : {})
    }
  }

  get display() {
    return { ...this.chart?.displayDefaults(), ...this.displayOverrides }
  }

  writeView() {
    this.chartMount?.setAttribute("data-chart-view-value", JSON.stringify(this.view))
  }

  chartReady(event) {
    this.chart = this.application.getControllerForElementAndIdentifier(event.target, "chart")
    this.renderLegend()
    this.renderDisplay()
    this.renderZoom()
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
    if (!this.chart?.zoomable()) return

    const count = this.chart.rowCount()
    this.animateWindow(zoomWindow(this.zoomWindow || [0, count], count, factor))
  }

  animateWindow(target) {
    const count = this.chart.rowCount()
    const from = this.zoomWindow || [0, count]
    const to = target || [0, count]
    cancelAnimationFrame(this.zoomFrame)
    if (this.reducedMotion.matches) {
      this.applyWindow(to)
      return
    }

    const startedAt = performance.now()
    const tick = (now) => {
      const progress = Math.min(1, (now - startedAt) / ZOOM_DURATION)
      const eased = 1 - (1 - progress) ** 3
      this.applyWindow(progress < 1 ? interpolateWindow(from, to, eased) : to)
      if (progress < 1) this.zoomFrame = requestAnimationFrame(tick)
    }
    this.zoomFrame = requestAnimationFrame(tick)
  }

  applyWindow(window) {
    if (!this.chart) return

    this.zoomWindow = isFullWindow(window, this.chart.rowCount()) ? null : window
    this.writeView()
    this.renderZoom()
  }

  renderZoom() {
    const zoomable = !!this.chart?.zoomable()
    this.zoomControlsTarget.hidden = !zoomable
    if (!zoomable) return

    const count = this.chart.rowCount()
    const [start, end] = this.zoomWindow || [0, count]
    this.zoomInButtonTarget.disabled = end - start <= minimumSpan(count) + 0.001
    this.zoomOutButtonTarget.disabled = !this.zoomWindow
    this.zoomResetButtonTarget.disabled = !this.zoomWindow
  }

  renderLegend() {
    const entries = this.chart?.legendEntries() || []
    const focused = this.legendTarget.contains(document.activeElement) ? document.activeElement.dataset.series : null
    this.legendTarget.hidden = entries.length < 2
    this.legendTarget.replaceChildren(...(entries.length < 2 ? [] : entries.map((entry) => this.legendItem(entry))))
    if (focused) this.legendTarget.querySelector(`[data-series="${focused}"]`)?.focus({ preventScroll: true })
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
    const keys = this.chart.legendEntries().map((entry) => entry.key)
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
    if (this.chart?.displayOptions()[setting]) this.setDisplay(setting, !this.display[setting])
  }

  resetDisplay() {
    this.displayOverrides = {}
    this.saveDisplay()
    this.writeView()
    this.renderDisplay()
  }

  setDisplay(key, value) {
    if (!this.chart || !DISPLAY_KEYS.includes(key)) return

    if (value === this.chart.displayDefaults()[key]) delete this.displayOverrides[key]
    else this.displayOverrides[key] = value
    this.saveDisplay()
    this.writeView()
    this.renderDisplay()
  }

  renderDisplay() {
    if (!this.chart) return

    const options = this.chart.displayOptions()
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

  loadDisplay() {
    if (!this.storageKey) return {}

    try {
      const saved = JSON.parse(localStorage.getItem(this.storageKey) || "{}").display || {}
      return Object.fromEntries(Object.entries(saved).filter(([key]) => DISPLAY_KEYS.includes(key)))
    } catch {
      return {}
    }
  }

  saveDisplay() {
    if (!this.storageKey) return

    try {
      localStorage.setItem(this.storageKey, JSON.stringify({ display: this.displayOverrides }))
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
    const title = trigger?.dataset.exploreTitle || card.querySelector(".card-title")?.textContent.trim() || ""
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
