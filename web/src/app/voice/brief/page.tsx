'use client'

/**
 * /voice/brief — Jo's Pip v0 daily surface (Layer 2).
 *
 * Single-screen layout per briefs/jo-pip-mobile-design.md §4.2:
 *   1. Confidentiality banner (sticky)
 *   2. Today's brief — questions inline with reply boxes (or
 *      captured answers if already replied)
 *   3. Memory search
 *   4. Recent memory writes
 *
 * Auth is handled by middleware + the Next.js proxies under
 * /api/deek/brief/*. If the user isn't signed in the proxies 401
 * and we redirect to /voice/login.
 *
 * This is intentionally separate from the existing /voice page —
 * different feature (memory-brief reply system, not Deek's morning
 * read briefing). Tabs and tasks live in /voice; brief reply lives
 * here. Jo's home-screen icon points at /voice/brief.
 */
import { useCallback, useEffect, useState } from 'react'
import { ConfidentialityBanner } from './components/ConfidentialityBanner'
import { BriefCard, type Brief } from './components/BriefCard'
import { MemorySearch } from './components/MemorySearch'
import { MemoryWriteFeed } from './components/MemoryWriteFeed'

interface Me {
  authenticated: boolean
  user?: { email: string; name?: string | null; role: string }
}

export default function BriefPage() {
  const [me, setMe] = useState<Me | null>(null)
  const [brief, setBrief] = useState<Brief | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [noBrief, setNoBrief] = useState(false)
  const [feedKey, setFeedKey] = useState(0) // bump to force MemoryWriteFeed remount on submit

  const loadBrief = useCallback(async () => {
    setLoading(true)
    setError(null)
    setNoBrief(false)
    try {
      const res = await fetch('/api/deek/brief/today', { cache: 'no-store' })
      if (res.status === 401) {
        window.location.href = '/voice/login?callbackUrl=/voice/brief'
        return
      }
      if (res.status === 404) {
        setNoBrief(true)
        setBrief(null)
        return
      }
      const data = await res.json()
      if (!res.ok) {
        setError(`Brief load failed: ${data?.detail || res.status}`)
        return
      }
      setBrief(data as Brief)
    } catch (err: any) {
      setError(err?.message || 'Network error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const boot = async () => {
      try {
        const res = await fetch('/api/voice/me', { cache: 'no-store' })
        if (res.status === 401) {
          window.location.href = '/voice/login?callbackUrl=/voice/brief'
          return
        }
        if (res.ok) setMe(await res.json())
      } catch {}
    }
    boot()
    loadBrief()
  }, [loadBrief])

  const onSubmitted = useCallback(() => {
    // Reload the brief (so it flips to "answered" state) AND nudge
    // the memory write feed to show the freshly-written chunks.
    setTimeout(() => {
      loadBrief()
      setFeedKey(k => k + 1)
    }, 500)
  }, [loadBrief])

  const displayName = me?.user?.name || 'Rex'

  return (
    <div className="min-h-[100dvh] bg-slate-950 text-slate-100">
      <ConfidentialityBanner displayName={displayName} />

      <main className="mx-auto max-w-2xl space-y-6 px-4 py-6">
        {/* Today's brief */}
        <section className="space-y-3">
          <div className="flex items-center justify-between text-xs uppercase tracking-wider text-slate-500">
            <span>Today</span>
            <button
              onClick={loadBrief}
              disabled={loading}
              className="rounded-full border border-slate-700 px-3 py-0.5 text-[11px] text-slate-400 hover:border-slate-500 disabled:opacity-50"
            >
              {loading ? 'Loading…' : 'Refresh'}
            </button>
          </div>

          {error && (
            <div className="rounded-md bg-rose-950/60 px-3 py-2 text-sm text-rose-200">
              {error}
            </div>
          )}

          {!loading && noBrief && (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-400">
              No brief yet today. The morning send will land it in your inbox
              and surface it here.
            </div>
          )}

          {brief && <BriefCard brief={brief} onSubmitted={onSubmitted} />}
        </section>

        {/* Memory search */}
        <MemorySearch />

        {/* Recent memory writes */}
        <MemoryWriteFeed key={feedKey} />
      </main>
    </div>
  )
}
