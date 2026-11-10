import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import {
  api,
  downloadAttachment,
  getUser,
  logout,
  newIdempotencyKey,
} from '../api/client'
import type {
  Attachment,
  Conversation,
  List,
  Message,
  MessageAccepted,
  Run,
} from '../api/types'
import { ToolCallCard } from '../components/ToolCallCard'
import { useRunStream } from '../hooks/useRunStream'
import { Markdown } from '../lib/Markdown'

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])
const ACCEPT = ['.pdf', '.docx', '.txt', '.md', '.csv']
const MAX_FILES = 10
const MAX_FILE_BYTES = 25 * 1024 * 1024

function sizeLabel(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function fileError(file: File) {
  const extension = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`
  if (!ACCEPT.includes(extension)) return `${file.name}: unsupported type`
  if (!file.size) return `${file.name}: empty file`
  if (file.size > MAX_FILE_BYTES) return `${file.name}: exceeds 25 MiB`
  return null
}

export function WorkspacePage() {
  const { conversationId } = useParams({ strict: false }) as { conversationId?: string }
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const user = getUser()
  const [draft, setDraft] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [error, setError] = useState('')
  const [localRun, setLocalRun] = useState<string | null>(null)
  const [pending, setPending] = useState<Message | null>(null)
  const scroller = useRef<HTMLDivElement>(null)

  const conversations = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api<List<Conversation>>('/v1/conversations'),
  })
  const detail = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => api<Conversation>(`/v1/conversations/${conversationId}`),
    enabled: !!conversationId,
    refetchInterval: (query) => (query.state.data?.active_run ? 2000 : false),
  })
  const messages = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => api<List<Message>>(`/v1/conversations/${conversationId}/messages?limit=200`),
    enabled: !!conversationId,
  })

  const runId = localRun ?? detail.data?.active_run?.id ?? null
  const live = useRunStream(runId)
  const running = !!runId && !TERMINAL.has(live?.status ?? detail.data?.active_run?.status ?? 'queued')

  useEffect(() => {
    setLocalRun(null)
    setPending(null)
    setFiles([])
    setError('')
  }, [conversationId])

  useEffect(() => {
    if (!live || !TERMINAL.has(live.status)) return
    setLocalRun(null)
    setPending(null)
    void queryClient.invalidateQueries({ queryKey: ['messages', conversationId] })
    void queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
    void queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }, [conversationId, live, queryClient])

  useEffect(() => {
    const element = scroller.current
    if (element) element.scrollTop = element.scrollHeight
  }, [messages.data?.items.length, pending, live?.text, live?.tools.length])

  const send = useMutation({
    mutationFn: async () => {
      let target = conversationId
      if (!target) {
        const created = await api<Conversation>('/v1/conversations', { method: 'POST' })
        target = created.id
      }
      const form = new FormData()
      form.append('content', draft.trim())
      for (const file of files) form.append('files', file, file.name)
      const accepted = await api<MessageAccepted>(`/v1/conversations/${target}/messages`, {
        method: 'POST',
        headers: { 'Idempotency-Key': newIdempotencyKey() },
        body: form,
      })
      return { target, accepted }
    },
    onSuccess: ({ target, accepted }) => {
      const attachments: Attachment[] = files.map((file, index) => ({
        id: `pending-${index}`,
        filename: file.name,
        content_type: file.type,
        size_bytes: file.size,
      }))
      setPending({
        id: accepted.message_id,
        conversation_id: target,
        run_id: accepted.run_id,
        role: 'user',
        content: draft.trim(),
        attachments,
        created_at: new Date().toISOString(),
      })
      setDraft('')
      setFiles([])
      setLocalRun(accepted.run_id)
      setError('')
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
      if (target !== conversationId) {
        navigate({ to: '/c/$conversationId', params: { conversationId: target } })
      } else {
        void queryClient.invalidateQueries({ queryKey: ['messages', target] })
        void queryClient.invalidateQueries({ queryKey: ['conversation', target] })
      }
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : 'Send failed.'),
  })

  const cancel = useMutation({
    mutationFn: (id: string) => api<Run>(`/v1/runs/${id}/cancel`, { method: 'POST' }),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api(`/v1/conversations/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
      navigate({ to: '/' })
    },
  })

  const shown = useMemo(() => {
    const items = [...(messages.data?.items ?? [])]
    if (pending && !items.some((item) => item.id === pending.id)) items.push(pending)
    return items
  }, [messages.data?.items, pending])

  function addFiles(incoming: File[]) {
    const next = [...files]
    for (const file of incoming) {
      const problem = fileError(file)
      if (problem) {
        setError(problem)
        continue
      }
      if (next.length >= MAX_FILES) {
        setError(`At most ${MAX_FILES} files are allowed.`)
        break
      }
      if (!next.some((item) => item.name === file.name && item.size === file.size)) next.push(file)
    }
    setFiles(next)
  }

  function submit() {
    if (send.isPending || running || (!draft.trim() && !files.length)) return
    send.mutate()
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="h-full flex">
      <aside className="w-60 border-r border-[#2a2a2a] bg-[#141414] flex flex-col">
        <div className="h-10 px-3 flex items-center border-b border-[#2a2a2a] text-xs text-[#8a8a8a] truncate">
          {user?.email}
        </div>
        <button
          className="mx-2 mt-2 border border-[#2a2a2a] px-2 py-1 text-left hover:bg-[#1c1c1c]"
          onClick={() => navigate({ to: '/' })}
        >
          New research
        </button>
        <div className="flex-1 overflow-y-auto px-1 py-2">
          {(conversations.data?.items ?? []).map((conversation) => (
            <Link
              key={conversation.id}
              to="/c/$conversationId"
              params={{ conversationId: conversation.id }}
              className={`block px-2 py-1.5 truncate hover:bg-[#1c1c1c] ${
                conversation.id === conversationId ? 'bg-[#1c1c1c]' : ''
              }`}
            >
              {conversation.title}
            </Link>
          ))}
        </div>
        <button
          className="h-9 text-[#8a8a8a] border-t border-[#2a2a2a]"
          onClick={() => void logout().finally(() => location.assign('/login'))}
        >
          Sign out
        </button>
      </aside>

      <main className="flex-1 min-w-0 flex flex-col">
        <header className="h-10 px-4 border-b border-[#2a2a2a] flex items-center justify-between text-xs text-[#8a8a8a]">
          <span className="truncate">{detail.data?.title ?? 'New research'}</span>
          {conversationId && (
            <button className="hover:text-red-400" onClick={() => remove.mutate(conversationId)}>
              Delete
            </button>
          )}
        </header>

        <div ref={scroller} className="flex-1 overflow-y-auto px-6 py-4">
          <div className="max-w-3xl mx-auto space-y-5">
            {!shown.length && !runId && (
              <p className="text-[#8a8a8a] pt-16">Ask a research question. Cmd+Enter to send.</p>
            )}
            {shown.map((message) => (
              <article key={message.id}>
                <div className="text-[11px] text-[#8a8a8a] mb-1">{message.role}</div>
                {message.attachments.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-2">
                    {message.attachments.map((attachment) => (
                      <button
                        key={attachment.id}
                        className="dx-filechip"
                        disabled={attachment.id.startsWith('pending-')}
                        onClick={() => void downloadAttachment(attachment.id, attachment.filename)}
                      >
                        {attachment.filename}
                        <span className="dx-filechip__size">{sizeLabel(attachment.size_bytes)}</span>
                      </button>
                    ))}
                  </div>
                )}
                {message.role === 'assistant' ? (
                  <Markdown text={message.content} />
                ) : (
                  <p className="whitespace-pre-wrap">{message.content}</p>
                )}
              </article>
            ))}
            {runId && live && !shown.some((message) => message.role === 'assistant' && message.run_id === runId) && (
              <article>
                <div className="text-[11px] text-[#8a8a8a] mb-1">assistant</div>
                {!live.text && !live.error && <p className="text-[#8a8a8a]">{live.note || 'Queued…'}</p>}
                {live.subtasks.length > 0 && (
                  <div className="text-xs text-[#8a8a8a] mb-2">
                    {live.subtasks.map((task) => (
                      <div key={task.id}>{task.status} · {task.description}</div>
                    ))}
                  </div>
                )}
                {live.tools.length > 0 && (
                  <div className="dx-tools">
                    {live.tools.map((tool) => <ToolCallCard key={tool.id} call={tool} />)}
                  </div>
                )}
                {live.text && <Markdown text={live.text} />}
                {live.error && <p className="text-red-400 text-xs mt-2">{live.error}</p>}
              </article>
            )}
          </div>
        </div>

        <div className="border-t border-[#2a2a2a] p-3">
          <div className="max-w-3xl mx-auto border border-[#2a2a2a] bg-[#141414]">
            {files.length > 0 && (
              <div className="px-3 pt-2 flex flex-wrap gap-1">
                {files.map((file, index) => (
                  <button
                    key={`${file.name}-${file.size}`}
                    className="dx-filechip"
                    onClick={() => setFiles((current) => current.filter((_, item) => item !== index))}
                  >
                    {file.name} <span className="dx-filechip__size">{sizeLabel(file.size)}</span> ×
                  </button>
                ))}
              </div>
            )}
            {error && <p className="px-3 pt-2 text-red-400 text-xs">{error}</p>}
            <textarea
              className="w-full bg-transparent px-3 py-2 outline-none min-h-[72px]"
              placeholder="Research question, optionally with PDF, DOCX, or text files"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={keyDown}
              disabled={running || send.isPending}
            />
            <div className="flex items-center gap-2 px-2 pb-2">
              <input
                className="min-w-0 flex-1 text-[11px] text-[#8a8a8a]"
                type="file"
                multiple
                accept={ACCEPT.join(',')}
                disabled={running || send.isPending}
                onChange={(event) => {
                  addFiles(Array.from(event.target.files ?? []))
                  event.target.value = ''
                }}
              />
              {running && runId ? (
                <button className="border border-[#2a2a2a] px-2 py-0.5" onClick={() => cancel.mutate(runId)}>
                  Stop
                </button>
              ) : (
                <button
                  className="border border-[#2a2a2a] px-2 py-0.5 disabled:opacity-40"
                  disabled={send.isPending || (!draft.trim() && !files.length)}
                  onClick={submit}
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
