import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static values = { name: String, options: Object }

  async connect() {
    const token = (this.token = Symbol("connect"))
    const { default: Effect } = await import(`react_bits/${this.nameValue}`)
    if (this.token !== token || !this.element.isConnected) return

    this.effect = new Effect(this.element, this.optionsValue)
  }

  disconnect() {
    this.token = null
    this.effect?.destroy()
    this.effect = null
  }
}
