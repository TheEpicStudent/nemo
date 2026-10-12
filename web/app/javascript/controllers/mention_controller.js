import { Controller } from "@hotwired/stimulus"
import { Listbox, searchUrl } from "lib/listbox"

const TOKEN = /@([\w.\-]*)$/

export default class extends Controller {
  static targets = ["field", "pop", "list"]
  static values = { url: String }

  connect() {
    this.timer = null
    this.box = new Listbox({
      pop: this.popTarget,
      list: this.listTarget,
      anchor: this.fieldTarget,
      input: this.fieldTarget,
      kind: "member",
      empty: "No members found",
      onSelect: ({ id }) => this.insertMention(id)
    })
    this.onOutsidePointer = (event) => {
      if (!this.element.contains(event.target)) this.close()
    }
    document.addEventListener("pointerdown", this.onOutsidePointer)
  }

  disconnect() {
    clearTimeout(this.timer)
    this.abortController?.abort()
    document.removeEventListener("pointerdown", this.onOutsidePointer)
    this.box.hide()
  }

  type() {
    clearTimeout(this.timer)
    this.timer = setTimeout(() => this.search(), 150)
  }

  token() {
    const beforeCaret = this.fieldTarget.value.slice(0, this.fieldTarget.selectionStart)
    return beforeCaret.match(TOKEN)
  }

  async search() {
    const match = this.token()
    this.abortController?.abort()
    if (!match || match[1].length < 2) return this.close()

    const abortController = new AbortController()
    this.abortController = abortController
    let members
    try {
      const response = await fetch(searchUrl(this.urlValue, match[1]), {
        headers: { Accept: "application/json" },
        signal: abortController.signal
      })
      if (!response.ok) throw new Error(`search failed with ${response.status}`)
      ;({ members } = await response.json())
    } catch {
      if (!abortController.signal.aborted) this.close()
      return
    }
    if (abortController.signal.aborted) return
    if (members.length === 0) return this.close()

    this.box.show(members)
  }

  insertMention(id) {
    const field = this.fieldTarget
    const at = field.selectionStart
    const match = this.token()
    if (!match) return

    const start = at - match[0].length
    field.value = `${field.value.slice(0, start)}@${id} ${field.value.slice(at)}`
    const caret = start + id.length + 2
    field.setSelectionRange(caret, caret)
    this.close()
    field.focus()
  }

  keys(event) {
    this.box.keys(event, { tab: true })
  }

  close() {
    clearTimeout(this.timer)
    this.abortController?.abort()
    this.box.hide()
  }
}
