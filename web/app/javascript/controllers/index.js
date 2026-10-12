import { application } from "controllers/application"
import { eagerLoadControllersFrom } from "@hotwired/stimulus-loading"

eagerLoadControllersFrom("controllers", application)

const chartPaths = Object.keys(
  JSON.parse(document.querySelector("script[type=importmap]").text).imports
).filter((path) => /^charts\/.*_controller$/.test(path))

const pendingCharts = new Map(chartPaths.map((path) => [
  path.replace(/^charts\//, "").replace(/_controller$/, "").replace(/_/g, "-"),
  path
]))

let observer = null

function isOnPage(name) {
  return document.querySelector(`[data-controller~="${name}"]`) !== null
}

function registerPageCharts() {
  for (const [name, path] of pendingCharts) {
    if (!isOnPage(name)) continue

    pendingCharts.delete(name)
    import(path)
      .then((module) => application.register(name, module.default))
      .catch((error) => console.error(`Failed to register chart controller: ${name} (${path})`, error))
  }
  if (pendingCharts.size === 0 && observer) {
    observer.disconnect()
    observer = null
  }
}

registerPageCharts()

if (pendingCharts.size > 0) {
  observer = new MutationObserver(registerPageCharts)
  observer.observe(document.documentElement, {
    attributeFilter: ["data-controller"],
    subtree: true,
    childList: true
  })
}

const chartNames = new Set(chartPaths.map((path) =>
  path.replace(/^charts\//, "").replace(/_controller$/, "").replace(/_/g, "-")))

document.addEventListener("turbo:morph", () => {
  application.controllers
    .filter((controller) => chartNames.has(controller.identifier))
    .filter((controller) => !controller.element.closest("[data-turbo-permanent]"))
    .forEach((controller) => {
      controller.disconnect?.()
      controller.connect?.()
    })
})
