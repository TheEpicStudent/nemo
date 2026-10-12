import { Controller } from "@hotwired/stimulus"

const STEP_INTERVAL_MS = 700

export default class extends Controller {
  static targets = ["button", "label"]
  static values = { steps: Number }

  disconnect() {
    this.stop()
  }

  play() {
    this.stop()
    this.show(0)
    let step = 0
    this.timer = setInterval(() => {
      step += 1
      if (step >= this.stepsValue) return this.stop()
      this.show(step)
    }, STEP_INTERVAL_MS)
  }

  stop() {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    this.show(this.stepsValue)
  }

  focus(event) {
    const user = event.currentTarget.dataset.user
    const linked = new Set([user])
    this.element.querySelectorAll("path.edge").forEach((edge) => {
      const connected = edge.dataset.a === user || edge.dataset.b === user
      edge.classList.toggle("is-lit", connected)
      if (connected) linked.add(edge.dataset.a).add(edge.dataset.b)
    })
    this.element.querySelectorAll(".node").forEach((node) => {
      node.classList.toggle("is-lit", linked.has(node.dataset.user))
    })
    this.element.classList.add("is-focus")
    if (!this.hasLabelTarget) return

    const node = event.currentTarget
    this.labelTarget.textContent = node.dataset.name
    this.labelTarget.setAttribute("x", node.dataset.x)
    this.labelTarget.setAttribute("y", node.dataset.y)
    this.labelTarget.classList.add("is-on")
  }

  blur() {
    this.element.classList.remove("is-focus")
    if (this.hasLabelTarget) this.labelTarget.classList.remove("is-on")
    this.element.querySelectorAll(".is-lit").forEach((element) => element.classList.remove("is-lit"))
  }

  show(step) {
    this.element.querySelectorAll("[data-step]").forEach((element) => {
      element.classList.toggle("is-later", Number(element.dataset.step) > step)
    })
  }
}
