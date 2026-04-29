'use client'

/**
 * Persistent strip at the top of /voice/brief reminding Jo whose
 * instance she's on and that the conversation is hers alone.
 *
 * The host name comes from window.location.host so it Just Works
 * whether she's on jo.nbne.local (Tailscale) or 100.x.x.x:443
 * directly. Falls back to "Rex" when host is unavailable (SSR).
 */
import { useEffect, useState } from 'react'
import { Lock } from 'lucide-react'

interface Props {
  displayName?: string
}

export function ConfidentialityBanner({ displayName = 'Rex' }: Props) {
  const [host, setHost] = useState<string>('')

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setHost(window.location.host || '')
    }
  }, [])

  return (
    <div className="sticky top-0 z-40 flex items-center justify-center gap-2 border-b border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-800 backdrop-blur">
      <Lock size={12} />
      <span className="font-medium">{displayName}</span>
      {host && (
        <>
          <span className="text-emerald-400">—</span>
          <span className="font-mono text-emerald-700">{host}</span>
        </>
      )}
    </div>
  )
}
