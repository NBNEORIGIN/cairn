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
      lang: 'en-GB',
      rate: 1.0,
      pitch: 1.0,
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
    u.rate = this.opts.rate ?? 1.0
    u.pitch = this.opts.pitch ?? 1.0
    u.lang = this.opts.lang ?? 'en-GB'

    const voices = window.speechSynthesis.getVoices()
    const chosen =
      (this.opts.voiceName &&
        voices.find(v => v.name === this.opts.voiceName)) ||
      voices.find(v => v.lang?.startsWith(u.lang)) ||
      voices[0]
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
