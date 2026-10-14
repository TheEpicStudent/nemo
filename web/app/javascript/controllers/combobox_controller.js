import { Controller } from "@hotwired/stimulus"
import { Listbox, searchUrl, avatarImage, span } from "lib/listbox"

const SLACK_ID = /^[UW][A-Z0-9]{2,}$/

export default class extends Controller {
  static targets = ["field", "trigger", "input", "pop", "list", "store"]
  static values = {
    url: String,
    kind: { type: String, default: "member" },
    name: String,
    single: Boolean,
    submit: Boolean,
    preset: Array,
    least: Number,
    empty: String
  }

  connect() {
    this.selected = new Map()
    for (const { id, name, initial } of this.presetValue) this.selected.set(id, { name, initial })
    this.blank = this.inputTarget.placeholder
    this.box = new Listbox({
      pop: this.popTarget,
      list: this.listTarget,
      anchor: this.hasFieldTarget ? this.fieldTarget : this.triggerTarget,
      input: this.inputTarget,
      kind: this.kindValue,
      empty: this.emptyValue,
      onSelect: (item) => this.selectItem(item)
    })
    this.onOutsidePointer = (event) => {
      if (!this.element.contains(event.target)) this.close()
    }
    document.addEventListener("pointerdown", this.onOutsidePointer)
    this.render()
  }

  disconnect() {
    clearTimeout(this.timer)
    this.abortController?.abort()
    document.removeEventListener("pointerdown", this.onOutsidePointer)
    this.box.hide()
  }

  get inline() {
    return this.hasFieldTarget
  }

  focus(event) {
    if (event.target === this.fieldTarget) this.inputTarget.focus()
  }

  openOnFocus() {
    if (!this.suppressWake && this.leastValue === 0 && !this.box.open) this.search()
  }

  toggle() {
    if (this.box.open) return this.close()

    this.inputTarget.value = ""
    this.box.reveal()
    this.inputTarget.focus()
    this.search()
  }

  type() {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => this.search(), 150)
  }

  leave(event) {
    if (!this.element.contains(event.relatedTarget)) this.close()
  }

  async search() {
    const term = this.inputTarget.value.trim()
    this.abortController?.abort()
    if (term.length < this.leastValue) {
      if (this.inline) this.box.hide()
      return
    }

    const abortController = new AbortController()
    this.abortController = abortController
    let payload
    try {
      const response = await fetch(searchUrl(this.urlValue, term), {
        headers: { Accept: "application/json" },
        signal: abortController.signal
      })
      if (!response.ok) throw new Error(`search failed with ${response.status}`)
      payload = await response.json()
    } catch {
      if (!abortController.signal.aborted) this.close()
      return
    }
    if (abortController.signal.aborted) return
    if (this.inline ? document.activeElement !== this.inputTarget : !this.box.open) return

    const items = payload.members || payload.channels || payload.tags || []
    this.box.show(items.filter((item) => !this.selected.has(item.id)))
  }

  selectItem({ id, name, initial }) {
    if (this.singleValue) this.selected.clear()
    this.selected.set(id, { name, initial })
    this.inputTarget.value = ""
    this.close()
    this.render()
    if (this.submitValue) return this.element.closest("form")?.requestSubmit()

    this.suppressWake = true
    ;(this.inline ? this.inputTarget : this.triggerTarget).focus()
    this.suppressWake = false
  }

  removeToken(event) {
    this.selected.delete(event.currentTarget.dataset.id)
    this.render()
    this.inputTarget.focus()
  }

  keys(event) {
    if (this.box.keys(event)) {
      if (event.key === "Escape" && !this.inline) this.triggerTarget.focus()
      return
    }

    if (event.key === "Enter") {
      event.preventDefault()
      const inputValue = this.inputTarget.value.trim().toUpperCase()
      if (this.kindValue === "member" && SLACK_ID.test(inputValue)) {
        this.selectItem({ id: inputValue, name: `@${inputValue}`, initial: inputValue[1] })
      }
      return
    }

    if (event.key === "ArrowDown" && this.inline) {
      event.preventDefault()
      return this.search()
    }

    if (event.key === "Backspace" && this.inline && this.inputTarget.value === "" && this.selected.size > 0) {
      this.selected.delete([...this.selected.keys()].pop())
      this.render()
    }
  }

  close() {
    clearTimeout(this.timer)
    this.abortController?.abort()
    this.box.hide()
  }

  render() {
    if (this.inline) {
      for (const token of this.fieldTarget.querySelectorAll(".token")) token.remove()
      for (const [id, item] of this.selected) {
        this.fieldTarget.insertBefore(this.token(id, item), this.inputTarget)
      }
      this.inputTarget.placeholder = this.selected.size > 0 ? "" : this.blank
    }

    this.storeTarget.replaceChildren(...[...this.selected.keys()].map((id) => {
      const hiddenInput = document.createElement("input")
      hiddenInput.type = "hidden"
      hiddenInput.name = this.nameValue
      hiddenInput.value = id
      return hiddenInput
    }))
    this.dispatch("selected", { detail: { ids: [...this.selected.keys()] } })
  }

  token(id, { name, initial }) {
    const token = document.createElement("span")
    token.className = "token"
    const displayName = this.kindValue === "channel" ? `#${name}` : name
    const label = span("token-label", displayName)

    if (this.kindValue === "channel" || this.kindValue === "tag") {
      token.classList.add("token-plain")
    } else {
      token.append(avatarImage(id, initial))
      if (name === `@${id}`) label.dataset.cachetName = id
    }

    const remove = document.createElement("button")
    remove.type = "button"
    remove.className = "token-x"
    remove.dataset.id = id
    remove.dataset.action = "combobox#removeToken"
    remove.setAttribute("aria-label", `Remove ${displayName}`)
    remove.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>'

    token.append(label, remove)
    return token
  }
}
