import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useEffect, useRef, useState } from 'react'
import { api, getAccess } from '../api/client'
import type { AgentEvent } from '../api/types'
import { formatToolArgs, type ToolCallInfo } from '../components/ToolCallCard'

export type Live = {
  runId: string
  status: string
  note: string
  reasoning: string
  text: string
  tools: ToolCallInfo[]
  error?: string
}

export function reduceLive(live: Live, ev: AgentEvent): Live {
  const p = payloadOf(ev)
  switch (ev.type) {
    case 'run.started':
      return { ...live, status: 'running', note: live.note || 'thinking' }
    case 'run.progress':
      return { ...live, status: 'running', note: String(p.note ?? live.note ?? 'thinking') }
    case 'reasoning_delta':
      return { ...live, reasoning: live.reasoning + String(p.delta ?? '') }
    case 'text_delta':
      return { ...live, text: live.text + String(p.delta ?? '') }
    case 'tool_call.started': {
      const id = String(p.tool_call_id ?? '')
      if (!id || live.tools.some((tool) => tool.id === id)) return live
      return {
        ...live,
        tools: [
          ...live.tools,
          { id, name: String(p.name ?? 'tool'), args: formatToolArgs(p.args), done: false },
        ],
      }
    }
    case 'tool_call.finished': {
      const id = String(p.tool_call_id ?? '')
      return {
        ...live,
        tools: live.tools.map((tool) =>
          tool.id === id
            ? { ...tool, done: true, ok: p.ok !== false, summary: String(p.summary ?? '') }
            : tool,
        ),
      }
    }
    case 'message.completed':
      return { ...live, text: String(p.content ?? live.text) }
    case 'run.finished':
      return {
        ...live,
        status: String(p.status ?? 'succeeded'),
        error: p.error ? String(p.error) : live.error,
      }
    case 'error':
      return { ...live, error: String(p.message ?? 'error') }
    default:
      return live
  }
}

export function useRunActivity(runId: string | null) {
  const [live, setLive] = useState<Live | null>(null)

  useEffect(() => {
    if (!runId) {
      setLive(null)
      return
    }
    let dead = false
    const ac = new AbortController()
    let seq = 0
    let current: Live = { runId, status: 'queued', note: '', reasoning: '', text: '', tools: [] }
    let flushTimer: number | null = null
    setLive(current)

    const publish = () => {
      if (!dead) setLive(current)
    }
    const schedule = () => {
      if (flushTimer != null) return
      flushTimer = window.requestAnimationFrame(() => {
        flushTimer = null
        publish()
      })
    }
    const apply = (ev: AgentEvent, immediate: boolean) => {
      if (ev.seq && ev.seq <= seq) return
      if (ev.seq) seq = ev.seq
      const next = reduceLive(current, ev)
      if (next === current) return
      current = next
      if (immediate) publish()
      else schedule()
    }

    void (async () => {
      try {
        let after = 0
        for (let page = 0; page < 40; page++) {
          const body = await api<{ items: AgentEvent[] }>(
            `/v1/runs/${encodeURIComponent(runId)}/events?after=${after}&limit=500`,
          )
          if (dead) return
          const batch = body.items ?? []
          if (batch.length === 0) break
          for (const ev of batch) apply(ev, false)
          publish()
          after = Number(batch[batch.length - 1]?.seq ?? after)
          if (batch.length < 500) break
        }
      } catch {
        /* the live stream still fills whatever the journal missed */
      }
      if (dead) return
      const headers: Record<string, string> = { Authorization: `Bearer ${getAccess() ?? ''}` }
      if (seq > 0) headers['Last-Event-ID'] = String(seq)
      void fetchEventSource(`/v1/streams/run/${runId}`, {
        signal: ac.signal,
        openWhenHidden: true,
        headers,
        async onopen(response) {
          const type = response.headers.get('content-type') || ''
          if (response.ok && type.includes('text/event-stream')) return
          const err = new Error(response.statusText || 'stream failed') as Error & { status?: number }
          err.status = response.status
          throw err
        },
        onmessage(msg) {
          if (!msg.data) return
          try {
            apply(
              { ...JSON.parse(msg.data), type: msg.event || 'message', seq: Number(msg.id || 0) },
              false,
            )
          } catch {
            /* ignore unknown */
          }
        },
        onerror(err) {
          if (ac.signal.aborted || dead) throw err
          const status = (err as { status?: number }).status
          if (status === 401 || status === 404) throw err
          if (status === 429) return 15000
          return 3000
        },
      })
    })()

    return () => {
      dead = true
      ac.abort()
      if (flushTimer != null) window.cancelAnimationFrame(flushTimer)
    }
  }, [runId])

  return live
}

function payloadOf(ev: AgentEvent): Record<string, unknown> {
  const raw = ev.payload
  if (!raw) return {}
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw) as unknown
      return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {}
    } catch {
      return {}
    }
  }
  return raw
}

export function useRunStream(runId: string | null, enabled: boolean) {
  const [live, setLive] = useState<Live | null>(null)
  const lastSeq = useRef(0)
  const buf = useRef({ reasoning: '', text: '' })
  const flushTimer = useRef<number | null>(null)

  useEffect(() => {
    if (!runId || !enabled) {
      lastSeq.current = 0
      buf.current = { reasoning: '', text: '' }
      if (!runId) setLive(null)
      return
    }
    const ac = new AbortController()
    lastSeq.current = 0
    buf.current = { reasoning: '', text: '' }
    setLive({ runId, status: 'queued', note: '', reasoning: '', text: '', tools: [] })

    const flush = () => {
      flushTimer.current = null
      setLive((cur) =>
        cur
          ? { ...cur, reasoning: buf.current.reasoning, text: buf.current.text }
          : cur,
      )
    }
    const schedule = () => {
      if (flushTimer.current != null) return
      flushTimer.current = window.requestAnimationFrame(flush)
    }

    const apply = (ev: AgentEvent) => {
      if (ev.seq && ev.seq <= lastSeq.current) return
      if (ev.seq) lastSeq.current = ev.seq
      const p = payloadOf(ev)
      switch (ev.type) {
        case 'run.started':
          setLive((c) => (c ? { ...c, status: 'running', note: c.note || 'thinking' } : c))
          break
        case 'run.progress':
          setLive((c) => (c ? { ...c, status: 'running', note: String(p.note ?? c.note ?? 'thinking') } : c))
          break
        case 'reasoning_delta':
          buf.current.reasoning += String(p.delta ?? '')
          schedule()
          break
        case 'text_delta':
          buf.current.text += String(p.delta ?? '')
          schedule()
          break
        case 'tool_call.started':
          setLive((c) => {
            if (!c) return c
            const id = String(p.tool_call_id ?? '')
            if (c.tools.some((t) => t.id === id)) return c
            return {
              ...c,
              tools: [
                ...c.tools,
                {
                  id,
                  name: String(p.name ?? 'tool'),
                  args: formatToolArgs(p.args),
                  done: false,
                },
              ],
            }
          })
          break
        case 'tool_call.finished':
          setLive((c) => {
            if (!c) return c
            const id = String(p.tool_call_id ?? '')
            return {
              ...c,
              tools: c.tools.map((t) =>
                t.id === id
                  ? { ...t, done: true, ok: p.ok !== false, summary: String(p.summary ?? '') }
                  : t,
              ),
            }
          })
          break
        case 'message.completed':
          buf.current.text = String(p.content ?? buf.current.text)
          flush()
          break
        case 'run.finished':
          flush()
          setLive((c) =>
            c ? { ...c, status: String(p.status ?? 'succeeded'), error: p.error ? String(p.error) : undefined } : c,
          )
          break
        case 'error':
          setLive((c) => (c ? { ...c, error: String(p.message ?? 'error') } : c))
          break
        default:
          break
      }
    }

    void fetchEventSource(`/v1/streams/run/${runId}`, {
      signal: ac.signal,
      openWhenHidden: true,
      headers: { Authorization: `Bearer ${getAccess() ?? ''}` },
      async onopen(response) {
        const type = response.headers.get('content-type') || ''
        if (response.ok && type.includes('text/event-stream')) return
        const err = new Error(response.statusText || 'stream failed') as Error & { status?: number }
        err.status = response.status
        throw err
      },
      onmessage(msg) {
        if (!msg.data) return
        try {
          apply({ ...JSON.parse(msg.data), type: msg.event || 'message', seq: Number(msg.id || 0) })
        } catch {
          /* ignore unknown */
        }
      },
      onerror(err) {
        if (ac.signal.aborted) throw err
        const status = (err as { status?: number }).status
        if (status === 401 || status === 404) throw err
        if (status === 429) return 15000
        return 3000
      },
    })

    return () => {
      ac.abort()
      if (flushTimer.current != null) window.cancelAnimationFrame(flushTimer.current)
    }
  }, [runId, enabled])

  return live
}
