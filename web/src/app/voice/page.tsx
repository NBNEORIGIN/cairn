'use client'

/**
 * Voice / Ambient interface — Phase 1 of the Deek voice brief.
 *
 * What this page does:
 * 1. Ambient view — location-scoped panels + morning number + clock,
 *    refreshed every 60 seconds. Cached in localStorage so the PWA
 *    still shows last-good data when Deek is offline.
 * 2. Press-to-talk — Web Speech API captures audio IN THE BROWSER
 *    (no audio ever hits our server — privacy by design). The
 *    transcript is POSTed to /api/voice/chat, the text response is
 *    displayed and read aloud via SpeechSynthesis.
 * 3. Location picker — first visit asks where you are; stored in
 *    localStorage, editable via the header badge.
 *
 * Failure modes handled:
 * - Deek API unreachable → "Deek offline" banner, cached ambient data
 * - Web Speech returns empty → "Didn't catch that — try again"
 * - Budget tripped → canned message displayed, no retry spin
 * - Browser without Web Speech → fallback text input
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'

type Location = 'workshop' | 'office' | 'home'

interface Me {
  authenticated: boolean
  user?: { id: string; email?: string; name?: string | null; role: string }
  allowed_locations?: Location[]
  login_url?: string
}

interface MorningNumber {
  number: string
  unit: string
  headline: string
  subtitle: string
  source_module: string
  stale: boolean
  as_of?: string | null
}

interface PanelItem {
  label: string
  status?: string | null
  detail?: string | null
}

interface AmbientPanel {
  id: string
  title: string
  items: PanelItem[]
}

interface AmbientPayload {
  location: Location
  morning_number: MorningNumber
  panels: AmbientPanel[]
  generated_at: string
  error?: string
  offline?: boolean
}

interface VoiceResponse {
  response: string
  session_id: string
  model_used: string
  cost_usd: number
  latency_ms: number
  outcome: 'success' | 'budget_trip' | 'backend_error'
  budget_remaining?: number
}

type Transcript = {
  role: 'user' | 'deek'
  text: string
  at: number
  outcome?: string
}

const CACHE_KEY = 'deek.ambient.cache'
const LOCATION_KEY = 'deek.location'
const SESSION_KEY = 'deek.voice.session'

export default function VoicePage() {
  const [me, setMe] = useState<Me | null>(null)
  const [location, setLocation] = useState<Location | null>(null)
  const [ambient, setAmbient] = useState<AmbientPayload | null>(null)
  const [offline, setOffline] = useState(false)
  const [now, setNow] = useState<Date>(new Date())
  const [listening, setListening] = useState(false)
  const [busy, setBusy] = useState(false)
  const [transcript, setTranscript] = useState<Transcript[]>([])
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [sttUnsupported, setSttUnsupported] = useState(false)
  const [fallbackInput, setFallbackInput] = useState('')

  const recognitionRef = useRef<any>(null)
  const sessionIdRef = useRef<string | null>(null)

  // ── Boot: fetch session + load location + hydrate transcript ──────
  useEffect(() => {
    const boot = async () => {
      // 1. Session / ACL
      try {
        const res = await fetch('/api/voice/me', { cache: 'no-store' })
        if (res.status === 401) {
          // Send user to login with this page as callbackUrl
          const cb = encodeURIComponent('/voice')
          window.location.href = `/voice/login?callbackUrl=${cb}`
          return
        }
        const json: Me = await res.json()
        setMe(json)

        // 2. Restore location if allowed
        const stored = localStorage.getItem(LOCATION_KEY) as Location | null
        if (
          stored &&
          (json.allowed_locations || []).includes(stored as Location)
        ) {
          setLocation(stored as Location)
        }

        // 3. Restore session id
        sessionIdRef.current = localStorage.getItem(SESSION_KEY)

        // 4. Hydrate transcript from server (last 20 turns for this user)
        try {
          const qs = sessionIdRef.current
            ? `?session_id=${sessionIdRef.current}&limit=20`
            : `?limit=20`
          const sRes = await fetch(`/api/voice/sessions${qs}`, {
            cache: 'no-store',
          })
          if (sRes.ok) {
            const sData = await sRes.json()
            const turns = (sData.turns || []).map((t: any) => ({
              role: t.role,
              text: t.text,
              at: new Date(t.at).getTime(),
              outcome: t.outcome,
            }))
            if (turns.length > 0) {
              setTranscript(turns)
            }
          }
        } catch {}
      } catch {
        // Offline / network failure — let the user try anyway; API proxies
        // will 401 and we'll handle it there.
      }

      // 5. Detect Web Speech support
      const SpeechRecognition =
        (typeof window !== 'undefined' &&
          ((window as any).SpeechRecognition ||
            (window as any).webkitSpeechRecognition)) ||
        null
      if (!SpeechRecognition) {
        setSttUnsupported(true)
      }
    }
    boot()
  }, [])

  // ── Clock — ticks every second ────────────────────────────────────
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  // ── Ambient polling + caching ─────────────────────────────────────
  const fetchAmbient = useCallback(async (loc: Location) => {
    try {
      const res = await fetch(`/api/voice/ambient?location=${loc}`, {
        cache: 'no-store',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: AmbientPayload = await res.json()
      setAmbient(data)
      setOffline(false)
      localStorage.setItem(
        CACHE_KEY,
        JSON.stringify({ location: loc, at: Date.now(), data })
      )
    } catch (err) {
      // Degrade to cached data
      const cached = localStorage.getItem(CACHE_KEY)
      if (cached) {
        try {
          const parsed = JSON.parse(cached)
          if (parsed.location === loc) {
            setAmbient(parsed.data)
          }
        } catch {}
      }
      setOffline(true)
    }
  }, [])

  useEffect(() => {
    if (!location) return
    fetchAmbient(location)
    const id = setInterval(() => fetchAmbient(location), 60_000)
    return () => clearInterval(id)
  }, [location, fetchAmbient])

  // ── Location change ───────────────────────────────────────────────
  const pickLocation = useCallback((loc: Location) => {
    setLocation(loc)
    localStorage.setItem(LOCATION_KEY, loc)
  }, [])

  // ── Speech synthesis (TTS) ────────────────────────────────────────
  const speak = useCallback((text: string) => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return
    try {
      window.speechSynthesis.cancel()
      const u = new SpeechSynthesisUtterance(text)
      u.rate = 1.0
      u.pitch = 1.0
      u.lang = 'en-GB'
      // Prefer a British voice if available
      const voices = window.speechSynthesis.getVoices()
      const gb = voices.find(v => v.lang.startsWith('en-GB'))
      if (gb) u.voice = gb
      window.speechSynthesis.speak(u)
    } catch {}
  }, [])

  // ── Submit a transcribed or typed utterance ───────────────────────
  const submitUtterance = useCallback(
    async (utterance: string) => {
      if (!location) return
      const text = (utterance || '').trim()
      if (!text) {
        setErrorMsg("Didn't catch that — tap to try again.")
        return
      }
      setErrorMsg(null)
      setBusy(true)
      setTranscript(t => [...t, { role: 'user', text, at: Date.now() }])

      try {
        const res = await fetch('/api/voice/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            content: text,
            location,
            session_id: sessionIdRef.current,
          }),
        })
        if (res.status === 401) {
          // Session expired — bounce to login with return-to here
          const cb = encodeURIComponent('/voice')
          window.location.href = `/voice/login?callbackUrl=${cb}`
          return
        }
        const data: VoiceResponse = await res.json()

        // Persist the session ID for continuity
        if (data.session_id) {
          sessionIdRef.current = data.session_id
          localStorage.setItem(SESSION_KEY, data.session_id)
        }

        setTranscript(t => [
          ...t,
          {
            role: 'deek',
            text: data.response,
            at: Date.now(),
            outcome: data.outcome,
          },
        ])
        if (data.outcome !== 'backend_error') speak(data.response)
      } catch (err) {
        setTranscript(t => [
          ...t,
          {
            role: 'deek',
            text: 'Network error — try again in a moment.',
            at: Date.now(),
            outcome: 'backend_error',
          },
        ])
      } finally {
        setBusy(false)
      }
    },
    [location, speak]
  )

  // ── Press-to-talk ─────────────────────────────────────────────────
  const startListening = useCallback(() => {
    if (sttUnsupported || busy || listening) return
    const SpeechRecognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition
    if (!SpeechRecognition) return

    const rec = new SpeechRecognition()
    rec.lang = 'en-GB'
    rec.interimResults = false
    rec.maxAlternatives = 1
    rec.continuous = false

    rec.onresult = (event: any) => {
      const transcript = event.results?.[0]?.[0]?.transcript || ''
      submitUtterance(transcript)
    }
    rec.onerror = (event: any) => {
      setListening(false)
      if (event.error === 'no-speech' || event.error === 'aborted') {
        setErrorMsg("Didn't catch that — tap to try again.")
      } else {
        setErrorMsg(`Mic error: ${event.error}`)
      }
    }
    rec.onend = () => setListening(false)

    try {
      rec.start()
      recognitionRef.current = rec
      setListening(true)
      setErrorMsg(null)
    } catch (err) {
      setErrorMsg(`Could not start microphone: ${err}`)
    }
  }, [busy, listening, sttUnsupported, submitUtterance])

  const stopListening = useCallback(() => {
    try {
      recognitionRef.current?.stop()
    } catch {}
  }, [])

  // ── Render ────────────────────────────────────────────────────────

  if (!location) {
    const allowed = me?.allowed_locations || ['workshop', 'office', 'home']
    if (allowed.length === 0) {
      return (
        <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-3 bg-slate-950 p-6 text-center text-slate-300">
          <div className="text-lg font-semibold">Access restricted</div>
          <div className="max-w-sm text-sm text-slate-500">
            Your role ({me?.user?.role || 'unknown'}) does not have access to
            any Deek voice location. Talk to an admin to adjust your
            permissions.
          </div>
        </div>
      )
    }
    return <LocationPicker allowed={allowed} onPick={pickLocation} />
  }

  return (
    <div className="flex min-h-[100dvh] flex-col bg-slate-950 text-slate-100">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900/60 px-4 py-3 backdrop-blur">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="text-sm text-slate-400 hover:text-slate-200"
          >
            ← Home
          </Link>
          <div>
            <div className="font-mono text-lg tabular-nums">
              {now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
            </div>
            <div className="text-xs text-slate-500">
              {now.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}
            </div>
          </div>
        </div>
        <button
          onClick={() =>
            pickLocation(
              nextLocation(
                location,
                me?.allowed_locations || ['workshop', 'office', 'home'],
              ),
            )
          }
          className="rounded-full border border-slate-700 px-3 py-1 text-xs uppercase tracking-wider text-slate-300 hover:border-slate-500"
          title="Cycle location"
        >
          📍 {location}
        </button>
      </header>

      {/* Offline banner */}
      {offline && (
        <div className="bg-amber-900/40 px-4 py-2 text-center text-xs text-amber-300">
          Deek is offline — showing last-cached data. Retrying every 60s.
        </div>
      )}

      {/* Main — Morning number + Panels */}
      <main className="flex-1 overflow-y-auto px-4 py-6">
        {ambient ? (
          <>
            <MorningNumberView mn={ambient.morning_number} />
            <div className="mt-6 grid gap-4 sm:grid-cols-2">
              {ambient.panels.map(p => (
                <PanelView key={p.id} panel={p} />
              ))}
            </div>
          </>
        ) : (
          <div className="flex h-32 items-center justify-center text-slate-500">
            Loading ambient data…
          </div>
        )}

        {/* Transcript */}
        {transcript.length > 0 && (
          <div className="mt-8 space-y-2">
            <div className="text-xs uppercase tracking-wider text-slate-500">
              Conversation
            </div>
            {transcript.slice(-6).map((m, i) => (
              <div
                key={i}
                className={`rounded-lg px-3 py-2 text-sm ${
                  m.role === 'user'
                    ? 'bg-slate-800 text-slate-200'
                    : m.outcome === 'backend_error'
                    ? 'bg-rose-950/60 text-rose-200'
                    : m.outcome === 'budget_trip'
                    ? 'bg-amber-950/60 text-amber-200'
                    : 'bg-emerald-950/60 text-emerald-100'
                }`}
              >
                <div className="mb-0.5 text-[10px] uppercase tracking-wider text-slate-500">
                  {m.role === 'user' ? 'You' : 'Deek'}
                </div>
                {m.text}
              </div>
            ))}
          </div>
        )}

        {errorMsg && (
          <div className="mt-4 rounded-lg bg-rose-950/60 px-3 py-2 text-sm text-rose-200">
            {errorMsg}
          </div>
        )}
      </main>

      {/* Footer — Press-to-talk */}
      <footer className="border-t border-slate-800 bg-slate-900/60 p-4 backdrop-blur">
        {sttUnsupported ? (
          <form
            onSubmit={e => {
              e.preventDefault()
              submitUtterance(fallbackInput)
              setFallbackInput('')
            }}
            className="flex gap-2"
          >
            <input
              value={fallbackInput}
              onChange={e => setFallbackInput(e.target.value)}
              placeholder="Voice not supported — type a question"
              disabled={busy}
              className="flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm placeholder-slate-500"
            />
            <button
              type="submit"
              disabled={busy || !fallbackInput.trim()}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Ask
            </button>
          </form>
        ) : (
          <button
            onClick={listening ? stopListening : startListening}
            disabled={busy}
            className={`flex w-full items-center justify-center gap-3 rounded-2xl py-4 text-base font-semibold transition ${
              listening
                ? 'bg-rose-600 hover:bg-rose-500'
                : busy
                ? 'bg-slate-700 text-slate-400'
                : 'bg-emerald-600 hover:bg-emerald-500'
            }`}
          >
            {busy ? (
              <>
                <span className="h-3 w-3 animate-pulse rounded-full bg-slate-400" />
                Deek thinking…
              </>
            ) : listening ? (
              <>
                <span className="h-3 w-3 animate-pulse rounded-full bg-white" />
                Listening… tap to stop
              </>
            ) : (
              <>🎙 Tap to talk</>
            )}
          </button>
        )}
      </footer>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────

function LocationPicker({
  allowed,
  onPick,
}: {
  allowed: Location[]
  onPick: (loc: Location) => void
}) {
  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-6 bg-slate-950 p-6 text-slate-100">
      <div className="text-center">
        <div className="mb-2 text-2xl font-semibold">Where are you?</div>
        <div className="text-sm text-slate-400">
          Deek will prioritise the info most useful for this location.
        </div>
      </div>
      <div className="flex flex-col gap-3 w-full max-w-sm">
        {allowed.includes('workshop') && (
          <LocButton onClick={() => onPick('workshop')} emoji="🔧">
            Workshop
            <span className="text-xs text-slate-400">
              Machines · make list · stock
            </span>
          </LocButton>
        )}
        {allowed.includes('office') && (
          <LocButton onClick={() => onPick('office')} emoji="💼">
            Office
            <span className="text-xs text-slate-400">
              Email · CRM · follow-ups
            </span>
          </LocButton>
        )}
        {allowed.includes('home') && (
          <LocButton onClick={() => onPick('home')} emoji="🏡">
            Home
            <span className="text-xs text-slate-400">
              Cash · revenue · high-level
            </span>
          </LocButton>
        )}
      </div>
    </div>
  )
}

function LocButton({
  onClick,
  emoji,
  children,
}: {
  onClick: () => void
  emoji: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-4 rounded-2xl border border-slate-700 bg-slate-900 px-5 py-4 text-left hover:border-emerald-600"
    >
      <span className="text-3xl">{emoji}</span>
      <span className="flex flex-col gap-0.5 text-base font-medium">
        {children}
      </span>
    </button>
  )
}

function MorningNumberView({ mn }: { mn: MorningNumber }) {
  return (
    <div className="rounded-3xl border border-slate-800 bg-gradient-to-br from-slate-900 to-slate-950 p-6">
      <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-wider text-slate-500">
        <span>{mn.source_module}</span>
        {mn.stale && (
          <span className="rounded-full bg-amber-900/40 px-2 py-0.5 text-amber-300">
            Stale
          </span>
        )}
      </div>
      <div className="text-5xl font-semibold tracking-tight text-slate-50">
        {mn.headline}
      </div>
      {mn.subtitle && (
        <div className="mt-2 text-base text-slate-400">{mn.subtitle}</div>
      )}
    </div>
  )
}

function PanelView({ panel }: { panel: AmbientPanel }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3 text-xs uppercase tracking-wider text-slate-500">
        {panel.title}
      </div>
      <div className="space-y-2">
        {panel.items.length === 0 && (
          <div className="text-xs text-slate-500">(no data)</div>
        )}
        {panel.items.map((item, i) => (
          <div
            key={i}
            className="flex items-start justify-between gap-3 text-sm"
          >
            <div className="flex items-center gap-2">
              {item.status && <StatusDot status={item.status} />}
              <span className="text-slate-200">{item.label}</span>
            </div>
            {item.detail && (
              <span className="text-right text-xs text-slate-400">
                {item.detail}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function StatusDot({ status }: { status: string }) {
  const cls =
    status === 'running' || status === 'green'
      ? 'bg-emerald-500'
      : status === 'amber'
      ? 'bg-amber-400'
      : status === 'red'
      ? 'bg-rose-500'
      : 'bg-slate-500'
  return <span className={`inline-block h-2 w-2 rounded-full ${cls}`} />
}

function nextLocation(l: Location, allowed: Location[]): Location {
  if (allowed.length === 0) return l
  const idx = allowed.indexOf(l)
  if (idx === -1) return allowed[0]
  return allowed[(idx + 1) % allowed.length]
}
