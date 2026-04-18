'use client'

/**
 * useVoiceLoop — orchestrates the continuous voice mode state machine.
 *
 * States: idle → listening → thinking → speaking → listening (loop)
 *
 * Uses:
 *   - Web Speech Recognition for STT (browser-native)
 *   - /api/voice/chat/stream for the LLM response (SSE)
 *   - SpeechQueue for sentence-buffered TTS
 *
 * Barge-in: if the user starts speaking while Deek is speaking, we cancel
 * TTS + abort the stream and capture the new utterance.
 *
 * The hook is self-contained — it owns the recognition instance, the
 * SpeechQueue, the AbortController for the fetch, and the state enum.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { SpeechQueue } from '@/lib/speechQueue'

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking'

export interface VoiceLoopTurn {
  role: 'user' | 'deek'
  text: string
  at: number
  outcome?: string
}

export interface VoiceLoopOpts {
  location: string
  sessionId: string | null
  onTurn: (turn: VoiceLoopTurn) => void
  onSessionId: (id: string) => void
  onError?: (msg: string) => void
}

export function useVoiceLoop(opts: VoiceLoopOpts) {
  const [state, setState] = useState<VoiceState>('idle')
  const [interim, setInterim] = useState<string>('')
  const [partialResponse, setPartialResponse] = useState<string>('')
  const [running, setRunning] = useState(false)
  // Driven by Web Speech's onsoundstart/onsoundend — used by HalEye
  // to pulse when the user is actually making sound. Avoids holding
  // a second getUserMedia stream which was blocking recognition on
  // Android Chrome.
  const [soundDetected, setSoundDetected] = useState(false)

  const recognitionRef = useRef<any>(null)
  const queueRef = useRef<SpeechQueue | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const runningRef = useRef(false)
  const stateRef = useRef<VoiceState>('idle')
  const sessionIdRef = useRef<string | null>(opts.sessionId)

  useEffect(() => {
    sessionIdRef.current = opts.sessionId
  }, [opts.sessionId])

  useEffect(() => {
    stateRef.current = state
  }, [state])

  const setS = useCallback((s: VoiceState) => {
    stateRef.current = s
    setState(s)
  }, [])

  // ── TTS queue + stream handling ────────────────────────────────────
  const speakStream = useCallback(
    async (utterance: string) => {
      opts.onTurn({ role: 'user', text: utterance, at: Date.now() })
      setS('thinking')
      setPartialResponse('')
      abortRef.current = new AbortController()

      // Fresh SpeechQueue each turn
      queueRef.current?.cancel()
      let preferredVoice: string | undefined
      try {
        preferredVoice = localStorage.getItem('deek.voice.preferred') || undefined
      } catch {}
      const q = new SpeechQueue({
        voiceName: preferredVoice,
        onSpeakStart: () => setS('speaking'),
        onSpeakEnd: () => {
          // After speaking, loop back to listening if still running
          if (runningRef.current) {
            setS('listening')
            startRecognition()
          } else {
            setS('idle')
          }
        },
      })
      queueRef.current = q

      try {
        const res = await fetch('/api/voice/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            content: utterance,
            location: opts.location,
            session_id: sessionIdRef.current,
          }),
          signal: abortRef.current.signal,
        })

        if (res.status === 401) {
          window.location.href = '/voice/login?callbackUrl=/voice'
          return
        }
        if (!res.ok || !res.body) {
          const err = `Stream failed HTTP ${res.status}`
          opts.onError?.(err)
          opts.onTurn({
            role: 'deek',
            text: err,
            at: Date.now(),
            outcome: 'backend_error',
          })
          setS('idle')
          return
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        let fullText = ''

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })

          // Parse SSE blocks separated by \n\n
          const blocks = buf.split('\n\n')
          buf = blocks.pop() || ''

          for (const block of blocks) {
            const lines = block.split('\n')
            let eventType = 'message'
            let dataStr = ''
            for (const l of lines) {
              if (l.startsWith('event: ')) eventType = l.slice(7).trim()
              else if (l.startsWith('data: ')) dataStr = l.slice(6).trim()
            }
            if (!dataStr) continue
            let data: any
            try {
              data = JSON.parse(dataStr)
            } catch {
              continue
            }
            if (eventType === 'response_delta') {
              const t = data.text || ''
              fullText += t
              setPartialResponse(fullText)
              q.push(t)
            } else if (eventType === 'done') {
              if (data.session_id) {
                sessionIdRef.current = data.session_id
                opts.onSessionId(data.session_id)
              }
              opts.onTurn({
                role: 'deek',
                text: fullText.trim(),
                at: Date.now(),
                outcome: data.outcome,
              })
              q.flush()
            } else if (eventType === 'error') {
              opts.onError?.(data.error || 'stream error')
              q.cancel()
              setS('idle')
            }
          }
        }

        q.flush()
      } catch (err: any) {
        if (err?.name === 'AbortError') {
          return
        }
        opts.onError?.(err?.message || String(err))
        setS('idle')
      }
    },
    [opts, setS],
  )

  // ── Speech recognition ─────────────────────────────────────────────
  const startRecognition = useCallback(() => {
    if (typeof window === 'undefined') return
    const SR: any =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition
    if (!SR) {
      opts.onError?.('Speech recognition not supported in this browser')
      setRunning(false)
      runningRef.current = false
      return
    }

    // If something's already running, stop it first
    try {
      recognitionRef.current?.stop()
    } catch {}

    const rec = new SR()
    rec.lang = 'en-GB'
    rec.interimResults = true
    rec.maxAlternatives = 1
    rec.continuous = false

    let finalText = ''
    rec.onsoundstart = () => setSoundDetected(true)
    rec.onsoundend = () => setSoundDetected(false)
    rec.onaudioend = () => setSoundDetected(false)
    rec.onresult = (event: any) => {
      let interimText = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const r = event.results[i]
        if (r.isFinal) {
          finalText += r[0].transcript
        } else {
          interimText += r[0].transcript
        }
      }
      if (interimText) setInterim(interimText)

      // Barge-in: user spoke while Deek was talking
      if (stateRef.current === 'speaking') {
        queueRef.current?.cancel()
        abortRef.current?.abort()
        setS('listening')
      }
    }
    rec.onerror = (event: any) => {
      const code = event.error || 'unknown'
      if (code === 'no-speech' || code === 'aborted') {
        // Loop: try again
        if (runningRef.current && stateRef.current === 'listening') {
          setTimeout(() => {
            if (runningRef.current) startRecognition()
          }, 200)
        }
        return
      }
      // Surface specific, human-readable messages
      if (code === 'not-allowed' || code === 'service-not-allowed') {
        opts.onError?.(
          'Microphone permission denied. Tap the lock icon in the address ' +
          'bar, allow microphone, then tap Start voice mode again.',
        )
      } else if (code === 'audio-capture') {
        opts.onError?.(
          'No microphone detected. Check device has a working mic and no ' +
          'other app is using it.',
        )
      } else if (code === 'network') {
        opts.onError?.(
          'Speech recognition network error. Check connection and retry.',
        )
      } else {
        opts.onError?.(`Mic: ${code}`)
      }
      // Stop the loop so the user isn't stuck in a broken state
      runningRef.current = false
      setRunning(false)
      setS('idle')
    }
    rec.onend = () => {
      setInterim('')
      setSoundDetected(false)
      const text = finalText.trim()
      finalText = ''
      if (text && runningRef.current) {
        speakStream(text)
      } else if (runningRef.current && stateRef.current === 'listening') {
        // No result but still listening — restart
        setTimeout(() => {
          if (runningRef.current && stateRef.current === 'listening') {
            startRecognition()
          }
        }, 300)
      }
    }
    recognitionRef.current = rec
    try {
      rec.start()
      setS('listening')
    } catch (err: any) {
      const msg = err?.message || String(err)
      if (/already started|InvalidStateError/i.test(msg)) {
        // Benign — another start is already in flight
        return
      }
      opts.onError?.(`Could not start microphone: ${msg}`)
      runningRef.current = false
      setRunning(false)
      setS('idle')
    }
  }, [opts, setS, speakStream])

  // ── Public controls ────────────────────────────────────────────────
  const start = useCallback(() => {
    runningRef.current = true
    setRunning(true)
    startRecognition()
  }, [startRecognition])

  const stop = useCallback(() => {
    runningRef.current = false
    setRunning(false)
    try {
      recognitionRef.current?.stop()
    } catch {}
    queueRef.current?.cancel()
    abortRef.current?.abort()
    setS('idle')
  }, [setS])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      runningRef.current = false
      try {
        recognitionRef.current?.stop()
      } catch {}
      queueRef.current?.cancel()
      abortRef.current?.abort()
    }
  }, [])

  return {
    state,
    running,
    interim,
    partialResponse,
    soundDetected,
    start,
    stop,
  }
}
