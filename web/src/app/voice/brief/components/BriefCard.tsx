'use client'

/**
 * BriefCard — today's brief at the top of /voice/brief.
 *
 * Two states:
 *   * unanswered → render each question with an inline reply box;
 *                  one Submit button submits all populated answers.
 *   * answered   → render the brief with the captured answers below.
 *
 * The PWA binds each text to its question_id, so the backend skips
 * the LLM normaliser and goes straight to _classify() →
 * apply_reply(). Same memory-write semantics as email replies.
 */
import { useState } from 'react'
import { Send, Check, AlertCircle } from 'lucide-react'

interface BriefQuestion {
  id: string
  category: string
  text: string
  reply_format: string
}

interface BriefAnswer {
  question_id: string | null
  category: string
  verdict: string
  correction_text: string
}

export interface Brief {
  brief_id: string
  date: string | null
  subject: string
  questions: BriefQuestion[]
  answered: boolean
  answers: BriefAnswer[]
}

interface Props {
  brief: Brief
  onSubmitted?: () => void
}

const CATEGORY_LABEL: Record<string, string> = {
  belief_audit: 'Belief audit',
  gist_validation: 'Gist check',
  salience_calibration: 'Salience check',
  open_ended: 'Open',
  research_prompt: 'Research prompt',
  hr_pulse: 'HR pulse',
  finance_check: 'Finance check',
  d2c_observation: 'D2C observation',
  production_quality: 'Production quality',
  equipment_health: 'Equipment',
  technical_solve: 'Technical solve',
}

export function BriefCard({ brief, onSubmitted }: Props) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sentSummary, setSentSummary] = useState<string | null>(null)

  const update = (qid: string, text: string) =>
    setDrafts(d => ({ ...d, [qid]: text }))

  const submit = async () => {
    setError(null)
    const answers = brief.questions
      .map(q => ({ question_id: q.id, text: (drafts[q.id] || '').trim() }))
      .filter(a => a.text.length > 0)
    if (answers.length === 0) {
      setError('Type at least one answer first.')
      return
    }
    setSubmitting(true)
    try {
      const res = await fetch('/api/deek/brief/reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ brief_id: brief.brief_id, answers }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(`Reply failed: ${data?.detail || data?.error || res.status}`)
        return
      }
      const processed = data?.applied_summary?.answers_processed || []
      setSentSummary(
        `Sent ${answers.length} ${
          answers.length === 1 ? 'answer' : 'answers'
        } — ${processed.length} applied.`,
      )
      onSubmitted?.()
    } catch (err: any) {
      setError(err?.message || 'Network error')
    } finally {
      setSubmitting(false)
    }
  }

  if (brief.answered) {
    return (
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
        <div className="mb-3 flex items-center gap-2 text-xs text-emerald-800">
          <Check size={14} />
          <span className="font-medium">Brief sent — replied</span>
          {brief.date && <span className="text-emerald-600">· {brief.date}</span>}
        </div>
        <div className="space-y-3">
          {brief.questions.map(q => {
            const a = brief.answers.find(x => x.question_id === q.id)
            return (
              <div key={q.id} className="rounded-lg bg-white px-3 py-2 ring-1 ring-gray-200">
                <div className="mb-1 text-xs uppercase tracking-wider text-gray-500">
                  {CATEGORY_LABEL[q.category] || q.category}
                </div>
                <div className="mb-2 text-sm text-gray-700">{q.text}</div>
                {a && a.correction_text ? (
                  <div className="rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-900 ring-1 ring-gray-200">
                    {a.correction_text}
                  </div>
                ) : a && a.verdict ? (
                  <div className="text-xs font-medium text-emerald-700">
                    {a.verdict.toUpperCase()}
                  </div>
                ) : (
                  <div className="text-xs text-gray-400">(no answer)</div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  if (sentSummary) {
    return (
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
        <div className="flex items-center gap-2">
          <Check size={14} /> {sentSummary}
        </div>
        <div className="mt-2 text-xs text-emerald-600">
          Refreshing in a moment will show the captured answers.
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between text-xs text-gray-500">
        <span>{brief.subject || `Brief — ${brief.date || ''}`}</span>
        <span>
          {brief.questions.length} question
          {brief.questions.length === 1 ? '' : 's'}
        </span>
      </div>

      <div className="space-y-4">
        {brief.questions.map(q => (
          <div key={q.id} className="rounded-lg bg-gray-50 px-3 py-3 ring-1 ring-gray-200">
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="uppercase tracking-wider text-gray-500">
                {CATEGORY_LABEL[q.category] || q.category}
              </span>
              {q.reply_format && (
                <span className="text-gray-400">{q.reply_format}</span>
              )}
            </div>
            <div className="mb-2 whitespace-pre-wrap text-sm text-gray-800">
              {q.text}
            </div>
            <textarea
              value={drafts[q.id] || ''}
              onChange={e => update(q.id, e.target.value)}
              placeholder="Plain English — I'll figure out the rest."
              rows={2}
              className="w-full resize-y rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-400"
              disabled={submitting}
            />
          </div>
        ))}
      </div>

      {error && (
        <div className="mt-3 flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">
          <AlertCircle size={14} />
          {error}
        </div>
      )}

      <div className="mt-4 flex items-center justify-end">
        <button
          onClick={submit}
          disabled={submitting}
          className="flex items-center gap-2 rounded-md bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-800 disabled:opacity-50"
        >
          <Send size={14} />
          {submitting ? 'Sending…' : 'Send replies'}
        </button>
      </div>
    </div>
  )
}
