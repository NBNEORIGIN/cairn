'use client'

/**
 * The ⋯ dropdown menu in the header.
 * Download transcript · Commit to memory · Logout.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { VoiceLoopTurn } from '@/hooks/useVoiceLoop'

export function TopMenu({
  transcript,
  sessionId,
  userEmail,
}: {
  transcript: VoiceLoopTurn[]
  sessionId: string | null
  userEmail?: string
}) {
  const [open, setOpen] = useState(false)
  const [working, setWorking] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    window.addEventListener('mousedown', onClick)
    return () => window.removeEventListener('mousedown', onClick)
  }, [open])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 5000)
  }

  const handleDownload = useCallback(() => {
    if (transcript.length === 0) {
      showToast('Nothing to download yet.')
      return
    }
    const now = new Date()
    const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}-${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`
    const lines: string[] = []
    lines.push(`# Deek transcript — ${stamp}`)
    if (sessionId) lines.push(`\nSession: \`${sessionId}\``)
    if (userEmail) lines.push(`User: ${userEmail}`)
    lines.push('')
    for (const t of transcript) {
      const who = t.role === 'user' ? 'User' : 'Deek'
      lines.push(`**${who}:** ${t.text}`)
      lines.push('')
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `deek-transcript-${stamp}.md`
    a.click()
    URL.revokeObjectURL(url)
    setOpen(false)
  }, [transcript, sessionId, userEmail])

  const handleCommit = useCallback(async () => {
    if (!sessionId) {
      showToast('Start a conversation first — no session to commit.')
      return
    }
    setOpen(false)
    setWorking('Committing to memory…')
    try {
      const res = await fetch('/api/voice/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      })
      const data = await res.json()
      if (!res.ok) {
        showToast(
          `Commit failed: ${data?.detail || data?.error || res.status}`,
        )
      } else {
        showToast(
          `Saved as "${data.title}" · ${data.turn_count} turns · searchable`,
        )
      }
    } catch (err: any) {
      showToast(`Commit failed: ${err?.message || err}`)
    } finally {
      setWorking(null)
    }
  }, [sessionId])

  const handleLogout = useCallback(async () => {
    await fetch('/api/voice/logout', { method: 'POST' })
    window.location.href = '/voice/login'
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-label="Menu"
        className="rounded-lg px-2 py-1 text-lg text-slate-300 hover:bg-slate-800"
      >
        ⋯
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 w-56 overflow-hidden rounded-lg border border-slate-700 bg-slate-900 shadow-lg">
          <MenuItem onClick={handleDownload} label="Download transcript" hint=".md file" />
          <MenuItem onClick={handleCommit} label="Commit to memory" hint="save as wiki article" />
          <div className="border-t border-slate-800" />
          <MenuItem onClick={handleLogout} label="Sign out" />
        </div>
      )}
      {(working || toast) && (
        <div className="fixed bottom-20 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-slate-800 px-4 py-2 text-xs text-slate-100 shadow-xl">
          {working || toast}
        </div>
      )}
    </div>
  )
}

function MenuItem({
  onClick,
  label,
  hint,
}: {
  onClick: () => void
  label: string
  hint?: string
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full flex-col items-start px-3 py-2 text-left text-sm text-slate-200 hover:bg-slate-800"
    >
      <span>{label}</span>
      {hint && <span className="text-xs text-slate-500">{hint}</span>}
    </button>
  )
}
