import { Controller } from "@hotwired/stimulus"

const HOST = "https://cachet.hackclub.com"
const TTL = 12 * 60 * 60 * 1000
const LANES = 8
const NAME = "[data-cachet-name]"
const AVATAR = "img[data-cachet-face]"

const profileCache = new Map()
const pendingRequests = new Map()
const queue = []
let activeRequests = 0

function cachedProfile(id) {
  if (profileCache.has(id)) return profileCache.get(id)
  try {
    const raw = sessionStorage.getItem(`cachet:${id}`)
    if (!raw) return null
    const row = JSON.parse(raw)
    if (Date.now() - row.at > TTL) return null
    profileCache.set(id, row.profile)
    return row.profile
  } catch {
    return null
  }
}

function cacheProfile(id, profile) {
  profileCache.set(id, profile)
  try {
    sessionStorage.setItem(`cachet:${id}`, JSON.stringify({ at: Date.now(), profile }))
  } catch {
    return
  }
}

function drain() {
  while (activeRequests < LANES && queue.length > 0) {
    const { id, resolve } = queue.shift()
    activeRequests += 1
    fetch(`${HOST}/users/${encodeURIComponent(id)}`, { headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        const known = body && body.displayName && body.displayName !== "Unknown"
        const profile = { name: known ? body.displayName : null, image: known ? body.imageUrl : null }
        if (known || (body && body.displayName === "Unknown")) cacheProfile(id, profile)
        resolve(profile)
      })
      .catch(() => resolve(null))
      .finally(() => {
        activeRequests -= 1
        pendingRequests.delete(id)
        drain()
      })
  }
}

export function profile(id) {
  const cached = cachedProfile(id)
  if (cached) return Promise.resolve(cached)
  if (pendingRequests.has(id)) return pendingRequests.get(id)

  const request = new Promise((resolve) => queue.push({ id, resolve }))
  pendingRequests.set(id, request)
  drain()
  return request
}

function fallback(img) {
  const span = document.createElement("span")
  span.className = `${img.className} ${img.dataset.cachetTone || "avatar-none"}`.trim()
  span.textContent = img.dataset.cachetInitial || "?"
  span.setAttribute("aria-hidden", "true")
  for (const key of ["user", "name"]) {
    if (img.dataset[key] !== undefined) span.dataset[key] = img.dataset[key]
  }
  img.replaceWith(span)
}

function fill(node) {
  if (node.dataset.cachetDone) return
  node.dataset.cachetDone = "1"

  if (node.matches(AVATAR)) {
    const id = node.dataset.cachetFace
    node.addEventListener("error", () => fallback(node), { once: true })
    profile(id).then((result) => {
      if (result && result.name === null && node.isConnected) fallback(node)
    })
    return
  }

  const id = node.dataset.cachetName
  profile(id).then((result) => {
    if (result && result.name && node.isConnected) node.textContent = result.name
  })
}

export function hydrate(root) {
  if (!(root instanceof Element)) return
  if (root.matches(`${NAME}, ${AVATAR}`)) fill(root)
  for (const node of root.querySelectorAll(`${NAME}, ${AVATAR}`)) fill(node)
}

export default class extends Controller {
  connect() {
    hydrate(this.element)
    this.watcher = new MutationObserver((changes) => {
      for (const change of changes) {
        for (const node of change.addedNodes) hydrate(node)
      }
    })
    this.watcher.observe(this.element, { childList: true, subtree: true })
  }

  disconnect() {
    this.watcher?.disconnect()
  }
}
