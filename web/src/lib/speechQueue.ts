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
    u.rate = this.opts.rate ?? 0.88
    u.pitch = this.opts.pitch ?? 0.7
    u.lang = this.opts.lang ?? 'en-GB'

    const chosen = chooseHalVoice(this.opts.voiceName)
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

/** List available voices — handy for a future settings panel. */
export function listHalCandidates(): SpeechSynthesisVoice[] {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    return []
  }
  const voices = window.speechSynthesis.getVoices()
  // Prefer English + male-coded
  return voices
    .filter(v => v.lang?.startsWith('en'))
    .filter(v => !HAL_AVOID.test(v.name))
}
