import { useState } from 'react'

export type ToolCallInfo = {
  id: string
  name: string
  args?: string
  summary?: string
  done: boolean
  ok?: boolean
}

export function formatToolArgs(raw: unknown): string {
  if (raw == null || raw === '') return ''
  if (typeof raw === 'string') return collapse(raw)
  if (typeof raw === 'object' && !Array.isArray(raw)) {
    const rec = raw as Record<string, unknown>
    for (const key of ['query', 'url', 'path', 'command', 'pattern', 'glob']) {
      const v = rec[key]
      if (typeof v === 'string' && v.trim()) return collapse(v)
    }
    try {
      return collapse(JSON.stringify(rec))
    } catch {
      return ''
    }
  }
  return collapse(String(raw))
}

function collapse(raw: string): string {
  const cleaned = raw.replace(/\s+/g, ' ').trim()
  return cleaned.length > 80 ? `${cleaned.slice(0, 80)}…` : cleaned
}

function argsFromSummary(summary?: string): string {
  if (!summary) return ''
  const query = summary.match(/\bquery:\s*(.+?)(?:\s+results:|$)/i)
  if (query?.[1]) return collapse(query[1])
  const url = summary.match(/\burl:\s*(\S+)/i)
  if (url?.[1]) return collapse(url[1])
  return ''
}

function isFailed(call: ToolCallInfo): boolean {
  if (!call.done) return false
  if (call.ok === false) return true
  return /^\s*error:/i.test(call.summary ?? '')
}

export function ToolCallCard({ call }: { call: ToolCallInfo }) {
  const running = !call.done
  const failed = isFailed(call)
  const [open, setOpen] = useState(false)
  const hasOutput = Boolean(call.summary)
  const showOutput = (running && hasOutput) || (open && hasOutput)
  const args = call.args ? collapse(call.args) : argsFromSummary(call.summary)
  const tone = running ? 'dx-tool--running' : failed ? 'dx-tool--err' : 'dx-tool--ok'

  return (
    <div className={`dx-tool ${tone}${showOutput ? ' dx-tool--open' : ''}`}>
      <button
        type="button"
        className="dx-tool__head"
        onClick={() => {
          if (!running && hasOutput) setOpen((v) => !v)
        }}
      >
        <span className="dx-tool__icon" aria-hidden>
          {running ? (
            <span className="dx-tool__spin" />
          ) : failed ? (
            <XIcon />
          ) : (
            <CheckIcon />
          )}
        </span>
        <span className="dx-tool__name">{call.name || 'tool'}</span>
        {args && <span className="dx-tool__args">{args}</span>}
        <span className="dx-tool__status">{running ? 'running…' : failed ? 'failed' : 'done'}</span>
        {!running && hasOutput && (
          <span className="dx-tool__chev" aria-hidden>
            {open ? '▾' : '▸'}
          </span>
        )}
      </button>
      {showOutput && hasOutput && <div className="dx-tool__out">{call.summary}</div>}
    </div>
  )
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.5 2.5L16 9.5" />
    </svg>
  )
}

function XIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </svg>
  )
}
