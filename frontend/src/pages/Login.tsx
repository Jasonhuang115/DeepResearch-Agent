import { useState, type FormEvent } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { api, scheduleRefresh, setSession } from '../api/client'
import type { TokenPair } from '../api/types'

export function LoginPage() {
  const nav = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setErr('')
    setBusy(true)
    try {
      const path = mode === 'login' ? '/v1/auth/login' : '/v1/auth/register'
      const body =
        mode === 'login'
          ? { email, password }
          : { email, password, display_name: name }
      const pair = await api<TokenPair>(path, {
        method: 'POST',
        body: JSON.stringify(body),
        skipAuth: true,
      })
      setSession(pair)
      scheduleRefresh(pair.expires_in)
      nav({ to: '/' })
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : 'failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-full grid place-items-center px-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm border border-[#2a2a2a] bg-[#141414] p-6">
        <h1 className="text-[15px] font-medium mb-1">Research</h1>
        <p className="text-[#8a8a8a] mb-5">Sign in to keep conversations isolated per account.</p>
        {mode === 'register' && (
          <label className="block mb-3">
            <span className="text-[#8a8a8a] text-xs">Name</span>
            <input
              className="mt-1 w-full bg-[#0e0e0e] border border-[#2a2a2a] px-2 py-1.5 outline-none"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        )}
        <label className="block mb-3">
          <span className="text-[#8a8a8a] text-xs">Email</span>
          <input
            className="mt-1 w-full bg-[#0e0e0e] border border-[#2a2a2a] px-2 py-1.5 outline-none"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="block mb-4">
          <span className="text-[#8a8a8a] text-xs">Password</span>
          <input
            className="mt-1 w-full bg-[#0e0e0e] border border-[#2a2a2a] px-2 py-1.5 outline-none"
            type="password"
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {err && <p className="text-red-400 text-xs mb-3">{err}</p>}
        <button
          disabled={busy}
          className="w-full bg-[#e8e8e8] text-[#111] py-1.5 text-sm disabled:opacity-50"
        >
          {mode === 'login' ? 'Sign in' : 'Create account'}
        </button>
        <button
          type="button"
          className="w-full mt-3 text-[#8a8a8a] text-xs"
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
        >
          {mode === 'login' ? 'Need an account?' : 'Have an account?'}
        </button>
      </form>
    </div>
  )
}
