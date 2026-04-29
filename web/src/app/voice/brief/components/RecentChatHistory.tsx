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
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-gray-500">
          <MessageSquare size={12} />
          Recent chat
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1 rounded-full border border-gray-300 px-2 py-0.5 text-[11px] text-gray-600 hover:border-gray-400 hover:text-gray-900 disabled:opacity-50"
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-rose-200">
          {error}
        </div>
      )}

      {!loading && turns.length === 0 && !error && (
        <div className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-500 ring-1 ring-gray-200">
          No recent conversation.
        </div>
      )}

      {turns.length > 0 && (
        <ul className="space-y-2">
          {turns.map((t, i) => (
            <li
              key={`${t.at}-${i}`}
              className={`rounded-md px-3 py-2 text-xs leading-relaxed ring-1 ring-gray-200 ${
                t.role === 'user'
                  ? 'bg-gray-100 text-gray-900'
                  : 'bg-gray-50 text-gray-700'
              }`}
            >
              <div className="mb-0.5 flex items-center justify-between text-[10px] uppercase tracking-wider text-gray-500">
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
