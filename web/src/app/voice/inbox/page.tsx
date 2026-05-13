'use client'

/**
 * /voice/inbox — Toby's active-PM pending-drafts surface.
 *
 * Phase 1 (today): shows every unreviewed triage row that has a
 * drafted reply. Each card expands to show the full original email,
 * the full draft, and three actions: edit, stage to sales@, reject.
 *
 * Designed mobile-first (Toby uses this on his phone) — single column,
 * thumb-friendly buttons, no horizontal scroll.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

interface PendingDraft {
  id: number
  email_subject: string
  email_sender: string
  email_received_at: string
  processed_at: string
  classification: string
  project_id: string | null
  draft_preview: string
  draft_length: number
  reviewed_at: string | null
  review_action: string | null
}

interface DraftDetail extends PendingDraft {
  email_body: string
  draft_reply: string
  draft_model: string
  match_candidates: any[] | null
  client_name_guess: string | null
  project_name?: string
  classification_confidence: number | null
}

function fmtTs(iso: string | null): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    const today = new Date()
    const sameDay =
      d.getFullYear() === today.getFullYear() &&
      d.getMonth() === today.getMonth() &&
      d.getDate() === today.getDate()
    if (sameDay) {
      return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    }
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
  } catch {
    return iso
  }
}

export default function InboxPage() {
  const [rows, setRows] = useState<PendingDraft[]>([])
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [includeReviewed, setIncludeReviewed] = useState(false)

  const fetchList = useCallback(async () => {
    setLoading(true)
    setErrorMsg(null)
    try {
      const res = await fetch(
        `/api/voice/inbox?limit=100&include_reviewed=${includeReviewed}`,
        { cache: 'no-store' },
      )
      if (res.status === 401) {
        window.location.href = '/voice/login?callbackUrl=/voice/inbox'
        return
      }
      const data = await res.json()
      setRows(data.rows || [])
    } catch (e: any) {
      setErrorMsg(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [includeReviewed])

  useEffect(() => {
    fetchList()
  }, [fetchList])

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950 text-slate-100">
      <header className="flex-shrink-0 border-b border-slate-800 px-4 py-3">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">Inbox</h1>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={includeReviewed}
                onChange={e => setIncludeReviewed(e.target.checked)}
                className="rounded"
              />
              show actioned
            </label>
            <button
              onClick={fetchList}
              className="rounded-md bg-slate-800 px-2 py-1 text-xs hover:bg-slate-700"
            >
              Refresh
            </button>
          </div>
        </div>
        <div className="mt-1 text-xs text-slate-500">
          {loading
            ? 'Loading…'
            : `${rows.length} drafts ${includeReviewed ? '(all)' : 'awaiting action'}`}
        </div>
      </header>

      {errorMsg && (
        <div className="mx-4 mt-2 rounded-lg bg-rose-950/60 px-3 py-2 text-xs text-rose-200">
          {errorMsg}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
        {!loading && rows.length === 0 && (
          <div className="py-16 text-center text-sm text-slate-500">
            {includeReviewed
              ? 'No drafts in the history window.'
              : 'No pending drafts. Inbox zero.'}
          </div>
        )}
        {rows.map(row => (
          <InboxCard
            key={row.id}
            row={row}
            expanded={expandedId === row.id}
            onToggle={() =>
              setExpandedId(expandedId === row.id ? null : row.id)
            }
            onActioned={fetchList}
          />
        ))}
      </div>
    </div>
  )
}

function InboxCard({
  row,
  expanded,
  onToggle,
  onActioned,
}: {
  row: PendingDraft
  expanded: boolean
  onToggle: () => void
  onActioned: () => void
}) {
  const reviewed = !!row.reviewed_at
  return (
    <div
      className={`rounded-lg border ${
        reviewed
          ? 'border-slate-800/50 bg-slate-900/50'
          : 'border-slate-700 bg-slate-900'
      }`}
    >
      <button
        onClick={onToggle}
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline justify-between gap-2">
            <div className="truncate text-sm font-medium text-slate-100">
              {row.email_sender}
            </div>
            <div className="flex-shrink-0 text-xs text-slate-500">
              {fmtTs(row.processed_at)}
            </div>
          </div>
          <div className="truncate text-xs text-slate-400 mt-0.5">
            {row.email_subject || '(no subject)'}
          </div>
          {!expanded && (
            <div className="line-clamp-2 text-xs text-slate-500 mt-1.5 italic">
              {row.draft_preview}
            </div>
          )}
        </div>
        {reviewed ? (
          <span className="flex-shrink-0 rounded-full bg-emerald-950/60 px-2 py-0.5 text-[10px] text-emerald-300">
            {row.review_action}
          </span>
        ) : (
          <span className="flex-shrink-0 rounded-full bg-amber-950/60 px-2 py-0.5 text-[10px] text-amber-300">
            pending
          </span>
        )}
      </button>
      {expanded && (
        <InboxDetail triageId={row.id} onActioned={onActioned} />
      )}
    </div>
  )
}

function InboxDetail({
  triageId,
  onActioned,
}: {
  triageId: number
  onActioned: () => void
}) {
  const [detail, setDetail] = useState<DraftDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draftEdit, setDraftEdit] = useState('')
  const [working, setWorking] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const draftRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/voice/inbox/${triageId}`, { cache: 'no-store' })
      .then(r => r.json())
      .then(d => {
        if (cancelled) return
        if (d?.error) {
          setError(d.error)
          return
        }
        setDetail(d)
        setDraftEdit(d.draft_reply || '')
      })
      .catch(e => !cancelled && setError(e?.message || String(e)))
    return () => {
      cancelled = true
    }
  }, [triageId])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 4000)
  }

  const handleSaveEdit = async () => {
    setWorking('Saving edit…')
    try {
      const res = await fetch(`/api/voice/inbox/${triageId}/edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ draft_reply: draftEdit }),
      })
      const data = await res.json()
      if (!res.ok) showToast(`Save failed: ${data?.detail || data?.error || res.status}`)
      else showToast('Edit saved')
    } catch (e: any) {
      showToast(`Save failed: ${e?.message || e}`)
    } finally {
      setWorking(null)
    }
  }

  const handleStage = async () => {
    if (!confirm(`Send this draft to sales@nbnesigns.co.uk for manual review?`)) return
    setWorking('Staging to sales@…')
    try {
      const res = await fetch(`/api/voice/inbox/${triageId}/stage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      const data = await res.json()
      if (!res.ok) showToast(`Stage failed: ${data?.detail || data?.error || res.status}`)
      else {
        showToast('Staged to sales@ ✓')
        setTimeout(onActioned, 800)
      }
    } catch (e: any) {
      showToast(`Stage failed: ${e?.message || e}`)
    } finally {
      setWorking(null)
    }
  }

  const handleReject = async () => {
    const reason = prompt('Reject reason (optional — helps training):')
    if (reason === null) return // cancelled
    setWorking('Rejecting…')
    try {
      const res = await fetch(`/api/voice/inbox/${triageId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      })
      const data = await res.json()
      if (!res.ok) showToast(`Reject failed: ${data?.detail || data?.error || res.status}`)
      else {
        showToast('Rejected ✓')
        setTimeout(onActioned, 800)
      }
    } catch (e: any) {
      showToast(`Reject failed: ${e?.message || e}`)
    } finally {
      setWorking(null)
    }
  }

  if (error) {
    return <div className="px-3 pb-3 text-xs text-rose-300">Error: {error}</div>
  }
  if (!detail) {
    return <div className="px-3 pb-3 text-xs text-slate-500">Loading detail…</div>
  }

  return (
    <div className="border-t border-slate-800 px-3 py-3 space-y-3">
      {/* Project + match */}
      <div className="rounded-md bg-slate-950/50 p-2 text-xs">
        <div className="text-slate-400">
          Project:{' '}
          <span className="text-slate-200">
            {detail.project_name || '(unmapped)'}
          </span>
          {detail.project_id && (
            <span className="ml-2 font-mono text-[10px] text-slate-500">
              {detail.project_id}
            </span>
          )}
        </div>
        {detail.classification && (
          <div className="mt-1 text-slate-500">
            Classification: {detail.classification}
            {detail.classification_confidence != null &&
              ` (${(detail.classification_confidence * 100).toFixed(0)}%)`}
          </div>
        )}
      </div>

      {/* Original email body */}
      <details className="text-xs">
        <summary className="cursor-pointer text-slate-400">
          Original email body
        </summary>
        <div className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md bg-slate-950/50 p-2 text-slate-300">
          {detail.email_body || '(body not captured — see cairn_email_raw)'}
        </div>
      </details>

      {/* Drafted reply — editable */}
      <div>
        <label className="text-xs text-slate-400">Drafted reply (editable)</label>
        <textarea
          ref={draftRef}
          value={draftEdit}
          onChange={e => setDraftEdit(e.target.value)}
          rows={Math.min(20, Math.max(6, (draftEdit.match(/\n/g)?.length || 0) + 3))}
          className="mt-1 w-full resize-y rounded-md border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
        />
        <div className="mt-1 text-[10px] text-slate-500">
          drafted by {detail.draft_model || '?'}
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={handleSaveEdit}
          disabled={!!working || draftEdit === (detail.draft_reply || '')}
          className="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-medium text-slate-100 hover:bg-slate-600 disabled:opacity-40"
        >
          Save edit
        </button>
        <button
          onClick={handleStage}
          disabled={!!working || !!detail.reviewed_at}
          className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-40"
        >
          Stage to sales@
        </button>
        <button
          onClick={handleReject}
          disabled={!!working || !!detail.reviewed_at}
          className="rounded-md bg-rose-900/80 px-3 py-1.5 text-xs font-medium text-rose-100 hover:bg-rose-900 disabled:opacity-40"
        >
          Reject
        </button>
        {detail.reviewed_at && (
          <span className="self-center text-[10px] text-emerald-400">
            Already actioned ({detail.review_action}) — buttons disabled
          </span>
        )}
      </div>

      {(working || toast) && (
        <div className="rounded-md bg-slate-800 px-3 py-1.5 text-xs text-slate-100">
          {working || toast}
        </div>
      )}
    </div>
  )
}
