'use client'

/**
 * /admin/voice-metrics — Phase 1.5 telemetry dashboard.
 *
 * Aggregations over deek_voice_sessions: count/day, cost, latency,
 * outcomes, location breakdown, last 20 turns. Admin + PM roles only.
 *
 * Not a real-time dashboard — polls every 30s. Good enough for
 * spotting cost creep or misclassification patterns.
 */
import { useEffect, useState } from 'react'

interface OutcomeRow {
  outcome: string
  count: number
}
interface DailyRow {
  day: string
  count: number
  cost_usd: number
  avg_latency_ms: number
}
interface Turn {
  session_id: string
  user: string | null
  location: string | null
  question: string
  response: string | null
  outcome: string | null
  model_used: string | null
  latency_ms: number | null
  created_at: string | null
}
interface Metrics {
  count_24h: number
  count_7d: number
  cost_usd_24h: number
  cost_usd_7d: number
  avg_latency_ms_24h: number
  outcomes_24h: OutcomeRow[]
  by_location_24h: { location: string; count: number }[]
  by_day_7d: DailyRow[]
  recent_turns: Turn[]
  budget_limit: number
  budget_cost_cap_gbp: number
}

export default function VoiceMetricsPage() {
  const [data, setData] = useState<Metrics | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch('/api/voice/metrics', { cache: 'no-store' })
        if (res.status === 403) {
          setError('Admin or PM role required to view voice metrics.')
          return
        }
        if (!res.ok) {
          setError(`HTTP ${res.status}`)
          return
        }
        const json = await res.json()
        setData(json)
        setError(null)
      } catch (err: any) {
        setError(`Failed to load: ${err?.message || err}`)
      }
    }
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [])

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center p-8 text-center text-slate-500">
        <div>
          <div className="mb-2 text-lg font-semibold text-slate-800">
            Voice Metrics
          </div>
          <div className="text-sm">{error}</div>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-slate-500">
        Loading metrics…
      </div>
    )
  }

  const budgetPct = Math.min(100, (data.count_24h / data.budget_limit) * 100)

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Voice Metrics</h1>
        <p className="text-sm text-slate-500">
          Telemetry from <code>deek_voice_sessions</code> — refreshes every 30s.
        </p>
      </div>

      {/* Top cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="Turns (24h)" value={String(data.count_24h)} sub={`${data.count_7d} in 7d`} />
        <Card
          label="Spend (24h)"
          value={`$${data.cost_usd_24h.toFixed(4)}`}
          sub={`$${data.cost_usd_7d.toFixed(4)} in 7d`}
        />
        <Card
          label="Avg latency (24h)"
          value={`${Math.round(data.avg_latency_ms_24h)}ms`}
          sub="successful turns only"
        />
        <Card
          label="Daily budget"
          value={`${data.count_24h} / ${data.budget_limit}`}
          sub={`£${data.budget_cost_cap_gbp.toFixed(2)} cap`}
        >
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
            <div
              className={`h-full ${
                budgetPct > 90
                  ? 'bg-rose-500'
                  : budgetPct > 70
                  ? 'bg-amber-400'
                  : 'bg-emerald-500'
              }`}
              style={{ width: `${budgetPct}%` }}
            />
          </div>
        </Card>
      </div>

      {/* Outcomes + Locations */}
      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Outcomes (24h)">
          {data.outcomes_24h.length === 0 ? (
            <Empty />
          ) : (
            <ul className="space-y-1 text-sm">
              {data.outcomes_24h.map(o => (
                <li key={o.outcome} className="flex items-center justify-between">
                  <span className={outcomeClass(o.outcome)}>{o.outcome}</span>
                  <span className="font-mono">{o.count}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="By location (24h)">
          {data.by_location_24h.length === 0 ? (
            <Empty />
          ) : (
            <ul className="space-y-1 text-sm">
              {data.by_location_24h.map(l => (
                <li key={l.location} className="flex items-center justify-between">
                  <span>{l.location}</span>
                  <span className="font-mono">{l.count}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {/* 7-day history */}
      <Panel title="Last 7 days">
        {data.by_day_7d.length === 0 ? (
          <Empty />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
                <th className="py-1">Day</th>
                <th className="py-1 text-right">Turns</th>
                <th className="py-1 text-right">Spend $</th>
                <th className="py-1 text-right">Avg latency</th>
              </tr>
            </thead>
            <tbody>
              {data.by_day_7d.map(d => (
                <tr key={d.day} className="border-t border-slate-100">
                  <td className="py-1">{d.day}</td>
                  <td className="py-1 text-right font-mono">{d.count}</td>
                  <td className="py-1 text-right font-mono">
                    {d.cost_usd.toFixed(4)}
                  </td>
                  <td className="py-1 text-right font-mono">
                    {Math.round(d.avg_latency_ms)}ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {/* Recent turns */}
      <Panel title="Recent turns (latest 20)">
        {data.recent_turns.length === 0 ? (
          <Empty />
        ) : (
          <div className="space-y-2">
            {data.recent_turns.map((t, i) => (
              <div
                key={i}
                className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm"
              >
                <div className="mb-1 flex items-center gap-2 text-xs text-slate-500">
                  <span>{t.created_at ? new Date(t.created_at).toLocaleString('en-GB') : '—'}</span>
                  {t.user && <span>· {t.user}</span>}
                  {t.location && <span>· {t.location}</span>}
                  {t.model_used && <span>· {t.model_used}</span>}
                  {t.latency_ms != null && (
                    <span>· {t.latency_ms}ms</span>
                  )}
                  <span className={`ml-auto ${outcomeClass(t.outcome || '')}`}>
                    {t.outcome}
                  </span>
                </div>
                <div className="mb-1 text-slate-900">
                  <span className="mr-2 text-xs font-semibold text-slate-500">
                    Q:
                  </span>
                  {t.question}
                </div>
                {t.response && (
                  <div className="text-slate-700">
                    <span className="mr-2 text-xs font-semibold text-slate-500">
                      A:
                    </span>
                    {t.response}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}

function Card({
  label,
  value,
  sub,
  children,
}: {
  label: string
  value: string
  sub?: string
  children?: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
      {children}
    </div>
  )
}

function Panel({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 text-xs uppercase tracking-wider text-slate-500">
        {title}
      </div>
      {children}
    </div>
  )
}

function Empty() {
  return <div className="text-xs text-slate-400">(no data)</div>
}

function outcomeClass(outcome: string): string {
  if (outcome === 'success') return 'text-emerald-600'
  if (outcome === 'budget_trip') return 'text-amber-600'
  if (outcome === 'backend_error' || outcome === 'forbidden')
    return 'text-rose-600'
  return 'text-slate-500'
}
