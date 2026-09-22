import { useEffect, useMemo, useState } from 'react'
import { ToolCallCard } from './ToolCallCard'
import { useRunActivity } from '../hooks/useRunStream'
import { Markdown } from '../lib/Markdown'
import { chipLabel, drawerRows, isDone, type SubagentRun } from '../lib/subagents'

function streamStatus(listed: string, streamed?: string) {
  if (!streamed || streamed === 'queued') return listed
  return streamed
}

export function SubagentChip({ items, onOpen }: { items: SubagentRun[]; onOpen: () => void }) {
  if (items.length === 0) return null
  const spinning = items.some((item) => !isDone(item.status))
  return (
    <button type="button" className="dx-subchip" onClick={onOpen}>
      {spinning ? <span className="dx-subchip__dot" aria-hidden /> : null}
      {chipLabel(items)}
    </button>
  )
}

export function SubagentDrawer({ items, onClose }: { items: SubagentRun[]; onClose: () => void }) {
  const rows = useMemo(() => drawerRows(items), [items])
  const [picked, setPicked] = useState<string | null>(null)
  const selected =
    picked && rows.some((row) => row.item.run_id === picked)
      ? picked
      : ((rows.find((row) => !isDone(row.item.status)) ?? rows[0])?.item.run_id ?? null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const live = useRunActivity(selected)
  const current = rows.find((row) => row.item.run_id === selected)?.item
  const waiting = !live?.text && !live?.reasoning && (live?.tools.length ?? 0) === 0 && !live?.error

  return (
    <div className="dx-drawer" role="dialog" aria-modal="true" aria-label="Subagents">
      <aside className="dx-drawer__list">
        <div className="dx-drawer__bar">
          <span>Subagents</span>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="dx-drawer__scroll">
          {rows.map((row) => {
            const on = row.item.run_id === selected
            const spinning = !isDone(row.item.status)
            return (
              <button
                key={row.item.run_id}
                type="button"
                className={`dx-subrow${row.indent ? ' dx-subrow--child' : ''}${on ? ' dx-subrow--on' : ''}`}
                onClick={() => setPicked(row.item.run_id)}
              >
                <span className="dx-subrow__top">
                  {spinning ? <span className="dx-subchip__dot" aria-hidden /> : null}
                  <span className="dx-subrow__id">{row.item.id}</span>
                  <span className="dx-subrow__status">{row.item.status}</span>
                </span>
                {row.item.description ? <span className="dx-subrow__desc">{row.item.description}</span> : null}
              </button>
            )
          })}
        </div>
      </aside>
      <section className="dx-drawer__main">
        {current ? (
          <>
            <div className="text-[11px] text-[#8a8a8a] mb-2">
              {current.id} · {streamStatus(current.status, live?.status)}
            </div>
            {waiting ? (
              <details className="mb-2 text-[#8a8a8a]" open>
                <summary className="cursor-pointer">thinking</summary>
                <p className="whitespace-pre-wrap mt-1">Working…</p>
              </details>
            ) : null}
            {live?.reasoning ? (
              <details className="mb-2 text-[#8a8a8a]" open>
                <summary className="cursor-pointer">thinking</summary>
                <p className="whitespace-pre-wrap mt-1">{live.reasoning}</p>
              </details>
            ) : null}
            {live && live.tools.length > 0 ? (
              <div className="dx-tools">
                {live.tools.map((tool) => (
                  <ToolCallCard key={tool.id} call={tool} />
                ))}
              </div>
            ) : null}
            {live?.text ? <Markdown text={live.text} /> : null}
            {current.description ? (
              <details className="mt-3 text-[#8a8a8a]">
                <summary className="cursor-pointer">task</summary>
                <p className="whitespace-pre-wrap mt-1">{current.description}</p>
              </details>
            ) : null}
            {live?.error ? <p className="text-red-400 text-xs mt-2">{live.error}</p> : null}
          </>
        ) : (
          <p className="text-[#8a8a8a]">No subagent selected.</p>
        )}
      </section>
    </div>
  )
}
