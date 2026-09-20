import { api } from '../api/client'
import type { AgentEvent } from '../api/types'
import { formatToolArgs, type ToolCallInfo } from '../components/ToolCallCard'

export type Trace = {
  reasoning: string
  tools: ToolCallInfo[]
}

export function payloadOf(ev: Pick<AgentEvent, 'payload'>): Record<string, unknown> {
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

export function mergeTrace(prev: Trace | undefined, next: Trace): Trace {
  return {
    reasoning: next.reasoning.length >= (prev?.reasoning.length ?? 0) ? next.reasoning : prev?.reasoning ?? '',
    tools: next.tools.length >= (prev?.tools.length ?? 0) ? next.tools : prev?.tools ?? [],
  }
}

export function traceFromEvents(events: AgentEvent[]): Trace {
  let reasoning = ''
  const tools: ToolCallInfo[] = []
  const byId = new Map<string, ToolCallInfo>()
  for (const ev of events) {
    const p = payloadOf(ev)
    switch (ev.type) {
      case 'reasoning_delta':
        reasoning += String(p.delta ?? '')
        break
      case 'tool_call.started': {
        const id = String(p.tool_call_id ?? '')
        if (!id || byId.has(id)) break
        const t: ToolCallInfo = {
          id,
          name: String(p.name ?? 'tool'),
          args: formatToolArgs(p.args),
          done: false,
        }
        byId.set(id, t)
        tools.push(t)
        break
      }
      case 'tool_call.finished': {
        const id = String(p.tool_call_id ?? '')
        const prev = byId.get(id)
        if (!prev) break
        prev.done = true
        prev.ok = p.ok !== false
        prev.summary = String(p.summary ?? '')
        break
      }
      default:
        break
    }
  }
  return { reasoning, tools }
}

export async function fetchRunTrace(runId: string): Promise<Trace> {
  const events: AgentEvent[] = []
  let after = 0
  for (let i = 0; i < 40; i++) {
    const page = await api<{ items: AgentEvent[] }>(
      `/v1/runs/${encodeURIComponent(runId)}/events?after=${after}&limit=500`,
    )
    const batch = page.items ?? []
    if (batch.length === 0) break
    events.push(...batch)
    after = Number(batch[batch.length - 1]?.seq ?? after)
    if (batch.length < 500) break
  }
  return traceFromEvents(events)
}
