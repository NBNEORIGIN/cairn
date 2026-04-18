/**
 * Sentence-buffered SpeechSynthesis queue.
 *
 * Feeds streaming text tokens in; detects sentence boundaries; serially
 * speaks each sentence via SpeechSynthesis. Used by the Voice mode so
 * Deek can start speaking the first sentence as soon as it's ready,
 * rather than waiting for the whole response to buffer.
 *
 * Usage:
 *   const q = new SpeechQueue({ onSpeakStart, onSpeakEnd, voiceName })
 *   q.push('Hello.') // speaks immediately
 *   q.push(' How are ')
 *   q.push('you?')    // "How are you?" speaks next
 *   q.flush()          // speaks any remaining buffer + marks end
 *   q.cancel()         // barge-in: stop now, drop pending
 */

export interface SpeechQueueOpts {
  voiceName?: string
  lang?: string
  rate?: number
  pitch?: number
  onSpeakStart?: () => void
  onSpeakEnd?: () => void
  onSentenceStart?: (sentence: string) => void
}

const SENTENCE_BOUNDARY = /([.!?])\s+(?=[A-Z0-9])|([.!?])$|\n\n/

export class SpeechQueue {
  private buffer = ''
  private pending: string[] = []
  private speaking = false
  private finished = false
  private cancelled = false
  private opts: SpeechQueueOpts

  constructor(opts: SpeechQueueOpts = {}) {
    this.opts = {
      // HAL 9000 defaults — deep, calm, deliberate.
      // Browser voices vary wildly; we pick the most HAL-like available
      // at speak time via chooseHalVoice() below.
      lang: 'en-GB',
      rate: 0.88,   // slower than conversational — HAL-like deliberation
      pitch: 0.7,   // lower than default — male, resonant
      ...opts,
    }
  }

  push(text: string) {
    if (this.cancelled || this.finished) return
    this.buffer += text
    this.flushBoundaries()
  }

  /** Signal no more tokens are coming; speak remaining buffer. */
  flush() {
    if (this.cancelled || this.finished) return
    this.finished = true
    const tail = this.buffer.trim()
    this.buffer = ''
    if (tail) {
      this.pending.push(tail)
    }
    this.tick()
  }

  /** Barge-in: stop speaking, drop everything, fire onSpeakEnd. */
  cancel() {
    this.cancelled = true
    this.pending = []
    this.buffer = ''
    try {
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel()
      }
    } catch {}
    if (this.speaking) {
      this.speaking = false
      this.opts.onSpeakEnd?.()
    }
  }

  private flushBoundaries() {
    // Extract complete sentences from buffer
    let changed = true
    while (changed) {
      changed = false
      const match = this.buffer.match(SENTENCE_BOUNDARY)
      if (!match || match.index === undefined) break
      const end = match.index + match[0].length
      const sentence = this.buffer.slice(0, end).trim()
      if (sentence) {
        this.pending.push(sentence)
        changed = true
      }
      this.buffer = this.buffer.slice(end)
    }
    this.tick()
  }

  private tick() {
    if (this.cancelled) return
    if (this.speaking) return
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      // No TTS — drain silently
      while (this.pending.length) this.pending.shift()
      if (this.finished) this.opts.onSpeakEnd?.()
      return
    }
    const next = this.pending.shift()
    if (!next) {
      if (this.finished) this.opts.onSpeakEnd?.()
      return
    }

    const u = new SpeechSynthesisUtterance(next)
    const chosen = chooseHalVoice(this.opts.voiceName)
    const tuned = halTuningFor(chosen?.name)
    // Per-voice tuning wins unless the caller passed explicit rate/pitch
    u.rate = this.opts.rate ?? tuned.rate
    u.pitch = this.opts.pitch ?? tuned.pitch
    u.lang = this.opts.lang ?? 'en-GB'
    if (chosen) u.voice = chosen

    u.onstart = () => {
      if (!this.speaking) {
        this.speaking = true
        this.opts.onSpeakStart?.()
      }
      this.opts.onSentenceStart?.(next)
    }
    u.onend = () => {
      if (this.cancelled) return
      // Kick the next sentence
      this.speaking = false
      if (this.pending.length === 0 && this.finished) {
        this.opts.onSpeakEnd?.()
        return
      }
      this.tick()
    }
    u.onerror = () => {
      if (this.cancelled) return
      this.speaking = false
      this.tick()
    }

    this.speaking = true
    try {
      window.speechSynthesis.speak(u)
      this.opts.onSpeakStart?.()
    } catch {
      this.speaking = false
    }
  }
}

// ── HAL-ish voice selection ─────────────────────────────────────────────────
//
// The stock SpeechSynthesis voice list varies wildly by platform. To get a
// HAL 9000 quality (deep, calm, mid-Atlantic male) we prefer specific
// voice names in priority order, falling back to any male-sounding voice,
// then any en-GB / en-US voice, then whatever's available.
//
// If the user sets a voice name explicitly (e.g. via future settings), it
// takes precedence.

const HAL_PREFERRED_VOICES = [
  // High-quality male voices across platforms
  'Microsoft Ryan Online (Natural) - English (United Kingdom)',
  'Microsoft Thomas Online (Natural) - English (France)',  // surprisingly HAL-like
  'Google UK English Male',
  'Microsoft George - English (United Kingdom)',
  'Microsoft David - English (United States)',
  'Microsoft Mark - English (United States)',
  // Apple
  'Daniel',       // en-GB male, iOS/macOS — the closest Apple voice to HAL
  'Alex',         // en-US male, macOS (compact, warm)
  'Arthur',       // en-GB male, iOS
  'Rishi',        // en-IN male — deep, measured
  'Oliver',       // en-GB male, Apple
  // Android
  'en-gb-x-gba-network',
  'en-gb-x-rjs-network',
]

// Female voices to actively DE-prioritise (HAL is male-coded)
const HAL_AVOID = /female|woman|samantha|victoria|fiona|tessa|karen|serena|martha|susan|catherine/i

export function chooseHalVoice(
  explicit?: string,
): SpeechSynthesisVoice | undefined {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    return undefined
  }
  const voices = window.speechSynthesis.getVoices()
  if (!voices.length) return undefined

  // 1. Explicit user override
  if (explicit) {
    const byName = voices.find(v => v.name === explicit)
    if (byName) return byName
  }

  // 2. Our preferred list, in order
  for (const name of HAL_PREFERRED_VOICES) {
    const found = voices.find(v => v.name === name)
    if (found) return found
  }

  // 3. Any en-GB male-coded voice (filter out obviously female ones)
  const enGbMale = voices.find(
    v => v.lang?.startsWith('en-GB') && !HAL_AVOID.test(v.name),
  )
  if (enGbMale) return enGbMale

  // 4. Any en-US male-coded voice
  const enUsMale = voices.find(
    v => v.lang?.startsWith('en-US') && !HAL_AVOID.test(v.name),
  )
  if (enUsMale) return enUsMale

  // 5. Any English voice (even female) — better than nothing
  const anyEn = voices.find(v => v.lang?.startsWith('en'))
  if (anyEn) return anyEn

  return voices[0]
}

/** List available voices — used by the voice picker in the ⋯ menu. */
export function listHalCandidates(): SpeechSynthesisVoice[] {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    return []
  }
  const voices = window.speechSynthesis.getVoices()
  // Prefer English + male-coded but still list everything English so the
  // user can override. We sort: preferred first, then male, then female.
  const english = voices.filter(v => v.lang?.startsWith('en'))
  const score = (v: SpeechSynthesisVoice) => {
    if (HAL_PREFERRED_VOICES.includes(v.name)) {
      return HAL_PREFERRED_VOICES.length - HAL_PREFERRED_VOICES.indexOf(v.name)
    }
    if (!HAL_AVOID.test(v.name)) return 5
    return 1
  }
  return english.sort((a, b) => score(b) - score(a))
}

// ── Per-voice pitch/rate tuning ─────────────────────────────────────────────
// Different voices sound best with different pitch/rate. At pitch 0.7 a
// voice like Microsoft Ryan sounds great but Google UK English Male goes
// into "chipmunk reverse" territory. These are hand-tuned.

interface HalTuning {
  rate: number
  pitch: number
}

const HAL_VOICE_TUNING: Record<string, HalTuning> = {
  // Microsoft Windows
  'Microsoft Ryan Online (Natural) - English (United Kingdom)': { rate: 0.88, pitch: 0.7 },
  'Microsoft Thomas Online (Natural) - English (France)':        { rate: 0.92, pitch: 0.75 },
  'Microsoft George - English (United Kingdom)':                 { rate: 0.9,  pitch: 0.75 },
  'Microsoft David - English (United States)':                   { rate: 0.92, pitch: 0.75 },
  'Microsoft Mark - English (United States)':                    { rate: 0.9,  pitch: 0.7 },

  // Google (Android Chrome + Chrome desktop)
  // These are quite low-pitched natively, so don't drop further
  'Google UK English Male': { rate: 0.92, pitch: 0.85 },
  'Google US English':      { rate: 0.9,  pitch: 0.8 },

  // Apple
  'Daniel': { rate: 0.88, pitch: 0.7 },   // en-GB male, iOS/macOS
  'Alex':   { rate: 0.92, pitch: 0.75 },  // en-US male, macOS
  'Arthur': { rate: 0.88, pitch: 0.7 },   // en-GB male, iOS
  'Rishi':  { rate: 0.88, pitch: 0.7 },   // en-IN male, iOS
  'Oliver': { rate: 0.88, pitch: 0.7 },   // en-GB male, Apple

  // Android system voices — already low and robotic; don't pitch down
  'en-gb-x-gba-network': { rate: 0.95, pitch: 0.9 },
  'en-gb-x-rjs-network': { rate: 0.95, pitch: 0.9 },
}

const HAL_DEFAULT_TUNING: HalTuning = { rate: 0.88, pitch: 0.75 }

export function halTuningFor(voiceName: string | undefined): HalTuning {
  if (!voiceName) return HAL_DEFAULT_TUNING
  return HAL_VOICE_TUNING[voiceName] ?? HAL_DEFAULT_TUNING
}
