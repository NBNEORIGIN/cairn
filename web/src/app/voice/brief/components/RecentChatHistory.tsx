'use client'

/**
 * RecentChatHistory — read-only feed of the user's last ~20 turns.
 *
 * Reuses /api/voice/sessions?user=<email>&limit=20 (cross-device
 * continuity — same endpoint the existing voice PWA hydrates from).
 * No new backend needed.
 */
import { useCallback, useEffect, useState } from 'react'
import { MessageSquare, RefreshCw } from 'lucide-react'

interface ChatTurn {
  role: 'user' | 'assistant' | string
  text: string
  at: string | number
  outcome?: string | null
}

export function RecentChatHistory() {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/voice/sessions?limit=20', {
        cache: 'no-store',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data?.error || `HTTP ${res.status}`)
        setTurns([])
      } else {
        setTurns(data?.turns || [])
      }
    } catch (err: any) {
      setError(err?.message || 'Network error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-slate-500">
          <MessageSquare size={12} />
          Recent chat
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1 rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400 hover:border-slate-500 disabled:opacity-50"
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-md bg-rose-950/60 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {!loading && turns.length === 0 && !error && (
        <div className="rounded-md bg-slate-900/40 px-3 py-2 text-xs text-slate-600">
          No recent conversation.
        </div>
      )}

      {turns.length > 0 && (
        <ul className="space-y-2">
          {turns.map((t, i) => (
            <li
              key={`${t.at}-${i}`}
              className={`rounded-md px-3 py-2 text-xs leading-relaxed ${
                t.role === 'user'
                  ? 'bg-slate-900/80 text-slate-100'
                  : 'bg-slate-900/40 text-slate-300'
              }`}
            >
              <div className="mb-0.5 flex items-center justify-between text-[10px] uppercase tracking-wider text-slate-500">
                <span>{t.role}</span>
                <span>
                  {(() => {
                    const d =
                      typeof t.at === 'number' ? new Date(t.at) : new Date(t.at)
                    return isNaN(d.getTime())
                      ? ''
                      : d.toLocaleTimeString('en-GB', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })
                  })()}
                </span>
              </div>
              <div className="whitespace-pre-wrap">
                {t.text.length > 320 ? t.text.slice(0, 317) + '…' : t.text}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
