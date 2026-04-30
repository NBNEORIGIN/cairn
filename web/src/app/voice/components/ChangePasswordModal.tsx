'use client'

/**
 * Change-password modal — opens from the user menu in the /voice header.
 *
 * POSTs to /api/voice/me/password with old_password + new_password. The
 * proxy adds the email from the JWT cookie. On success the modal closes;
 * the user stays signed in (their JWT cookie is unchanged).
 */
import { useState, type FormEvent } from 'react'
import { Eye, EyeOff, Loader2, Check, X, AlertCircle } from 'lucide-react'

interface Props {
  onClose: () => void
}

export function ChangePasswordModal({ onClose }: Props) {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmNew, setConfirmNew] = useState('')
  const [showOld, setShowOld] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setError(null)

    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmNew) {
      setError('New password and confirmation don\'t match.')
      return
    }
    if (newPassword === oldPassword) {
      setError('New password must be different from the old one.')
      return
    }

    setBusy(true)
    try {
      const res = await fetch('/api/voice/me/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          old_password: oldPassword,
          new_password: newPassword,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data?.detail || data?.error || `Couldn't update (HTTP ${res.status}).`)
        setBusy(false)
        return
      }
      setDone(true)
      setTimeout(onClose, 1200)
    } catch (err: any) {
      setError(err?.message || 'Network error.')
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
        <div className="mb-4 flex items-center justify-between">
          <div className="text-base font-semibold text-gray-900">Change password</div>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-900"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {done ? (
          <div className="flex items-center gap-2 rounded-md bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
            <Check size={16} />
            Password updated. You stay signed in.
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <div>
              <label className="mb-1 block text-xs uppercase tracking-wider text-gray-500">
                Current password
              </label>
              <div className="relative">
                <input
                  type={showOld ? 'text' : 'password'}
                  required
                  autoComplete="current-password"
                  value={oldPassword}
                  onChange={e => setOldPassword(e.target.value)}
                  disabled={busy}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-10 text-sm text-gray-900 placeholder-gray-400 focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-400 disabled:opacity-60"
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowOld(v => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                  aria-label={showOld ? 'Hide' : 'Show'}
                >
                  {showOld ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs uppercase tracking-wider text-gray-500">
                New password (8+ chars)
              </label>
              <div className="relative">
                <input
                  type={showNew ? 'text' : 'password'}
                  required
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  disabled={busy}
                  minLength={8}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-10 text-sm text-gray-900 placeholder-gray-400 focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-400 disabled:opacity-60"
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowNew(v => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                  aria-label={showNew ? 'Hide' : 'Show'}
                >
                  {showNew ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs uppercase tracking-wider text-gray-500">
                Confirm new password
              </label>
              <input
                type={showNew ? 'text' : 'password'}
                required
                autoComplete="new-password"
                value={confirmNew}
                onChange={e => setConfirmNew(e.target.value)}
                disabled={busy}
                minLength={8}
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
                type="button"
                onClick={onClose}
                disabled={busy}
                className="rounded-md px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy || !oldPassword || !newPassword || !confirmNew}
                className="flex items-center gap-1.5 rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-40"
              >
                {busy && <Loader2 size={12} className="animate-spin" />}
                {busy ? 'Updating…' : 'Update password'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
