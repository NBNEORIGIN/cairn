'use client'

/**
 * BriefingView — Deek's morning read.
 *
 * Shows the most recent pending briefing + the live on-demand briefing
 * (refreshable). Tasks are listed with tap-to-done actions.
 */
import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react'
import type { VoiceLoopTurn } from '@/hooks/useVoiceLoop'

interface Task {
  id: number
  assignee: string
  content: string
  status: string
  source: string
  due_at: string | null
  title: string | null
  priority: string | null
  context: string | null
  linked_module: string | null
  linked_ref: string | null
}

interface BriefingResponse {
  user: string
  display_name: string | null
  role_tag: string | null
  generated_at: string
  briefing_md: string
  open_tasks: Task[]
  stale_snapshots: string[]
}

interface PendingBriefing {
  id: number
  email: string
  generated_at: string
  briefing_md: string
  seen_at: string | null
  dismissed_at: string | null
  incorrect_reason: string | null
}

export function BriefingView({
  onTasksChanged,
}: {
  onTasksChanged?: () => void
}) {
  const [liveBriefing, setLiveBriefing] = useState<BriefingResponse | null>(null)
  const [pending, setPending] = useState<PendingBriefing[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [bRes, pRes] = await Promise.all([
        fetch('/api/voice/briefing', { cache: 'no-store' }),
        fetch('/api/voice/briefings/pending', { cache: 'no-store' }),
      ])
      if (bRes.ok) {
        setLiveBriefing(await bRes.json())
      } else if (bRes.status === 401) {
        window.location.href = '/voice/login?callbackUrl=/voice'
        return
      } else {
        setError(`Briefing failed: HTTP ${bRes.status}`)
      }
      if (pRes.ok) {
        const data = await pRes.json()
        // Mark the latest as seen when the user opens this view
        setPending(data.items || [])
        const unseen = (data.items || []).find((i: PendingBriefing) => !i.seen_at)
        if (unseen) {
          fetch(`/api/voice/briefings/${unseen.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'seen' }),
          })
        }
      }
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const markDone = useCallback(
    async (taskId: number) => {
      setActionBusy(taskId)
      try {
        const res = await fetch(`/api/voice/tasks/${taskId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'done' }),
        })
        if (res.ok) {
          // Remove from the local list
          setLiveBriefing(b =>
            b ? { ...b, open_tasks: b.open_tasks.filter(t => t.id !== taskId) } : b
          )
          onTasksChanged?.()
        }
      } finally {
        setActionBusy(null)
      }
    },
    [onTasksChanged]
  )

  const markIncorrect = useCallback(async (briefingId: number) => {
    const reason = prompt(
      'What was wrong with this briefing? (Optional — leave blank to just flag it)'
    )
    if (reason === null) return
    await fetch(`/api/voice/briefings/${briefingId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'incorrect',
        incorrect_reason: reason || '(no reason given)',
      }),
    })
    alert('Thanks — flagged. Toby will review.')
  }, [])

  if (loading && !liveBriefing) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-950 text-slate-500">
        Loading briefing…
      </div>
    )
  }

  const latestPending = pending.find(p => !p.dismissed_at)

  return (
    <div className="h-full overflow-y-auto bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-2xl space-y-6 px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="text-xs uppercase tracking-wider text-slate-500">
            {liveBriefing?.role_tag
              ? `${liveBriefing.role_tag} briefing`
              : 'Briefing'}
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1 rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-slate-500 disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="rounded-lg bg-rose-950/60 px-3 py-2 text-sm text-rose-200">
            {error}
          </div>
        )}

        {/* Most recent pending briefing (if distinct from live) */}
        {latestPending && (
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
              <span>
                Delivered{' '}
                {new Date(latestPending.generated_at).toLocaleString('en-GB', {
                  weekday: 'short',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
              <button
                onClick={() => markIncorrect(latestPending.id)}
                className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300"
                title="Flag as incorrect"
              >
                <AlertTriangle size={12} />
                Flag
              </button>
            </div>
            <MarkdownBlock md={latestPending.briefing_md} />
          </div>
        )}

        {/* Live on-demand briefing (fresh snapshot) */}
        {liveBriefing && (
          <div className="rounded-2xl border border-emerald-900/60 bg-emerald-950/20 p-4">
            <div className="mb-2 text-xs text-emerald-400">
              Live — generated just now
            </div>
            <MarkdownBlock md={liveBriefing.briefing_md} />

            {liveBriefing.open_tasks.length > 0 && (
              <div className="mt-4 space-y-2">
                <div className="text-xs uppercase tracking-wider text-slate-500">
                  Your tasks
                </div>
                {liveBriefing.open_tasks.map(t => (
                  <div
                    key={t.id}
                    className="flex items-start justify-between gap-3 rounded-lg bg-slate-900 px-3 py-2 text-sm"
                  >
                    <div className="flex-1">
                      {t.priority && (
                        <span
                          className={`mr-2 inline-block rounded-full px-1.5 py-0.5 text-[10px] uppercase ${
                            t.priority === 'critical'
                              ? 'bg-rose-900 text-rose-200'
                              : t.priority === 'high'
                              ? 'bg-amber-900 text-amber-200'
                              : 'bg-slate-800 text-slate-300'
                          }`}
                        >
                          {t.priority}
                        </span>
                      )}
                      {t.title || t.content}
                      {t.due_at && (
                        <div className="mt-0.5 text-xs text-slate-500">
                          Due {new Date(t.due_at).toLocaleDateString('en-GB')}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => markDone(t.id)}
                      disabled={actionBusy === t.id}
                      className="flex items-center gap-1 rounded-md bg-emerald-700 px-2 py-1 text-xs text-white hover:bg-emerald-600 disabled:opacity-50"
                    >
                      <CheckCircle2 size={12} />
                      Done
                    </button>
                  </div>
                ))}
              </div>
            )}

            {liveBriefing.stale_snapshots.length > 0 && (
              <div className="mt-4 rounded-md bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
                ⚠ Snapshot data for {liveBriefing.stale_snapshots.join(', ')} is
                older than 2h — figures may be out of date.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function MarkdownBlock({ md }: { md: string }) {
  // Lightweight markdown rendering — just handle headings, bold, bullet
  // lists. Good enough for briefings (no tables or code).
  const html = md
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/^## (.+)$/gm, '<h3 class="text-base font-semibold mt-2 mb-1 text-slate-100">$1</h3>')
    .replace(/^# (.+)$/gm, '<h2 class="text-lg font-semibold mt-3 mb-2 text-slate-50">$1</h2>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="text-slate-100">$1</strong>')
    .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc text-slate-200">$1</li>')
    .replace(/\n\n/g, '</p><p class="my-2">')
    .replace(/\n/g, '<br/>')
  return (
    <div
      className="prose-invert text-sm leading-relaxed text-slate-300"
      dangerouslySetInnerHTML={{ __html: `<p class="my-1">${html}</p>` }}
    />
  )
}
