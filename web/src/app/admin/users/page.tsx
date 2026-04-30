'use client'

/**
 * /admin/users — list of users + per-user "Reset password" button.
 *
 * ADMIN role only. Server-side enforcement: the API proxy at
 * /api/admin/users + /api/admin/users/reset both check
 * session.role === 'ADMIN' and 403 otherwise. This page also
 * client-side redirects non-admins back to /voice.
 */
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft, Loader2, Eye, EyeOff, Key, Check, AlertCircle, Users,
} from 'lucide-react'
import { BRAND } from '@/lib/brand'

interface User {
  email: string
  name: string | null
  role: string
  created_at: string | null
  updated_at: string | null
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [resetTarget, setResetTarget] = useState<User | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/users', { cache: 'no-store' })
      if (res.status === 401) {
        window.location.href = '/voice/login?callbackUrl=/admin/users'
        return
      }
      if (res.status === 403) {
        window.location.href = '/voice'
        return
      }
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data?.error || `HTTP ${res.status}`)
        setUsers([])
      } else {
        setUsers(data.users || [])
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
    <div className="min-h-[100dvh] bg-white text-gray-900">
      <header className="flex items-center justify-between border-b border-gray-200 px-4 py-2">
        <div className="flex items-center gap-3">
          <Link
            href="/voice"
            className="rounded-md p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
            title="Back to chat"
          >
            <ArrowLeft size={16} />
          </Link>
          <div className="flex items-center gap-2 text-sm font-semibold tracking-tight">
            <Users size={14} />
            Users
          </div>
        </div>
        <div className="text-xs text-gray-500">{BRAND}</div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6">
        {loading && (
          <div className="flex items-center gap-2 py-12 text-sm text-gray-500">
            <Loader2 size={14} className="animate-spin" />
            Loading users…
          </div>
        )}

        {error && (
          <div className="mb-4 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">
            <AlertCircle size={14} />
            {error}
          </div>
        )}

        {!loading && users.length === 0 && !error && (
          <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
            No users yet.
          </div>
        )}

        {users.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-gray-200">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Email</th>
                  <th className="px-3 py-2 text-left font-medium">Name</th>
                  <th className="px-3 py-2 text-left font-medium">Role</th>
                  <th className="px-3 py-2 text-left font-medium">Updated</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr
                    key={u.email}
                    className="border-t border-gray-100 hover:bg-gray-50"
                  >
                    <td className="px-3 py-2 font-mono text-xs text-gray-700">
                      {u.email}
                    </td>
                    <td className="px-3 py-2 text-gray-700">{u.name || '—'}</td>
                    <td className="px-3 py-2">
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-gray-700">
                        {u.role}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {u.updated_at
                        ? new Date(u.updated_at).toLocaleDateString('en-GB')
                        : '—'}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => setResetTarget(u)}
                        className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
                      >
                        <Key size={11} /> Reset password
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {resetTarget && (
        <ResetPasswordModal
          target={resetTarget}
          onClose={() => setResetTarget(null)}
          onDone={() => {
            setResetTarget(null)
            load()
          }}
        />
      )}
    </div>
  )
}

// ── Reset modal ──────────────────────────────────────────────────────

function ResetPasswordModal({
  target,
  onClose,
  onDone,
}: {
  target: User
  onClose: () => void
  onDone: () => void
}) {
  const [pw, setPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [reveal, setReveal] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const submit = async () => {
    setError(null)
    if (pw.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (pw !== confirmPw) {
      setError("Passwords don't match.")
      return
    }
    setBusy(true)
    try {
      const res = await fetch('/api/admin/users/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_email: target.email,
          new_password: pw,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data?.detail || data?.error || `HTTP ${res.status}`)
        setBusy(false)
        return
      }
      setDone(true)
      setTimeout(onDone, 1200)
    } catch (err: any) {
      setError(err?.message || 'Network error')
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-xl"
      >
        <div className="mb-2 text-base font-semibold text-gray-900">
          Reset password
        </div>
        <div className="mb-4 text-xs text-gray-500">
          Setting a new password for{' '}
          <span className="font-mono text-gray-700">{target.email}</span>.
          They'll need this new password on next sign-in.
        </div>

        {done ? (
          <div className="flex items-center gap-2 rounded-md bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
            <Check size={16} />
            Password reset. Pass the new one to {target.name || target.email}.
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs uppercase tracking-wider text-gray-500">
                New password (8+ chars)
              </label>
              <div className="relative">
                <input
                  type={reveal ? 'text' : 'password'}
                  value={pw}
                  onChange={e => setPw(e.target.value)}
                  disabled={busy}
                  minLength={8}
                  autoComplete="new-password"
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-10 text-sm text-gray-900 placeholder-gray-400 focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-400 disabled:opacity-60"
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setReveal(v => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                  aria-label={reveal ? 'Hide' : 'Show'}
                >
                  {reveal ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs uppercase tracking-wider text-gray-500">
                Confirm password
              </label>
              <input
                type={reveal ? 'text' : 'password'}
                value={confirmPw}
                onChange={e => setConfirmPw(e.target.value)}
                disabled={busy}
                minLength={8}
                autoComplete="new-password"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-400 disabled:opacity-60"
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-rose-200">
                <AlertCircle size={12} />
                {error}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                onClick={onClose}
                disabled={busy}
                className="rounded-md px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={submit}
                disabled={busy || !pw || !confirmPw}
                className="flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-40"
              >
                {busy && <Loader2 size={12} className="animate-spin" />}
                {busy ? 'Resetting…' : 'Reset password'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
