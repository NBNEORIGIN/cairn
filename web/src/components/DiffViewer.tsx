'use client'

interface DiffViewerProps {
  diff: string
}

export function DiffViewer({ diff }: DiffViewerProps) {
  if (!diff) return null

  const lines = diff.split('\n')

  return (
    <pre className="max-h-48 overflow-y-auto rounded-2xl border border-slate-200 bg-slate-950 p-3 font-mono text-xs leading-5 shadow-inner">
      {lines.map((line, i) => {
        let cls = 'text-slate-300'
        if (line.startsWith('+') && !line.startsWith('+++')) cls = 'text-emerald-400'
        else if (line.startsWith('-') && !line.startsWith('---')) cls = 'text-rose-400'
        else if (line.startsWith('@@')) cls = 'text-sky-400'
        else if (line.startsWith('---') || line.startsWith('+++')) cls = 'text-slate-500'
        return (
          <span key={i} className={cls + ' block'}>
            {line || ' '}
          </span>
        )
      })}
    </pre>
  )
}
