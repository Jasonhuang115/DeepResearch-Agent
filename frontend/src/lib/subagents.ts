export type SubagentRun = {
  id: string
  run_id: string
  parent_run_id: string
  parent_id: string | null
  description: string
  status: string
  depth: number
}

const DONE = new Set(['succeeded', 'failed', 'timed_out', 'cancelled'])

export function isDone(status: string) {
  return DONE.has(status)
}

export function cohortFor(items: SubagentRun[], parentRunId: string) {
  const roots = items.filter((item) => item.parent_run_id === parentRunId && !item.parent_id)
  const rootIds = new Set(roots.map((item) => item.id))
  const children = items.filter((item) => item.parent_id != null && rootIds.has(item.parent_id))
  return [...roots, ...children]
}

export function chipLabel(items: SubagentRun[]) {
  if (items.length === 1) {
    const one = items[0]
    return `${clipTask(one.description || one.id)} · ${one.status}`
  }
  const running = items.filter((item) => !isDone(item.status)).length
  return `${running} running · ${items.length - running} done`
}

export type DrawerRow = { item: SubagentRun; indent: boolean }

export function drawerRows(items: SubagentRun[]): DrawerRow[] {
  const roots = items.filter((item) => !item.parent_id || item.depth <= 1)
  const nested = new Map<string, SubagentRun[]>()
  for (const item of items) {
    if (!item.parent_id || item.depth <= 1) continue
    const list = nested.get(item.parent_id) ?? []
    list.push(item)
    nested.set(item.parent_id, list)
  }
  const ranked = [...roots].sort((a, b) => {
    const rank = familyRank(a, nested.get(a.id) ?? []) - familyRank(b, nested.get(b.id) ?? [])
    if (rank !== 0) return rank
    return a.id.localeCompare(b.id)
  })
  const rows: DrawerRow[] = []
  for (const root of ranked) {
    rows.push({ item: root, indent: false })
    for (const child of sortRuns(nested.get(root.id) ?? [])) {
      rows.push({ item: child, indent: true })
    }
  }
  return rows
}

function familyRank(root: SubagentRun, children: SubagentRun[]) {
  if (!isDone(root.status)) return 0
  if (children.some((child) => !isDone(child.status))) return 1
  return 2
}

function sortRuns(items: SubagentRun[]) {
  return [...items].sort((a, b) => {
    const rank = Number(isDone(a.status)) - Number(isDone(b.status))
    if (rank !== 0) return rank
    return a.id.localeCompare(b.id)
  })
}

function clipTask(text: string) {
  const clean = text.replace(/\s+/g, ' ').trim()
  if (clean.length <= 32) return clean
  return `${clean.slice(0, 31)}…`
}
