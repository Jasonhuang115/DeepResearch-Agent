import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { api, clearSession, getUser, newIdempotencyKey } from '../api/client'
import type { Conversation, List, Message, Run } from '../api/types'
import { useRunStream } from '../hooks/useRunStream'
import { Markdown } from '../lib/Markdown'

export function WorkspacePage() {
  const { conversationId } = useParams({ strict: false }) as { conversationId?: string }
  const nav = useNavigate()
  const qc = useQueryClient()
  const user = getUser()
  const [collapsed, setCollapsed] = useState(false)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<{ tempId: string; content: string } | null>(null)

  const convs = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api<List<Conversation>>('/v1/conversations'),
  })

  const detail = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => api<Conversation>(`/v1/conversations/${conversationId}`),
    enabled: !!conversationId,
  })

  const messages = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => api<List<Message>>(`/v1/conversations/${conversationId}/messages?limit=100`),
    enabled: !!conversationId,
  })

  const activeRunId = detail.data?.active_run?.id ?? null
  const live = useRunStream(activeRunId, !!activeRunId)
  const liveDone = live && ['succeeded', 'failed', 'cancelled'].includes(live.status)

  useEffect(() => {
    if (liveDone) {
      void qc.invalidateQueries({ queryKey: ['messages', conversationId] })
      void qc.invalidateQueries({ queryKey: ['conversation', conversationId] })
      void qc.invalidateQueries({ queryKey: ['conversations'] })
    }
  }, [liveDone, conversationId, qc])

  const send = useMutation({
    mutationFn: async (content: string) => {
      const key = newIdempotencyKey()
      if (!conversationId) {
        const out = await api<{ conversation: Conversation; message: Message; run: Run }>(
          '/v1/conversations',
          { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify({ content }) },
        )
        return out
      }
      const out = await api<{ message: Message; run: Run }>(`/v1/conversations/${conversationId}/messages`, {
        method: 'POST',
        headers: { 'Idempotency-Key': key },
        body: JSON.stringify({ content }),
      })
      return { ...out, conversation: { id: conversationId } as Conversation }
    },
    onSuccess: async (out) => {
      setPending(null)
      await qc.invalidateQueries({ queryKey: ['conversations'] })
      if (!conversationId || conversationId !== out.conversation.id) {
        nav({ to: '/c/$conversationId', params: { conversationId: out.conversation.id } })
      } else {
        await qc.invalidateQueries({ queryKey: ['conversation', conversationId] })
        await qc.invalidateQueries({ queryKey: ['messages', conversationId] })
      }
    },
    onError: () => setPending(null),
  })

  const cancel = useMutation({
    mutationFn: (runId: string) => api(`/v1/runs/${runId}/cancel`, { method: 'POST' }),
  })

  function submit() {
    const content = draft.trim()
    if (!content || send.isPending) return
    setPending({ tempId: `tmp-${Date.now()}`, content })
    setDraft('')
    send.mutate(content)
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      submit()
    }
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault()
      document.getElementById('conv-search')?.focus()
    }
  }

  const history = messages.data?.items ?? []
  const shown = useMemo(() => {
    const rows = [...history]
    if (pending && !rows.some((m) => m.content === pending.content && m.role === 'user')) {
      rows.push({
        id: pending.tempId,
        conversation_id: conversationId || '',
        role: 'user',
        content: pending.content,
        created_at: new Date().toISOString(),
      })
    }
    return rows
  }, [history, pending, conversationId])

  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' })
  }, [shown.length, live?.text])

  const running = !!activeRunId && !liveDone

  return (
    <div className="h-full flex">
      <aside className={`border-r border-[#2a2a2a] bg-[#141414] flex flex-col ${collapsed ? 'w-12' : 'w-60'}`}>
        <div className="h-10 px-2 flex items-center justify-between border-b border-[#2a2a2a]">
          {!collapsed && <span className="text-xs text-[#8a8a8a] truncate">{user?.display_name}</span>}
          <button className="text-[#8a8a8a] px-1" onClick={() => setCollapsed((v) => !v)} title="Toggle sidebar">
            {collapsed ? '›' : '‹'}
          </button>
        </div>
        {!collapsed && (
          <>
            <button
              className="mx-2 mt-2 mb-1 border border-[#2a2a2a] px-2 py-1 text-left hover:bg-[#1c1c1c]"
              onClick={() => nav({ to: '/' })}
            >
              New research
            </button>
            <div className="flex-1 overflow-y-auto px-1">
              {(convs.data?.items ?? []).map((c) => (
                <Link
                  key={c.id}
                  to="/c/$conversationId"
                  params={{ conversationId: c.id }}
                  className={`block px-2 py-1.5 truncate hover:bg-[#1c1c1c] ${
                    c.id === conversationId ? 'bg-[#1c1c1c]' : ''
                  }`}
                >
                  {c.title}
                </Link>
              ))}
            </div>
            <button
              className="h-9 text-[#8a8a8a] border-t border-[#2a2a2a]"
              onClick={() => {
                clearSession()
                location.assign('/login')
              }}
            >
              Sign out
            </button>
          </>
        )}
      </aside>

      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-10 px-4 border-b border-[#2a2a2a] flex items-center text-[#8a8a8a] text-xs">
          {detail.data?.title || 'New thread'}
          {running && <span className="ml-3">running</span>}
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="max-w-3xl mx-auto space-y-5">
            {shown.length === 0 && !pending && (
              <p className="text-[#8a8a8a] pt-16">Ask a research question. Cmd+Enter to send.</p>
            )}
            {shown.map((m) => (
              <article key={m.id}>
                <div className="text-[11px] text-[#8a8a8a] mb-1">{m.role}</div>
                {m.role === 'assistant' ? <Markdown text={m.content} /> : <p className="whitespace-pre-wrap">{m.content}</p>}
              </article>
            ))}
            {running && live && !shown.some((m) => m.role === 'assistant' && m.run_id === activeRunId) && (
              <article>
                <div className="text-[11px] text-[#8a8a8a] mb-1">assistant</div>
                {live.reasoning && (
                  <details className="mb-2 text-[#8a8a8a]" open>
                    <summary className="cursor-pointer">thinking</summary>
                    <p className="whitespace-pre-wrap mt-1">{live.reasoning}</p>
                  </details>
                )}
                {live.tools.map((t) => (
                  <div key={t.id} className="text-[#8a8a8a] text-xs mb-1">
                    {t.done ? 'tool' : 'calling'} {t.name}
                    {t.summary ? ` — ${t.summary}` : ''}
                  </div>
                ))}
                {live.text && <Markdown text={live.text} />}
                {live.error && <p className="text-red-400 text-xs mt-2">{live.error}</p>}
              </article>
            )}
            <div ref={end} />
          </div>
        </div>

        <div className="border-t border-[#2a2a2a] p-3">
          <div className="max-w-3xl mx-auto border border-[#2a2a2a] bg-[#141414]">
            <textarea
              className="w-full bg-transparent px-3 py-2 outline-none min-h-[72px]"
              placeholder="Research question"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              disabled={running || send.isPending}
            />
            <div className="flex justify-between items-center px-2 pb-2 text-[#8a8a8a] text-xs">
              <span>Cmd+Enter send</span>
              {running && activeRunId ? (
                <button onClick={() => cancel.mutate(activeRunId)} className="border border-[#2a2a2a] px-2 py-0.5">
                  Stop
                </button>
              ) : (
                <button
                  onClick={submit}
                  disabled={!draft.trim() || send.isPending}
                  className="border border-[#2a2a2a] px-2 py-0.5 disabled:opacity-40"
                >
                  Send
                </button>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
