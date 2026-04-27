'use client'

/**
 * MemoryWriteFeed — chronological list of recent memory chunks
 * written via brief replies.
 *
 * Backed by /api/deek/brief/memory/recent → claw_code_chunks filtered
 * to file_path LIKE 'memory/brief-reply/%'. The cairn_memory_writes
 * table referenced in the original brief never existed —
 * claw_code_chunks is the canonical store.
 */
import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, BookOpen } from 'lucide-react'

interface MemoryWrite {
  id: number
  name: string
  snippet: string
  indexed_at: string | null
  salience: number | null
  via: string | null
}

export function MemoryWriteFeed() {
  const [items, setItems] = useState<MemoryWrite[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/deek/brief/memory/recent?limit=20', {
        cache: 'no-store',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data?.error || `HTTP ${res.status}`)
        setItems([])
      } else {
        setItems(data?.items || [])
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
          <BookOpen size={12} />
          Recent memory writes
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

      {!loading && items.length === 0 && !error && (
        <div className="rounded-md bg-slate-900/40 px-3 py-2 text-xs text-slate-600">
          No memory written from brief replies yet.
        </div>
      )}

      {items.length > 0 && (
        <ul className="space-y-2">
          {items.map(item => (
            <li
              key={item.id}
              className="rounded-md bg-slate-900/60 px-3 py-2 text-xs"
            >
              <div className="mb-1 flex items-center justify-between">
                <span className="font-mono text-slate-500">#{item.id}</span>
                {item.indexed_at && (
                  <span className="text-slate-600">
                    {new Date(item.indexed_at).toLocaleString('en-GB', {
                      month: 'short',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                )}
              </div>
              {item.snippet && (
                <div className="leading-relaxed text-slate-300">
                  {item.snippet}
                </div>
              )}
              {item.via && (
                <div className="mt-1 text-[10px] uppercase tracking-wider text-slate-600">
                  via {item.via}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
