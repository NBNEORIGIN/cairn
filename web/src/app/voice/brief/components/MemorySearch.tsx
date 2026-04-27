'use client'

/**
 * MemorySearch — single search box → matching wiki/memory chunks.
 *
 * Hits /api/deek/wiki/search (proxy → /api/wiki/search hybrid retriever).
 * Debounced 400ms so typing doesn't hammer the backend.
 */
import { useEffect, useRef, useState } from 'react'
import { Search, Loader2 } from 'lucide-react'

interface SearchResult {
  id?: number | string
  file_path?: string
  chunk_name?: string
  snippet?: string
  text?: string
  score?: number
}

export function MemorySearch() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!q.trim()) {
      setResults([])
      setLoading(false)
      return
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(
          `/api/deek/wiki/search?q=${encodeURIComponent(q.trim())}&top_k=10`,
          { cache: 'no-store' },
        )
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          setError(data?.error || `HTTP ${res.status}`)
          setResults([])
        } else {
          // The wiki search endpoint returns results under various
          // keys depending on the indexing path; accept all.
          const items: SearchResult[] =
            data?.results || data?.items || data?.matches || []
          setResults(items)
        }
      } catch (err: any) {
        setError(err?.message || 'Network error')
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 400)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [q])

  return (
    <section className="space-y-3">
      <div className="text-xs uppercase tracking-wider text-slate-500">
        Memory search
      </div>
      <div className="relative">
        <Search
          size={14}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
        />
        <input
          type="text"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search your memory…"
          className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 pl-9 text-sm text-slate-100 placeholder:text-slate-600 focus:border-emerald-700 focus:outline-none"
        />
        {loading && (
          <Loader2
            size={14}
            className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-slate-500"
          />
        )}
      </div>

      {error && (
        <div className="rounded-md bg-rose-950/60 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      {!loading && q.trim() && results.length === 0 && !error && (
        <div className="text-xs text-slate-600">No matches.</div>
      )}

      {results.length > 0 && (
        <ul className="space-y-2">
          {results.map((r, i) => {
            const title = r.chunk_name || r.file_path || `Result ${i + 1}`
            const body = r.snippet || r.text || ''
            return (
              <li
                key={`${r.id ?? title}-${i}`}
                className="rounded-md bg-slate-900/60 px-3 py-2"
              >
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="font-mono text-slate-400">{title}</span>
                  {typeof r.score === 'number' && (
                    <span className="text-slate-600">
                      {r.score.toFixed(2)}
                    </span>
                  )}
                </div>
                {body && (
                  <div className="text-xs leading-relaxed text-slate-300">
                    {body.length > 280 ? body.slice(0, 277) + '…' : body}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
