'use client'

/**
 * /admin/staff — Directors-only staff profile management.
 *
 * Each row is editable inline. Changes hit PUT /api/voice/staff.
 */
import { useCallback, useEffect, useState } from 'react'

interface StaffProfile {
  email: string
  display_name: string | null
  role_tag: string | null
  briefings_enabled: boolean
  briefing_time: string
  active_days: string
  quiet_start: string
  quiet_end: string
  preferred_voice: string | null
  preferred_face: string | null
  notes: string | null
  created_at: string | null
  updated_at: string | null
}

const ROLE_OPTIONS = ['production', 'dispatch', 'tech', 'admin', 'director']
const DAY_OPTIONS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

export default function StaffPage() {
  const [profiles, setProfiles] = useState<StaffProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingEmail, setSavingEmail] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/voice/staff', { cache: 'no-store' })
      if (res.status === 403) {
        setError('Admin/PM role required.')
        return
      }
      if (!res.ok) {
        setError(`HTTP ${res.status}`)
        return
      }
      const data = await res.json()
      setProfiles(data.profiles || [])
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => {
    load()
  }, [load])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  const save = useCallback(async (profile: Partial<StaffProfile>) => {
    if (!profile.email) return
    setSavingEmail(profile.email)
    try {
      const res = await fetch('/api/voice/staff', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile),
      })
      if (res.ok) {
        showToast(`Saved ${profile.email}`)
        await load()
      } else {
        const data = await res.json().catch(() => ({}) as any)
        showToast(`Save failed: ${data?.detail || res.status}`)
      }
    } finally {
      setSavingEmail(null)
    }
  }, [load])

  const updateLocal = (email: string, patch: Partial<StaffProfile>) => {
    setProfiles(ps => ps.map(p => (p.email === email ? { ...p, ...patch } : p)))
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center p-8 text-center text-slate-500">
        {error}
      </div>
    )
  }
  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-slate-500">
        Loading staff profiles…
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Staff profiles</h1>
        <p className="text-sm text-slate-500">
          Role, briefing schedule and preferences for each team member.
          Changes save per row.
        </p>
      </div>

      <div className="space-y-4">
        {profiles.map(p => (
          <ProfileRow
            key={p.email}
            profile={p}
            saving={savingEmail === p.email}
            onField={patch => updateLocal(p.email, patch)}
            onSave={() => save(p)}
          />
        ))}
        {profiles.length === 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-6 text-center text-slate-500">
            No profiles yet. They'll seed on next API restart.
          </div>
        )}
      </div>

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-lg bg-slate-800 px-4 py-2 text-xs text-slate-100 shadow-xl">
          {toast}
        </div>
      )}
    </div>
  )
}

function ProfileRow({
  profile,
  saving,
  onField,
  onSave,
}: {
  profile: StaffProfile
  saving: boolean
  onField: (patch: Partial<StaffProfile>) => void
  onSave: () => void
}) {
  const days = new Set(profile.active_days.split(',').map(s => s.trim().toLowerCase()))
  const toggleDay = (d: string) => {
    const newSet = new Set(days)
    if (newSet.has(d)) newSet.delete(d)
    else newSet.add(d)
    const ordered = DAY_OPTIONS.filter(x => newSet.has(x)).join(',')
    onField({ active_days: ordered })
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-semibold text-slate-900">
            {profile.display_name || profile.email}
          </div>
          <div className="text-xs text-slate-500">{profile.email}</div>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={profile.briefings_enabled}
            onChange={e => onField({ briefings_enabled: e.target.checked })}
          />
          Briefings on
        </label>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field label="Role">
          <select
            value={profile.role_tag || ''}
            onChange={e => onField({ role_tag: e.target.value || null })}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">—</option>
            {ROLE_OPTIONS.map(r => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Briefing time">
          <input
            type="time"
            value={profile.briefing_time}
            onChange={e => onField({ briefing_time: e.target.value })}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
        </Field>
        <Field label="Quiet start">
          <input
            type="time"
            value={profile.quiet_start}
            onChange={e => onField({ quiet_start: e.target.value })}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
        </Field>
        <Field label="Quiet end">
          <input
            type="time"
            value={profile.quiet_end}
            onChange={e => onField({ quiet_end: e.target.value })}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
        </Field>
      </div>

      <div className="mt-3">
        <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">
          Active days
        </div>
        <div className="flex flex-wrap gap-1">
          {DAY_OPTIONS.map(d => (
            <button
              key={d}
              onClick={() => toggleDay(d)}
              className={`rounded-md border px-2 py-1 text-xs ${
                days.has(d)
                  ? 'border-emerald-500 bg-emerald-50 text-emerald-700'
                  : 'border-slate-300 text-slate-500'
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      <Field label="Notes">
        <textarea
          value={profile.notes || ''}
          onChange={e => onField({ notes: e.target.value })}
          rows={2}
          className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
          placeholder="What Deek should know about this person's role + preferences"
        />
      </Field>

      <div className="mt-3 flex justify-end">
        <button
          onClick={onSave}
          disabled={saving}
          className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-xs uppercase tracking-wider text-slate-500">
        {label}
      </div>
      {children}
    </div>
  )
}
