import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useEffect, useRef, useState } from 'react'
import { getAccess, refreshSession } from '../api/client'
import type { AgentEvent } from '../api/types'
import { formatToolArgs, type ToolCallInfo } from '../components/ToolCallCard'

export type Live = {
  runId: string
  status: string
  note: string
  text: string
  tools: ToolCallInfo[]
  subtasks: { id: string; description: string; status: string }[]
  error?: string
}

export function useRunStream(runId: string | null) {
  const [live, setLive] = useState<Live | null>(null)
  const lastSeq = useRef(0)

  useEffect(() => {
    if (!runId) {
      setLive(null)
      return
    }
    const controller = new AbortController()
    const headers: Record<string, string> = {
      Authorization: `Bearer ${getAccess() ?? ''}`,
    }
    lastSeq.current = 0
    setLive({ runId, status: 'queued', note: '', text: '', tools: [], subtasks: [] })

    const apply = (event: AgentEvent) => {
      if (event.seq <= lastSeq.current) return
      lastSeq.current = event.seq
      const payload = event.payload ?? {}
      setLive((current) => {
        if (!current) return current
        switch (event.type) {
          case 'run.started':
            return { ...current, status: 'running', note: 'Researching…' }
          case 'run.progress':
            return { ...current, note: String(payload.note ?? 'Researching…') }
          case 'text.delta':
            return { ...current, text: current.text + String(payload.text ?? '') }
          case 'tool.started': {
            const id = String(payload.tool_call_id ?? '')
            if (!id || current.tools.some((tool) => tool.id === id)) return current
            return {
              ...current,
              tools: [
                ...current.tools,
                {
                  id,
                  name: String(payload.name ?? 'tool'),
                  args: formatToolArgs(payload.args),
                  done: false,
                },
              ],
            }
          }
          case 'tool.finished': {
            const id = String(payload.tool_call_id ?? '')
            return {
              ...current,
              tools: current.tools.map((tool) =>
                tool.id === id
                  ? {
                      ...tool,
                      done: true,
                      ok: payload.ok !== false,
                      summary: String(payload.summary ?? ''),
                    }
                  : tool,
              ),
            }
          }
          case 'subtask.started':
            return {
              ...current,
              subtasks: [
                ...current.subtasks,
                {
                  id: String(payload.subagent_id ?? ''),
                  description: String(payload.description ?? ''),
                  status: 'running',
                },
              ],
            }
          case 'subtask.finished':
            return {
              ...current,
              subtasks: current.subtasks.map((task) =>
                task.id === String(payload.subagent_id ?? '')
                  ? { ...task, status: String(payload.status ?? 'finished') }
                  : task,
              ),
            }
          case 'message.completed':
            return { ...current, text: String(payload.content ?? current.text) }
          case 'run.finished':
            return {
              ...current,
              status: String(payload.status ?? 'failed'),
              error: payload.error ? String(payload.error) : current.error,
            }
          case 'error':
            return { ...current, error: String(payload.message ?? 'Research failed.') }
          default:
            return current
        }
      })
    }

    void fetchEventSource(`/v1/runs/${encodeURIComponent(runId)}/events`, {
      signal: controller.signal,
      openWhenHidden: true,
      credentials: 'include',
      headers,
      async onopen(response) {
        if (response.ok && response.headers.get('content-type')?.includes('text/event-stream')) return
        if (response.status === 401 && (await refreshSession())) {
          headers.Authorization = `Bearer ${getAccess() ?? ''}`
          throw new Error('reconnect')
        }
        throw new Error(response.statusText || 'stream failed')
      },
      onmessage(message) {
        if (!message.data) return
        try {
          apply({
            seq: Number(message.id || 0),
            type: message.event || 'message',
            payload: JSON.parse(message.data),
          })
        } catch {
          // Ignore malformed or unknown events.
        }
      },
      onerror(error) {
        if (controller.signal.aborted) throw error
        return 3000
      },
    })

    return () => controller.abort()
  }, [runId])

  return live
}
