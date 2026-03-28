'use client'

import { DiffViewer } from './DiffViewer'

export interface PendingToolCall {
  tool_call_id: string
  tool_name: string
  description: string
  diff_preview: string
  input: Record<string, unknown>
  risk_level: 'safe' | 'review' | 'destructive'
  auto_approve: boolean
}

interface ToolApprovalProps {
  toolCall: PendingToolCall
  onApprove: (toolCall: PendingToolCall) => void
  onReject: (toolCall: PendingToolCall) => void
}

const RISK_STYLES = {
  safe:        'border-slate-200 bg-white',
  review:      'border-amber-200 bg-amber-50/80',
  destructive: 'border-rose-200 bg-rose-50/80',
}

const RISK_ICONS = {
  safe:        '📖',
  review:      '🔧',
  destructive: '⚠️',
}

export function ToolApproval({ toolCall, onApprove, onReject }: ToolApprovalProps) {
  const riskStyle = RISK_STYLES[toolCall.risk_level] || RISK_STYLES.review
  const riskIcon  = RISK_ICONS[toolCall.risk_level]  || '🔧'

  return (
    <div className={`mt-3 rounded-[22px] border p-4 shadow-sm ${riskStyle}`}>
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <span>{riskIcon}</span>
        <span className="text-slate-800">{toolCall.tool_name}</span>
        <span className="ml-auto text-xs uppercase tracking-wide text-slate-500">
          {toolCall.risk_level}
        </span>
      </div>

      <p className="mb-3 text-xs leading-6 text-slate-600">{toolCall.description}</p>

      {toolCall.diff_preview && (
        <div className="mb-3">
          <DiffViewer diff={toolCall.diff_preview} />
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => onApprove(toolCall)}
          className="rounded-xl bg-sky-600 px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-sky-700"
        >
          Apply
        </button>
        <button
          onClick={() => onReject(toolCall)}
          className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
        >
          Reject
        </button>
      </div>
    </div>
  )
}
