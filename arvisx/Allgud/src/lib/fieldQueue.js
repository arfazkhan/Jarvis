// Offline-tolerant entry queue for the field round-runner.
//
// A technician on a basement/stairwell with flaky signal must NEVER lose a tap.
// When an entry save fails on the network (not a real 4xx from the server), we
// stash it in localStorage and replay it: on reconnect, on the next app load,
// and on a periodic flush. The UI treats a queued entry as saved-pending so the
// tech keeps moving — paper never blocked them, neither do we.
//
// Scope note: this queues the small JSON entry writes (status/value/note), the
// high-frequency path. Photo uploads are larger and stay best-effort for now.

import { api } from '../api/client'

const KEY = 'allgud.fieldqueue'
const listeners = new Set()

function read() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]')
  } catch {
    return []
  }
}

function write(items) {
  localStorage.setItem(KEY, JSON.stringify(items))
  listeners.forEach((cb) => cb(items.length))
}

// A real server rejection looks like "<status>: detail" (see client.request).
// Anything else (TypeError "Failed to fetch", timeouts) is a transport failure
// we should retry rather than drop.
export function isNetworkError(err) {
  return !/^\d{3}:/.test(String(err && err.message))
}

export function queueSize() {
  return read().length
}

export function subscribe(cb) {
  listeners.add(cb)
  cb(read().length)
  return () => listeners.delete(cb)
}

export function enqueue(rid, body) {
  const items = read()
  items.push({ rid, body, ts: Date.now() })
  write(items)
}

let flushing = false

// Replay queued entries in order. Stops at the first transport failure (still
// offline) and leaves the rest queued. Returns true if the queue is now empty.
export async function flush() {
  if (flushing) return read().length === 0
  flushing = true
  try {
    let items = read()
    while (items.length) {
      const head = items[0]
      try {
        await api.entry(head.rid, head.body)
      } catch (err) {
        if (isNetworkError(err)) break // still offline — try again later
        // a real rejection (e.g. run already submitted): drop it, can't retry
      }
      items = items.slice(1)
      write(items)
    }
    return read().length === 0
  } finally {
    flushing = false
  }
}

// Wire automatic replay once per app load.
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => { flush() })
  flush()
}
