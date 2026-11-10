import type { TokenPair } from './types'

const ACCESS = 'dra.access'
const USER = 'dra.user'

export function getAccess() {
  return sessionStorage.getItem(ACCESS)
}

export function getUser() {
  const raw = localStorage.getItem(USER)
  return raw ? (JSON.parse(raw) as TokenPair['user']) : null
}

export function setSession(pair: TokenPair) {
  sessionStorage.setItem(ACCESS, pair.access_token)
  localStorage.setItem(USER, JSON.stringify(pair.user))
}

export function clearSession() {
  sessionStorage.removeItem(ACCESS)
  localStorage.removeItem(USER)
}

let refreshFlight: Promise<boolean> | null = null

export async function refreshSession(): Promise<boolean> {
  if (refreshFlight) return refreshFlight
  refreshFlight = (async () => {
    const res = await fetch('/v1/auth/refresh', { method: 'POST', credentials: 'include' })
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
  window.setTimeout(() => void refreshSession(), wait)
}

type Opts = RequestInit & { skipAuth?: boolean }

export async function api<T>(path: string, opts: Opts = {}): Promise<T> {
  const headers = new Headers(opts.headers)
  const isForm = typeof FormData !== 'undefined' && opts.body instanceof FormData
  if (isForm) headers.delete('Content-Type')
  else if (!headers.has('Content-Type') && opts.body) headers.set('Content-Type', 'application/json')
  const token = getAccess()
  if (token && !opts.skipAuth) headers.set('Authorization', `Bearer ${token}`)
  let res = await fetch(path, { ...opts, headers, credentials: 'include' })
  if (res.status === 401 && !opts.skipAuth) {
    if (!(await refreshSession())) {
      if (!location.pathname.startsWith('/login')) location.assign('/login')
      throw new Error('unauthorized')
    }
    headers.set('Authorization', `Bearer ${getAccess()}`)
    res = await fetch(path, { ...opts, headers, credentials: 'include' })
  }
  const text = await res.text()
  const json = text ? JSON.parse(text) : {}
  if (!res.ok) {
    const err = new Error(json?.error?.message || res.statusText) as Error & {
      code?: string
      status?: number
    }
    err.code = json?.error?.code
    err.status = res.status
    throw err
  }
  return json.data as T
}

export function newIdempotencyKey() {
  return crypto.randomUUID()
}

export async function logout() {
  try {
    await api('/v1/auth/logout', { method: 'POST' })
  } finally {
    clearSession()
  }
}

export async function downloadAttachment(id: string, filename: string) {
  const res = await fetch(`/v1/attachments/${encodeURIComponent(id)}/download`, {
    headers: { Authorization: `Bearer ${getAccess() ?? ''}` },
    credentials: 'include',
  })
  if (!res.ok) throw new Error('download failed')
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
