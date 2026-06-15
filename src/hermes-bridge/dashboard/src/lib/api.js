/**
 * ServerStick API client — thin wrapper around fetch() for the Svelte dashboard.
 * All calls are relative; vite proxies /api and /ws to the hermes-bridge on :8080.
 */

const API_BASE = ''  // relative; vite proxy handles routing

async function request(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // ─── Onboarding ──────────────────────────────────────────────────
  onboardSubdomain: (subdomain) =>
    request('/api/onboard/subdomain', {
      method: 'POST',
      body: JSON.stringify({ subdomain }),
    }),

  onboardBrain: (data) =>
    request('/api/onboard/brain', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  onboardBrainStatus: (jobId) =>
    request(`/api/onboard/brain/${jobId}`),

  // ─── Hardware & Mining ───────────────────────────────────────────
  hardwareScan: () =>
    request('/api/hardware/scan', { method: 'POST' }),

  mineCheck: () =>
    request('/api/mine/check', { method: 'POST' }),

  getHardware: () =>
    request('/api/hardware'),

  // ─── Services ────────────────────────────────────────────────────
  listServices: () =>
    request('/api/services'),

  serviceAction: (id, action) =>
    request(`/api/services/${id}/${action}`, { method: 'POST' }),

  listRecipes: () =>
    request('/api/services/recipes'),

  installRecipe: (recipe, github = null) =>
    request('/api/services/install', {
      method: 'POST',
      body: JSON.stringify({ recipe, github }),
    }),

  // ─── Hermes ──────────────────────────────────────────────────────
  getHermesLogs: () =>
    request('/api/hermes/logs'),

  getCredit: () =>
    request('/api/credit'),

  // ─── Chat (WebSocket) ────────────────────────────────────────────
  openChatSocket() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return new WebSocket(`${proto}//${location.host}/ws/chat`)
  },

  // ─── Status ──────────────────────────────────────────────────────
  getStatus: () =>
    request('/api/status'),
}
