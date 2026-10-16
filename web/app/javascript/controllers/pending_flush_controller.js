import { Controller } from "@hotwired/stimulus"
import { syncFrame } from "turbo_actions"

export default class extends Controller {
  static values = { frame: String }

  connect() {
    this.streamDisconnected = false
    this.onChange = this.onChange.bind(this)
    this.onVisible = this.onVisible.bind(this)

    document.addEventListener("visibilitychange", this.onVisible)

    const source = this.source
    if (!source) return

    this.observer = new MutationObserver(this.onChange)
    this.observer.observe(source, { attributeFilter: ["connected"] })
  }

  disconnect() {
    document.removeEventListener("visibilitychange", this.onVisible)
    if (this.observer) this.observer.disconnect()
  }

  get source() {
    return this.element.querySelector("turbo-cable-stream-source")
  }

  onChange() {
    const source = this.source
    if (!source) return

    if (!source.hasAttribute("connected")) {
      this.streamDisconnected = true
      return
    }

    if (!this.streamDisconnected) return

    this.streamDisconnected = false
    this.syncFrame()
  }

  onVisible() {
    if (document.visibilityState === "visible") this.syncFrame()
  }

  syncFrame() {
    syncFrame(document.getElementById(this.frameValue))
  }
}
