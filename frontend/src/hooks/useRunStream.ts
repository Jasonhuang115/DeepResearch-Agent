import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useEffect, useRef, useState } from 'react'
import { getAccess } from '../api/client'
import type { AgentEvent } from '../api/types'

export type Live = {
  runId: string
  status: string
  reasoning: string
  text: string
  tools: { id: string; name: string; summary?: string; done: boolean }[]
  error?: string
}

export function useRunStream(runId: string | null, enabled: boolean) {
  const [live, setLive] = useState<Live | null>(null)
  const lastSeq = useRef(0)
  const buf = useRef({ reasoning: '', text: '' })
  const flushTimer = useRef<number | null>(null)

  useEffect(() => {
    if (!runId || !enabled) {
      setLive(null)
      lastSeq.current = 0
      buf.current = { reasoning: '', text: '' }
      return
    }
    const ac = new AbortController()
    setLive({ runId, status: 'queued', reasoning: '', text: '', tools: [] })
    buf.current = { reasoning: '', text: '' }

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
      flushTimer.current = window.setTimeout(flush, 60)
    }

    const apply = (ev: AgentEvent) => {
      if (ev.seq && ev.seq <= lastSeq.current) return
      if (ev.seq) lastSeq.current = ev.seq
      const p = ev.payload || {}
      switch (ev.type) {
        case 'run.started':
          setLive((c) => (c ? { ...c, status: 'running' } : c))
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
            return { ...c, tools: [...c.tools, { id, name: String(p.name ?? 'tool'), done: false }] }
          })
          break
        case 'tool_call.finished':
          setLive((c) => {
            if (!c) return c
            const id = String(p.tool_call_id ?? '')
            return {
              ...c,
              tools: c.tools.map((t) =>
                t.id === id ? { ...t, done: true, summary: String(p.summary ?? '') } : t,
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
      onmessage(msg) {
        if (!msg.data) return
        try {
          apply({ ...JSON.parse(msg.data), type: msg.event || 'message', seq: Number(msg.id || 0) })
        } catch {
          /* ignore unknown */
        }
      },
    })

    return () => {
      ac.abort()
      if (flushTimer.current) window.clearTimeout(flushTimer.current)
    }
  }, [runId, enabled])

  return live
}
