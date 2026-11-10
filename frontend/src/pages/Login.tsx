import { useState, type FormEvent } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { api, scheduleRefresh, setSession } from '../api/client'
import type { TokenPair } from '../api/types'

export function LoginPage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const pair = await api<TokenPair>(`/v1/auth/${mode}`, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
        skipAuth: true,
      })
      setSession(pair)
      scheduleRefresh(pair.expires_in)
      navigate({ to: '/' })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Authentication failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-full grid place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm border border-[#2a2a2a] bg-[#141414] p-6">
        <h1 className="text-[15px] font-medium mb-1">Deep Research</h1>
        <p className="text-[#8a8a8a] mb-5">Your conversations are isolated by account.</p>
        <label className="block mb-3">
          <span className="text-[#8a8a8a] text-xs">Email</span>
          <input
            className="mt-1 w-full bg-[#0e0e0e] border border-[#2a2a2a] px-2 py-1.5 outline-none"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
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
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error && <p className="text-red-400 text-xs mb-3">{error}</p>}
        <button disabled={busy} className="w-full bg-[#e8e8e8] text-[#111] py-1.5 disabled:opacity-50">
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
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
