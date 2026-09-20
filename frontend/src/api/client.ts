import type { TokenPair } from './types'

const ACCESS = 'dra.access'
const REFRESH = 'dra.refresh'
const USER = 'dra.user'

export function getAccess() {
  return localStorage.getItem(ACCESS)
}

export function getUser() {
  const raw = localStorage.getItem(USER)
  return raw ? (JSON.parse(raw) as TokenPair['user']) : null
}

export function setSession(pair: TokenPair) {
  localStorage.setItem(ACCESS, pair.access_token)
  localStorage.setItem(REFRESH, pair.refresh_token)
  localStorage.setItem(USER, JSON.stringify(pair.user))
}

export function clearSession() {
  localStorage.removeItem(ACCESS)
  localStorage.removeItem(REFRESH)
  localStorage.removeItem(USER)
}

let refreshFlight: Promise<boolean> | null = null

async function refreshOnce(): Promise<boolean> {
  if (refreshFlight) return refreshFlight
  refreshFlight = (async () => {
    const refresh = localStorage.getItem(REFRESH)
    if (!refresh) return false
    const res = await fetch('/v1/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!res.ok) {
      clearSession()
      return false
    }
    const body = await res.json()
    setSession(body.data)
    return true
  })().finally(() => {
    refreshFlight = null
  })
  return refreshFlight
}

export function scheduleRefresh(expiresIn: number) {
  const wait = Math.max(30_000, (expiresIn - 60) * 1000)
  window.setTimeout(() => {
    void refreshOnce()
  }, wait)
}

type Opts = RequestInit & { skipAuth?: boolean }

export async function api<T>(path: string, opts: Opts = {}): Promise<T> {
  const headers = new Headers(opts.headers)
  const form = typeof FormData !== 'undefined' && opts.body instanceof FormData
  if (form) headers.delete('Content-Type')
  else if (!headers.has('Content-Type') && opts.body) headers.set('Content-Type', 'application/json')
  const token = getAccess()
  if (token && !opts.skipAuth) headers.set('Authorization', `Bearer ${token}`)
  let res = await fetch(path, { ...opts, headers })
  if (res.status === 401 && !opts.skipAuth) {
    const ok = await refreshOnce()
    if (!ok) {
      clearSession()
      if (!location.pathname.startsWith('/login')) location.assign('/login')
      throw new Error('unauthorized')
    }
    headers.set('Authorization', `Bearer ${getAccess()}`)
    res = await fetch(path, { ...opts, headers })
  }
  const text = await res.text()
  const json = text ? JSON.parse(text) : {}
  if (!res.ok) {
    const msg = json?.error?.message || res.statusText
    const err = new Error(msg) as Error & { code?: string; status?: number }
    err.code = json?.error?.code
    err.status = res.status
    throw err
  }
  return json.data as T
}

export function newIdempotencyKey() {
  return crypto.randomUUID()
}
