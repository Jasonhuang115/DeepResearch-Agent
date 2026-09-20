import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { api, clearSession, getUser, newIdempotencyKey } from '../api/client'
import type { Conversation, List, Message, Run } from '../api/types'
import { ToolCallCard } from '../components/ToolCallCard'
import { useRunStream, type Live } from '../hooks/useRunStream'
import { Markdown } from '../lib/Markdown'
import { fetchRunTrace, mergeTrace, type Trace } from '../lib/trace'

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])
const ACCEPT_EXT = ['.pdf', '.docx', '.txt', '.md', '.csv']
const MAX_FILES = 5
const MAX_BYTES = 20 * 1024 * 1024

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`
  return `${(n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`
}

function seedMessage(qc: ReturnType<typeof useQueryClient>, conversationId: string, message: Message) {
  qc.setQueryData<List<Message>>(['messages', conversationId], (old) => {
    const items = old?.items ?? []
    const next = items.some((m) => m.id === message.id)
      ? items.map((m) => (m.id === message.id ? { ...m, ...message } : m))
      : [...items, message]
    return { items: next, next_before: old?.next_before ?? null }
  })
}

function rejectReason(f: File): string | null {
  const ext = `.${(f.name.split('.').pop() || '').toLowerCase()}`
  if (ext === '.doc') return `${f.name}: 请另存为 .docx 后再上传`
  if (['.png', '.jpg', '.jpeg', '.webp', '.gif', '.heic', '.bmp'].includes(ext)) {
    return `${f.name}: 暂不支持图片，请上传 PDF 或 Word`
  }
  if (['.xls', '.xlsx', '.ppt', '.pptx'].includes(ext)) {
    return `${f.name}: 暂不支持表格/PPT，请导出为 PDF`
  }
  if (!ACCEPT_EXT.includes(ext)) return `${f.name}: 仅支持 PDF、DOCX、TXT、MD、CSV`
  if (f.size === 0) return `${f.name}: 文件是空的`
  if (f.size > MAX_BYTES) return `${f.name}: 超过 20MB`
  return null
}

function explainSendError(err: unknown) {
  const e = err as Error & { status?: number }
  const msg = e?.message || '发送失败'
  if (e?.status === 409 || msg.includes('already active')) return '请等当前研究完成后再发送'
  if (e?.status === 404 || msg === 'not found') return '当前对话不可用，请点左侧 New research 开新对话'
  return msg
}

function mergeFiles(cur: File[], incoming: File[]): { next: File[]; errors: string[] } {
  const next = [...cur]
  const errors: string[] = []
  for (const f of incoming) {
    const why = rejectReason(f)
    if (why) {
      errors.push(why)
      continue
    }
    if (next.length >= MAX_FILES) {
      errors.push(`一次最多 ${MAX_FILES} 个文件`)
      break
    }
    if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f)
  }
  return { next, errors }
}

export function WorkspacePage() {
  const { conversationId } = useParams({ strict: false }) as { conversationId?: string }
  const nav = useNavigate()
  const qc = useQueryClient()
  const user = getUser()
  const [collapsed, setCollapsed] = useState(false)
  const [draft, setDraft] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const filesRef = useRef<File[]>([])
  filesRef.current = files
  const scroller = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)
  const [attachError, setAttachError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [pending, setPending] = useState<{
    tempId: string
    content: string
    attachments?: { filename: string; size: number }[]
  } | null>(null)
  const [localRun, setLocalRun] = useState<{ id: string; conversationId: string } | null>(null)
  const [held, setHeld] = useState<Live | null>(null)
  const [traces, setTraces] = useState<Record<string, Trace>>({})
  const tracesRef = useRef(traces)
  tracesRef.current = traces
  const hydratedRuns = useRef(new Set<string>())

  const convs = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api<List<Conversation>>('/v1/conversations'),
  })

  const detail = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => api<Conversation>(`/v1/conversations/${conversationId}`),
    enabled: !!conversationId,
    refetchInterval: (q) => (q.state.data?.active_run ? 2000 : false),
  })

  const messages = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => api<List<Message>>(`/v1/conversations/${conversationId}/messages?limit=100`),
    enabled: !!conversationId,
    refetchInterval: () => (detail.data?.active_run ? 2000 : false),
  })

  const activeRunId = detail.data?.active_run?.id ?? null
  const runId =
    localRun && conversationId && localRun.conversationId === conversationId ? localRun.id : activeRunId
  const live = useRunStream(runId, !!runId)
  const liveDone = live && TERMINAL.has(live.status)

  useEffect(() => {
    setHeld(null)
    setFiles([])
    setAttachError(null)
    setDragging(false)
    stickToBottom.current = true
  }, [conversationId])

  useEffect(() => {
    if (live) setHeld(live)
  }, [live])

  useEffect(() => {
    if (liveDone) {
      void qc.invalidateQueries({ queryKey: ['messages', conversationId] })
      void qc.invalidateQueries({ queryKey: ['conversation', conversationId] })
      void qc.invalidateQueries({ queryKey: ['conversations'] })
    }
  }, [liveDone, conversationId, qc])

  const send = useMutation({
    mutationFn: async (input: { content: string; files: File[] }) => {
      const key = newIdempotencyKey()
      const { content, files: attached } = input
      const headers: HeadersInit = { 'Idempotency-Key': key }
      const body: BodyInit =
        attached.length > 0
          ? (() => {
              const fd = new FormData()
              fd.append('content', content)
              for (const f of attached) fd.append('files', f, f.name)
              return fd
            })()
          : JSON.stringify({ content })
      if (!conversationId) {
        const out = await api<{ conversation: Conversation; message: Message; run: Run }>(
          '/v1/conversations',
          { method: 'POST', headers, body },
        )
        return out
      }
      const out = await api<{ message: Message; run: Run }>(`/v1/conversations/${conversationId}/messages`, {
        method: 'POST',
        headers,
        body,
      })
      return { ...out, conversation: { id: conversationId } as Conversation }
    },
    onSuccess: (out) => {
      setAttachError(null)
      if (out.message) seedMessage(qc, out.conversation.id, out.message)
      setPending(null)
      setLocalRun({ id: out.run.id, conversationId: out.conversation.id })
      void qc.invalidateQueries({ queryKey: ['conversations'] })
      if (!conversationId || conversationId !== out.conversation.id) {
        nav({ to: '/c/$conversationId', params: { conversationId: out.conversation.id } })
      } else {
        void qc.invalidateQueries({ queryKey: ['conversation', conversationId] })
        void qc.invalidateQueries({ queryKey: ['messages', conversationId] })
      }
    },
  })

  const cancel = useMutation({
    mutationFn: (runId: string) => api(`/v1/runs/${runId}/cancel`, { method: 'POST' }),
  })

  function submit() {
    const content = draft.trim()
    if ((!content && files.length === 0) || send.isPending) return
    const attached = files
    setPending({
      tempId: `tmp-${Date.now()}`,
      content,
      attachments: attached.map((f) => ({ filename: f.name, size: f.size })),
    })
    setDraft('')
    setFiles([])
    setAttachError(null)
    stickToBottom.current = true
    send.mutate(
      { content, files: attached },
      {
        onError: (err) => {
          setDraft(content)
          setFiles(attached)
          setPending(null)
          setAttachError(explainSendError(err))
        },
      },
    )
  }

  function addFiles(picked: ArrayLike<File> | null | undefined) {
    const incoming = picked ? Array.from(picked) : []
    if (incoming.length === 0) return
    const { next, errors } = mergeFiles(filesRef.current, incoming)
    filesRef.current = next
    setFiles(next)
    setAttachError(errors[0] ?? null)
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

  const history = conversationId ? (messages.data?.items ?? []) : []
  const shown = useMemo(() => {
    const rows = [...history]
    if (pending && !rows.some((m) => m.id === pending.tempId)) {
      rows.push({
        id: pending.tempId,
        conversation_id: conversationId || '',
        role: 'user',
        content: pending.content,
        attachments: pending.attachments?.map((a, i) => ({
          id: `tmp-${i}`,
          filename: a.filename,
          content_type: '',
          size: a.size,
        })),
        created_at: new Date().toISOString(),
      })
    }
    return rows
  }, [history, pending, conversationId])

  const display = live ?? held
  const historyHasLive = !!display && shown.some((m) => m.role === 'assistant' && m.run_id === display.runId)
  const showLive = !!runId && !!display && display.runId === runId && !historyHasLive
  const active = showLive && !TERMINAL.has(display?.status ?? '')
  const lastAssistantId = [...shown].reverse().find((m) => m.role === 'assistant')?.id

  useEffect(() => {
    if (!display?.runId) return
    if (!display.reasoning && display.tools.length === 0) return
    setTraces((cur) => ({
      ...cur,
      [display.runId]: mergeTrace(cur[display.runId], { reasoning: display.reasoning, tools: display.tools }),
    }))
  }, [display])

  useEffect(() => {
    const ids = [
      ...new Set(shown.filter((m) => m.role === 'assistant' && m.run_id).map((m) => m.run_id as string)),
    ]
    let cancelled = false
    for (const id of ids) {
      const have = tracesRef.current[id]
      if (hydratedRuns.current.has(id)) continue
      if (have && (have.reasoning || have.tools.length > 0)) {
        hydratedRuns.current.add(id)
        continue
      }
      hydratedRuns.current.add(id)
      void fetchRunTrace(id)
        .then((trace) => {
          if (cancelled) return
          if (!trace.reasoning && trace.tools.length === 0) return
          setTraces((cur) => ({ ...cur, [id]: mergeTrace(cur[id], trace) }))
        })
        .catch(() => {
          hydratedRuns.current.delete(id)
        })
    }
    return () => {
      cancelled = true
    }
  }, [shown])

  useEffect(() => {
    if (historyHasLive) {
      setHeld(null)
      if (localRun && display?.runId === localRun.id) setLocalRun(null)
    }
  }, [historyHasLive, localRun, display?.runId])

  function pinIfNearBottom() {
    const el = scroller.current
    if (!el) return
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96
  }

  useEffect(() => {
    const el = scroller.current
    if (!el || !stickToBottom.current) return
    el.scrollTop = el.scrollHeight
  }, [shown.length, display?.text, display?.reasoning, display?.note, display?.tools.length])

  const running = active || send.isPending

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
              onClick={() => {
                setDraft('')
                setFiles([])
                setPending(null)
                nav({ to: '/' })
              }}
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
        <header className="h-10 px-4 border-b border-[#2a2a2a] flex items-center justify-between gap-3 text-[#8a8a8a] text-xs">
          <div className="min-w-0 flex items-center">
            <span className="truncate">{conversationId ? detail.data?.title || 'New thread' : 'New thread'}</span>
            {running && <span className="ml-3 shrink-0">running</span>}
          </div>
          <button
            className="shrink-0 w-7 h-7 border border-[#2a2a2a] hover:bg-[#1c1c1c] text-base leading-none"
            title="New research"
            onClick={() => {
              setDraft('')
              setFiles([])
              setPending(null)
              nav({ to: '/' })
            }}
          >
            +
          </button>
        </header>

        <div
          ref={scroller}
          className="flex-1 overflow-y-auto px-6 py-4 overscroll-contain [overflow-anchor:none]"
          onScroll={pinIfNearBottom}
          onWheel={(e) => {
            if (e.deltaY < 0) stickToBottom.current = false
            else requestAnimationFrame(pinIfNearBottom)
          }}
        >
          <div className="max-w-3xl mx-auto space-y-5">
            {conversationId && detail.isError && (
              <div className="border border-red-900 bg-[#1a1010] px-3 py-2 text-[12px] text-red-400">
                找不到这个对话（可能属于别的账号）。
                <button className="ml-2 underline" onClick={() => nav({ to: '/' })}>
                  开始新研究
                </button>
              </div>
            )}
            {shown.length === 0 && !pending && !detail.isError && (
              <p className="text-[#8a8a8a] pt-16">Ask a research question. Cmd+Enter to send.</p>
            )}
            {shown.map((m) => {
              const trace = m.run_id ? traces[m.run_id] : undefined
              const hideBody = showLive && display?.runId === m.run_id && m.role === 'assistant'
              if (hideBody) return null
              return (
                <article key={m.id}>
                  <div className="text-[11px] text-[#8a8a8a] mb-1">{m.role}</div>
                  {m.role === 'assistant' ? (
                    <>
                      <TraceBlock
                        reasoning={trace?.reasoning ?? ''}
                        tools={trace?.tools ?? []}
                        open={m.id === lastAssistantId}
                      />
                      <Markdown text={m.content} />
                    </>
                  ) : (
                    <>
                      <FileChips items={m.attachments} />
                      {m.content ? <p className="whitespace-pre-wrap">{m.content}</p> : null}
                    </>
                  )}
                </article>
              )
            })}
            {showLive && display && <LivePane live={display} />}
          </div>
        </div>

        <div className="border-t border-[#2a2a2a] p-3">
          <div
            className={`max-w-3xl mx-auto border bg-[#141414] ${dragging ? 'border-[#8a8a8a]' : 'border-[#2a2a2a]'}`}
            onDragEnter={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false)
            }}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              addFiles(Array.from(e.dataTransfer.files ?? []))
            }}
            onPaste={(e) => {
              if (e.clipboardData?.files?.length) addFiles(Array.from(e.clipboardData.files))
            }}
          >
            {files.length > 0 && (
              <div className="px-3 pt-2 flex flex-wrap gap-1">
                {files.map((f, i) => (
                  <button
                    key={`${f.name}-${i}`}
                    type="button"
                    className="dx-filechip"
                    onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))}
                    title="Remove"
                  >
                    {f.name}
                    <span className="dx-filechip__size">{formatBytes(f.size)}</span>
                    <span aria-hidden> ×</span>
                  </button>
                ))}
              </div>
            )}
            {(attachError || send.isError) && (
              <p className="px-3 pt-2 text-[11px] text-red-400">
                {attachError || explainSendError(send.error)}
              </p>
            )}
            <textarea
              className="w-full bg-transparent px-3 py-2 outline-none min-h-[72px]"
              placeholder={dragging ? '松开即可添加文件' : '研究问题，可同时附带 PDF / DOCX / 文本'}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              onPaste={(e) => {
                if (e.clipboardData?.files?.length) addFiles(Array.from(e.clipboardData.files))
              }}
              disabled={running || send.isPending || detail.isError}
            />
            <div className="flex items-center gap-2 px-2 pb-2">
              <input
                type="file"
                multiple
                accept=".pdf,.docx,.txt,.md,.csv"
                disabled={send.isPending || detail.isError}
                className="min-w-0 flex-1 text-[11px] text-[#8a8a8a] file:mr-2 file:border file:border-[#2a2a2a] file:bg-[#1c1c1c] file:px-2 file:py-0.5 file:text-[#e8e8e8] file:cursor-pointer"
                onChange={(e) => {
                  addFiles(Array.from(e.target.files ?? []))
                  e.target.value = ''
                }}
              />
              {running && runId ? (
                <button onClick={() => cancel.mutate(runId)} className="shrink-0 border border-[#2a2a2a] px-2 py-0.5 text-xs">
                  Stop
                </button>
              ) : (
                <button
                  onClick={submit}
                  disabled={(!draft.trim() && files.length === 0) || send.isPending || detail.isError}
                  className="shrink-0 border border-[#2a2a2a] px-2 py-0.5 text-xs disabled:opacity-40"
                >
                  {send.isPending ? 'Sending…' : 'Send'}
                </button>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}

function FileChips({ items }: { items?: { filename: string; size?: number }[] }) {
  if (!items || items.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1 mb-1">
      {items.map((a, i) => (
        <span key={`${a.filename}-${i}`} className="dx-filechip dx-filechip--static" title={a.filename}>
          {a.filename}
          {a.size ? <span className="dx-filechip__size">{formatBytes(a.size)}</span> : null}
        </span>
      ))}
    </div>
  )
}

function TraceBlock({
  reasoning,
  tools,
  open,
}: {
  reasoning: string
  tools: Live['tools']
  open: boolean
}) {
  if (!reasoning && tools.length === 0) return null
  return (
    <>
      {reasoning && (
        <details className="mb-2 text-[#8a8a8a]" {...(open ? { open: true } : {})}>
          <summary className="cursor-pointer">thinking</summary>
          <p className="whitespace-pre-wrap mt-1">{reasoning}</p>
        </details>
      )}
      {tools.length > 0 && (
        <div className="dx-tools">
          {tools.map((t) => (
            <ToolCallCard key={t.id} call={t} />
          ))}
        </div>
      )}
    </>
  )
}

function LivePane({ live }: { live: Live }) {
  const waiting = !live.text && !live.reasoning && live.tools.length === 0 && !live.error
  return (
    <article>
      <div className="text-[11px] text-[#8a8a8a] mb-1">assistant</div>
      {waiting && (
        <details className="mb-2 text-[#8a8a8a]" open>
          <summary className="cursor-pointer">thinking</summary>
          <p className="whitespace-pre-wrap mt-1">{live.note || 'Working on it…'}</p>
        </details>
      )}
      <TraceBlock reasoning={live.reasoning} tools={live.tools} open />
      {live.text && <Markdown text={live.text} />}
      {live.error && <p className="text-red-400 text-xs mt-2">{live.error}</p>}
    </article>
  )
}
