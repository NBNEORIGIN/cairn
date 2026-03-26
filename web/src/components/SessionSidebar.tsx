'use client'

import { useState, useEffect, useCallback } from 'react'

export interface Subproject {
  id: string
  project_id: string
  name: string
  display_name: string
  description: string
  created_at: string
}

export interface SessionEntry {
  session_id: string
  started_at: string | null
  last_message_at: string | null
  message_count: number
  subproject_id: string | null
  archived: boolean
}

export interface SessionSidebarProps {
  projectId: string
  activeSessionId: string
  activeSubprojectId: string | null
  onSessionSelect: (sessionId: string) => void
  onSubprojectChange: (subprojectId: string | null) => void
}

function formatSessionTime(ts: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts.replace(' ', 'T') + 'Z')
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffH = diffMs / 3_600_000
  if (diffH < 1) return `${Math.round(diffMs / 60_000)}m ago`
  if (diffH < 24) return `${Math.round(diffH)}h ago`
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

function sessionLabel(s: SessionEntry): string {
  const time = formatSessionTime(s.last_message_at)
  return `${time} · ${s.message_count} msg${s.message_count !== 1 ? 's' : ''}`
}

interface NewSubprojectFormProps {
  projectId: string
  onCreated: (sp: Subproject) => void
  onCancel: () => void
}

function NewSubprojectForm({ projectId, onCreated, onCancel }: NewSubprojectFormProps) {
  const [name, setName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !displayName.trim()) return
    setSaving(true)
    try {
      const r = await fetch('/api/subprojects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project: projectId,
          name: name.trim(),
          display_name: displayName.trim(),
          description: description.trim(),
        }),
      })
      if (r.ok) {
        const sp = await r.json()
        onCreated(sp)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mx-2 my-1 p-2 rounded bg-zinc-900 border border-zinc-700 text-xs"
    >
      <input
        autoFocus
        placeholder="name (e.g. demnurse.nbne.uk)"
        value={name}
        onChange={e => setName(e.target.value)}
        className="w-full bg-zinc-800 border border-zinc-700 text-zinc-200 rounded px-2 py-1 mb-1 text-xs"
      />
      <input
        placeholder="display name (e.g. DemNurse)"
        value={displayName}
        onChange={e => setDisplayName(e.target.value)}
        className="w-full bg-zinc-800 border border-zinc-700 text-zinc-200 rounded px-2 py-1 mb-1 text-xs"
      />
      <input
        placeholder="description (optional)"
        value={description}
        onChange={e => setDescription(e.target.value)}
        className="w-full bg-zinc-800 border border-zinc-700 text-zinc-200 rounded px-2 py-1 mb-2 text-xs"
      />
      <div className="flex gap-1">
        <button
          type="submit"
          disabled={saving || !name.trim() || !displayName.trim()}
          className="flex-1 py-1 rounded bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 text-zinc-200 text-xs"
        >
          {saving ? 'Saving…' : 'Create'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-400 text-xs"
        >
          ✕
        </button>
      </div>
    </form>
  )
}

interface SubprojectFolderProps {
  subproject: Subproject
  sessions: SessionEntry[]
  activeSessionId: string
  onSessionSelect: (id: string) => void
  isSelected: boolean
  onSelect: () => void
}

function SubprojectFolder({
  subproject,
  sessions,
  activeSessionId,
  onSessionSelect,
  isSelected,
  onSelect,
}: SubprojectFolderProps) {
  const [expanded, setExpanded] = useState(isSelected)

  useEffect(() => {
    if (isSelected) setExpanded(true)
  }, [isSelected])

  return (
    <div className="mb-0.5">
      <button
        onClick={() => {
          setExpanded(e => !e)
          onSelect()
        }}
        className={`w-full flex items-center gap-1.5 px-2 py-1.5 text-xs rounded hover:bg-zinc-800 transition-colors text-left ${
          isSelected ? 'text-zinc-200' : 'text-zinc-400'
        }`}
      >
        <span className="text-zinc-600 text-[10px]">{expanded ? '▼' : '▶'}</span>
        <span className="font-medium truncate">{subproject.display_name}</span>
        {sessions.length > 0 && (
          <span className="ml-auto text-zinc-600 text-[10px]">{sessions.length}</span>
        )}
      </button>

      {expanded && (
        <div className="ml-4 border-l border-zinc-800 pl-1">
          {sessions.length === 0 && (
            <p className="text-[10px] text-zinc-700 px-2 py-1">No sessions yet</p>
          )}
          {sessions.map(s => (
            <button
              key={s.session_id}
              onClick={() => onSessionSelect(s.session_id)}
              className={`w-full text-left px-2 py-1 text-[11px] rounded hover:bg-zinc-800 transition-colors flex items-center gap-1.5 ${
                s.session_id === activeSessionId
                  ? 'bg-zinc-800 text-zinc-200'
                  : 'text-zinc-500'
              }`}
            >
              {s.archived && (
                <span className="text-[9px] text-zinc-600 font-mono">[A]</span>
              )}
              <span className="truncate">{sessionLabel(s)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function SessionSidebar({
  projectId,
  activeSessionId,
  activeSubprojectId,
  onSessionSelect,
  onSubprojectChange,
}: SessionSidebarProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [subprojects, setSubprojects] = useState<Subproject[]>([])
  const [sessions, setSessions] = useState<SessionEntry[]>([])
  const [showNewForm, setShowNewForm] = useState(false)

  const loadData = useCallback(async () => {
    if (!projectId) return
    try {
      const [spRes, sessRes] = await Promise.all([
        fetch(`/api/subprojects?project=${encodeURIComponent(projectId)}`),
        fetch(`/api/sessions?project=${encodeURIComponent(projectId)}`),
      ])
      if (spRes.ok) {
        const d = await spRes.json()
        setSubprojects(d.subprojects || [])
      }
      if (sessRes.ok) {
        const d = await sessRes.json()
        setSessions(d.sessions || [])
      }
    } catch {
      // silently ignore network errors
    }
  }, [projectId])

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 30_000)
    return () => clearInterval(interval)
  }, [loadData])

  const handleSubprojectCreated = (sp: Subproject) => {
    setSubprojects(prev => [...prev, sp])
    setShowNewForm(false)
    onSubprojectChange(sp.id)
  }

  const sessionsForSubproject = (spId: string) =>
    sessions.filter(s => s.subproject_id === spId)

  const unscopedSessions = sessions.filter(s => !s.subproject_id)

  if (collapsed) {
    return (
      <div className="w-8 flex-shrink-0 border-r border-zinc-800 flex flex-col items-center py-3 bg-zinc-950">
        <button
          onClick={() => setCollapsed(false)}
          className="text-zinc-600 hover:text-zinc-400 text-xs"
          title="Expand sidebar"
        >
          ›
        </button>
      </div>
    )
  }

  return (
    <aside className="w-64 flex-shrink-0 border-r border-zinc-800 flex flex-col bg-zinc-950 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-zinc-800">
        <span className="text-[10px] font-bold tracking-widest text-zinc-500 uppercase">
          {projectId}
        </span>
        <button
          onClick={() => setCollapsed(true)}
          className="text-zinc-600 hover:text-zinc-400 text-xs leading-none"
          title="Collapse sidebar"
        >
          ‹
        </button>
      </div>

      {/* Session tree */}
      <div className="flex-1 overflow-y-auto py-1">
        {/* Subproject folders */}
        {subprojects.map(sp => (
          <SubprojectFolder
            key={sp.id}
            subproject={sp}
            sessions={sessionsForSubproject(sp.id)}
            activeSessionId={activeSessionId}
            onSessionSelect={onSessionSelect}
            isSelected={activeSubprojectId === sp.id}
            onSelect={() => onSubprojectChange(sp.id)}
          />
        ))}

        {/* New subproject */}
        {showNewForm ? (
          <NewSubprojectForm
            projectId={projectId}
            onCreated={handleSubprojectCreated}
            onCancel={() => setShowNewForm(false)}
          />
        ) : (
          <button
            onClick={() => setShowNewForm(true)}
            className="w-full text-left px-3 py-1 text-[11px] text-zinc-600 hover:text-zinc-400 hover:bg-zinc-900 rounded transition-colors"
          >
            + New subproject
          </button>
        )}

        {/* Unscoped sessions */}
        {unscopedSessions.length > 0 && (
          <div className="mt-2 border-t border-zinc-800 pt-1">
            <p className="px-3 py-1 text-[10px] text-zinc-600 uppercase tracking-wide">
              Unscoped sessions
            </p>
            {unscopedSessions.map(s => (
              <button
                key={s.session_id}
                onClick={() => onSessionSelect(s.session_id)}
                className={`w-full text-left px-3 py-1 text-[11px] rounded hover:bg-zinc-800 transition-colors flex items-center gap-1.5 ${
                  s.session_id === activeSessionId
                    ? 'bg-zinc-800 text-zinc-200'
                    : 'text-zinc-500'
                }`}
              >
                {s.archived && (
                  <span className="text-[9px] text-zinc-600 font-mono">[A]</span>
                )}
                <span className="truncate">{sessionLabel(s)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}
