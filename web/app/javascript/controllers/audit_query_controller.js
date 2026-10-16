import { Controller } from "@hotwired/stimulus"

const MAX_OPTIONS = 8
const LOOKUP_DELAY_MS = 150
const MEMBER_MIN_LENGTH = 3
const MEMBER_KEYS = ["about", "actor", "by", "who", "to", "subject"]
const CHANNEL_KEYS = ["in", "channel"]
let refocus = false

export default class extends Controller {
  static targets = ["input", "list", "remove"]
  static values = { keys: Array, choices: Object, people: Array, memberUrl: String, channelUrl: String }

  connect() {
    this.options = []
    this.selected = -1
    this.request = 0
    if (refocus) {
      refocus = false
      this.inputTarget.focus()
    }
  }

  disconnect() {
    clearTimeout(this.timer)
  }

  focus(event) {
    if (event.target.closest("a, button, input")) return
    this.inputTarget.focus()
  }

  suggest() {
    clearTimeout(this.timer)
    const draft = this.inputTarget.value.trim()
    const pair = /^(\w+):(.*)$/.exec(draft)
    if (pair && this.remote(pair[1])) {
      this.timer = setTimeout(() => this.lookup(pair[1], pair[2]), LOOKUP_DELAY_MS)
      return
    }

    this.show(this.matches(draft, pair), -1)
  }

  remote(key) {
    const kind = key.toLowerCase()
    return MEMBER_KEYS.includes(kind) || CHANNEL_KEYS.includes(kind)
  }

  async lookup(key, part) {
    const request = ++this.request
    const options = CHANNEL_KEYS.includes(key.toLowerCase()) ? await this.channels(key, part) : await this.members(key, part)
    if (request !== this.request) return

    this.show(options, options.length > 0 ? 0 : -1)
  }

  show(options, selected) {
    this.options = options
    this.selected = selected
    this.render()
  }

  matches(draft, pair) {
    if (!draft) return []

    if (!pair) {
      const keys = this.keysValue
        .filter(([key]) => key.startsWith(draft.toLowerCase()))
        .map(([key, description]) => ({ label: `${key}:`, description, fill: `${key}:` }))
      const text = draft.includes(" ") ? `"${draft}"` : draft
      return [...keys, { label: `"${draft}"`, description: "Full text", term: text }].slice(0, MAX_OPTIONS)
    }

    const [, key, part] = pair
    const query = part.toLowerCase()
    return this.optionsFor(key, this.choicesValue[key.toLowerCase()] || [], query)
  }

  optionsFor(key, values, query) {
    return values
      .filter(([value, label]) => value.toLowerCase().includes(query) || (label || "").toLowerCase().includes(query))
      .slice(0, MAX_OPTIONS)
      .map(([value, label]) => ({ label: `${key}:${value}`, description: label || "", term: `${key}:${value}` }))
  }

  async members(key, part) {
    const query = part.replace(/^@/, "")
    const selfOptions = key.toLowerCase() === "by" && "me".startsWith(query.toLowerCase())
      ? [{ label: `${key}:me`, description: "You", term: `${key}:me` }]
      : []
    if (query.length < MEMBER_MIN_LENGTH) {
      return [...selfOptions, ...this.optionsFor(key, this.peopleValue, query.toLowerCase())].slice(0, MAX_OPTIONS)
    }

    const payload = await this.fetchJson(this.memberUrlValue, query)
    const members = (payload?.members || []).map((member) => {
      const value = member.handle ? `@${member.handle}` : member.id
      return { label: `${key}:${value}`, description: member.name || "", term: `${key}:${value}` }
    })
    return [...selfOptions, ...members].slice(0, MAX_OPTIONS)
  }

  async channels(key, part) {
    const payload = await this.fetchJson(this.channelUrlValue, part.replace(/^#/, ""))
    return (payload?.channels || []).slice(0, MAX_OPTIONS).map((channel) => (
      { label: `${key}:#${channel.name}`, description: channel.id, term: `${key}:#${channel.name}` }
    ))
  }

  async fetchJson(url, query) {
    try {
      const response = await fetch(`${url}?q=${encodeURIComponent(query)}`, { headers: { Accept: "application/json" } })
      return response.ok ? await response.json() : null
    } catch {
      return null
    }
  }

  render() {
    this.listTarget.replaceChildren(...this.options.map((option, index) => this.optionElement(option, index)))
    this.listTarget.hidden = this.options.length === 0
  }

  optionElement(option, index) {
    const button = document.createElement("button")
    button.type = "button"
    button.setAttribute("role", "option")
    button.setAttribute("aria-selected", index === this.selected ? "true" : "false")
    button.dataset.index = index
    button.dataset.action = "mousedown->audit-query#choose"

    const label = document.createElement("span")
    label.className = "audit-suggest-label"
    label.textContent = option.label
    const description = document.createElement("span")
    description.className = "audit-suggest-description"
    description.textContent = option.description
    button.append(label, description)
    return button
  }

  key(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (this.options.length === 0) return
      event.preventDefault()
      const step = event.key === "ArrowDown" ? 1 : -1
      this.selected = (this.selected + step + this.options.length) % this.options.length
      this.render()
      return
    }
    if (event.key === "Enter") {
      if (this.selected >= 0) {
        event.preventDefault()
        this.apply(this.options[this.selected])
      } else {
        refocus = true
      }
      return
    }
    if (event.key === "Escape") return this.close()
    if (event.key === "Backspace" && this.inputTarget.value === "" && this.hasRemoveTarget) {
      event.preventDefault()
      refocus = true
      window.Turbo.visit(this.removeTargets[this.removeTargets.length - 1].href)
    }
  }

  choose(event) {
    event.preventDefault()
    this.apply(this.options[Number(event.currentTarget.dataset.index)])
  }

  apply(option) {
    if (!option) return

    if (option.fill) {
      this.inputTarget.value = option.fill
      this.inputTarget.focus()
      this.suggest()
      return
    }

    this.inputTarget.value = option.term
    refocus = true
    this.element.requestSubmit()
  }

  close() {
    clearTimeout(this.timer)
    this.request++
    this.show([], -1)
  }
}
