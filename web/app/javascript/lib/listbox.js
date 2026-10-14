import { placePop, clearPop } from "lib/place_pop"

const CACHET = "https://cachet.hackclub.com"
const SVG = "http://www.w3.org/2000/svg"
let idCounter = 0

export function searchUrl(path, term) {
  const url = new URL(path, window.location.origin)
  url.searchParams.set("q", term)
  return url
}

export function span(className, text) {
  const el = document.createElement("span")
  el.className = className
  el.textContent = text
  return el
}

export function avatarImage(id, initial) {
  const img = document.createElement("img")
  img.className = "avatar"
  img.src = `${CACHET}/users/${encodeURIComponent(id)}/r`
  img.alt = ""
  img.dataset.cachetFace = id
  img.dataset.cachetInitial = initial || "?"
  return img
}

export function nameLabel(id, name) {
  const el = span("combo-name", name)
  if (name === `@${id}`) el.dataset.cachetName = id
  return el
}

const CHANNEL_ICON = "M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"
const TAG_ICON = "M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"
const PLUS_ICON = "M5 12h14M12 5v14"

function icon(path) {
  const svg = document.createElementNS(SVG, "svg")
  svg.setAttribute("viewBox", "0 0 24 24")
  svg.setAttribute("fill", "none")
  svg.setAttribute("stroke", "currentColor")
  svg.setAttribute("stroke-width", "2")
  svg.setAttribute("stroke-linecap", "round")
  svg.setAttribute("aria-hidden", "true")
  svg.setAttribute("class", "combo-icon")
  const shape = document.createElementNS(SVG, "path")
  shape.setAttribute("d", path)
  svg.append(shape)
  return svg
}

function option(id) {
  const row = document.createElement("div")
  row.className = "combo-opt"
  row.id = `combo-opt-${++idCounter}`
  row.setAttribute("role", "option")
  row.setAttribute("aria-selected", "false")
  row.dataset.id = id
  return row
}

export function personOption(member) {
  const row = option(member.id)
  row.dataset.name = member.name
  row.dataset.initial = member.initial || ""

  const plainName = member.name.replace(/^@/, "")
  row.append(avatarImage(member.id, member.initial), nameLabel(member.id, member.name))
  if (member.handle && member.handle !== plainName) row.append(span("combo-sub", `@${member.handle}`))
  if (member.deleted) row.append(span("combo-end", "Deactivated"))
  return row
}

export function channelOption(channel) {
  const row = option(channel.id)
  row.dataset.name = channel.name
  row.append(icon(CHANNEL_ICON), span("combo-name", channel.name), span("combo-end mono", channel.id))
  return row
}

export function tagOption(tag) {
  const row = option(tag.id)
  row.dataset.name = tag.name
  row.append(icon(tag.create ? PLUS_ICON : TAG_ICON), span("combo-name", tag.name))
  if (!tag.create) row.append(span("combo-end", `${tag.uses} ${tag.uses === 1 ? "case" : "cases"}`))
  return row
}

const OPTIONS = { member: personOption, channel: channelOption, tag: tagOption }

export class Listbox {
  constructor({ pop, list, anchor, kind, empty, input, onSelect }) {
    this.pop = pop
    this.list = list || pop
    this.anchor = anchor
    this.input = input
    this.build = OPTIONS[kind] || personOption
    this.empty = empty || "No results"
    this.onSelect = onSelect
    this.at = -1
    this.onMove = () => { if (this.open) this.position() }
    this.list.setAttribute("role", "listbox")
    this.list.id ||= `combo-list-${++idCounter}`
    this.input?.setAttribute("aria-controls", this.list.id)
    this.list.addEventListener("pointerdown", (event) => event.preventDefault())
    this.list.addEventListener("click", (event) => this.onClick(event))
    this.list.addEventListener("pointermove", (event) => this.onPointerMove(event))
  }

  get open() {
    return this.pop.matches(":popover-open")
  }

  rows() {
    return [...this.list.querySelectorAll(".combo-opt")]
  }

  show(items) {
    this.list.replaceChildren()
    if (items.length === 0) {
      this.list.append(span("combo-none", this.empty))
    } else {
      for (const item of items) this.list.append(this.build(item))
    }
    this.at = items.length > 0 ? 0 : -1
    this.mark()
    this.reveal()
  }

  reveal() {
    if (!this.open) this.pop.showPopover()
    this.input?.setAttribute("aria-expanded", "true")
    this.anchor.setAttribute("aria-expanded", "true")
    this.position()
    window.addEventListener("resize", this.onMove)
    document.addEventListener("scroll", this.onMove, true)
  }

  hide() {
    if (this.open) this.pop.hidePopover()
    this.input?.setAttribute("aria-expanded", "false")
    this.anchor.setAttribute("aria-expanded", "false")
    this.input?.removeAttribute("aria-activedescendant")
    this.at = -1
    clearPop(this.pop)
    window.removeEventListener("resize", this.onMove)
    document.removeEventListener("scroll", this.onMove, true)
  }

  position() {
    if (this.pop.classList.contains("combo-pop-fit")) {
      this.pop.style.width = `${this.anchor.getBoundingClientRect().width}px`
    }
    placePop(this.pop, this.anchor)
  }

  mark() {
    this.rows().forEach((row, index) => {
      const isActive = index === this.at
      row.setAttribute("aria-selected", isActive ? "true" : "false")
      if (isActive) {
        row.scrollIntoView({ block: "nearest" })
        this.input?.setAttribute("aria-activedescendant", row.id)
      }
    })
    if (this.at < 0) this.input?.removeAttribute("aria-activedescendant")
  }

  move(step) {
    const optionRows = this.rows()
    if (optionRows.length === 0) return

    this.at = this.at < 0
      ? (step > 0 ? 0 : optionRows.length - 1)
      : (this.at + step + optionRows.length) % optionRows.length
    this.mark()
  }

  current() {
    return this.rows()[this.at] || null
  }

  onPointerMove(event) {
    const row = event.target.closest(".combo-opt")
    const index = this.rows().indexOf(row)
    if (index < 0 || index === this.at) return

    this.at = index
    this.mark()
  }

  onClick(event) {
    const row = event.target.closest(".combo-opt")
    if (row) this.onSelect(row.dataset)
  }

  keys(event, { tab = false } = {}) {
    if (!this.open) return false

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      this.move(event.key === "ArrowDown" ? 1 : -1)
      return true
    }

    if (event.key === "Home" || event.key === "End") {
      const optionRows = this.rows()
      if (optionRows.length === 0) return false
      event.preventDefault()
      this.at = event.key === "Home" ? 0 : optionRows.length - 1
      this.mark()
      return true
    }

    if (event.key === "Escape") {
      event.preventDefault()
      event.stopPropagation()
      this.hide()
      return true
    }

    if (event.key === "Enter" || (tab && event.key === "Tab")) {
      const row = this.current()
      if (!row) return false
      event.preventDefault()
      this.onSelect(row.dataset)
      return true
    }

    return false
  }
}
