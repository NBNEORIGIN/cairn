'use client'

import { useState, useRef, useEffect, useCallback, KeyboardEvent } from 'react'
import { MessageBubble, Message, ToolCallRecord } from './MessageBubble'
import { PendingToolCall } from './ToolApproval'
import { SessionSidebar, Subproject } from './SessionSidebar'

interface Project {
  id: string
  name: string
  ready: boolean
}

interface Mention {
  type: string   // file | folder | symbol | session | core | web
  value: string
  display: string
}

interface DropdownItem {
  type: string
  value: string
  display: string
  detail?: string
}

const MODEL_OPTIONS = [
  { value: 'auto',     label: 'Auto',    detail: 'recommended',  cost: '' },
  { value: 'local',    label: '⚡ Local',  detail: 'qwen2.5-coder', cost: 'free' },
  { value: 'deepseek', label: '🌊 DeepSeek', detail: 'deepseek-chat', cost: '~$0.001' },
  { value: 'sonnet',   label: '☁ Sonnet', detail: 'claude-sonnet', cost: '~$0.005' },
  { value: 'opus',     label: '🧠 Opus',   detail: 'claude-opus',  cost: '~$0.015' },
]

function generateId() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

const TOKEN_TRIM_THRESHOLD = 40_000

function TokenBar({ tokens }: { tokens: number }) {
  const pct = Math.min(100, (tokens / TOKEN_TRIM_THRESHOLD) * 100)
  const filled = Math.round(pct / 5)
  const empty = 20 - filled
  const bar = '█'.repeat(filled) + '░'.repeat(empty)

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 border-b border-zinc-800 bg-zinc-950 text-[11px] text-zinc-500 font-mono">
      <span>Context:</span>
      <span className={tokens >= TOKEN_TRIM_THRESHOLD ? 'text-red-400' : 'text-zinc-600'}>
        {bar}
      </span>
      <span>
        {tokens.toLocaleString()} / {TOKEN_TRIM_THRESHOLD.toLocaleString()} tokens
      </span>
    </div>
  )
}

function MentionPill({
  mention,
  onRemove,
}: {
  mention: Mention
  onRemove: () => void
}) {
  const icon =
    mention.type === 'file' ? '📄' :
    mention.type === 'folder' ? '📁' :
    mention.type === 'symbol' ? '⚙' :
    mention.type === 'session' ? '💬' :
    mention.type === 'core' ? '📌' :
    '🌐'

  return (
    <span className="inline-flex items-center gap-1 bg-zinc-800 border border-zinc-600 rounded px-2 py-0.5 text-xs text-zinc-300 font-mono">
      {icon} {mention.display}
      <button
        onClick={onRemove}
        className="ml-1 text-zinc-500 hover:text-zinc-200 leading-none"
        aria-label="Remove mention"
      >
        ✕
      </button>
    </span>
  )
}

export function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState<string>('')
  const [sessionId, setSessionId] = useState<string>('')
  const [sessionCost, setSessionCost] = useState(0)
  const [localCalls, setLocalCalls] = useState(0)
  const [apiCalls, setApiCalls] = useState(0)
  const [pastedImage, setPastedImage] = useState<string | null>(null)
  const [pastedImageType, setPastedImageType] = useState<string>('image/png')

  // Subproject state
  const [subprojects, setSubprojects] = useState<Subproject[]>([])
  const [activeSubprojectId, setActiveSubprojectId] = useState<string | null>(null)

  // Token tracking
  const [sessionTokens, setSessionTokens] = useState(0)

  // Archive notification
  const [archiveBanner, setArchiveBanner] = useState<string | null>(null)

  // @ mention state
  const [mentions, setMentions] = useState<Mention[]>([])
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [mentionTab, setMentionTab] = useState<'files' | 'folders' | 'symbols' | 'sessions'>('files')
  const [mentionItems, setMentionItems] = useState<DropdownItem[]>([])
  const [mentionIndex, setMentionIndex] = useState(0)
  const mentionFetchRef = useRef<AbortController | null>(null)

  // Model selector state
  const [modelOverride, setModelOverride] = useState<string>('auto')
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const modelDropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    setSessionId(generateId())
  }, [])

  // Close model dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(e.target as Node)) {
        setModelDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    fetch('/api/chat')
      .then(r => r.json())
      .then(data => {
        const ready = (data.projects || []).filter((p: Project) => p.ready)
        setProjects(ready)
        if (ready.length > 0) {
          const saved = localStorage.getItem('claw_project')
          const found = ready.find((p: Project) => p.id === saved)
          setProjectId(found ? found.id : ready[0].id)
        }
      })
      .catch(() => {})
  }, [])

  // Load subprojects when project changes
  useEffect(() => {
    if (!projectId) return
    fetch(`/api/subprojects?project=${encodeURIComponent(projectId)}`)
      .then(r => r.json())
      .then(data => setSubprojects(data.subprojects || []))
      .catch(() => {})
  }, [projectId])

  useEffect(() => {
    if (projectId) {
      localStorage.setItem('claw_project', projectId)
      setMessages([{ id: generateId(), role: 'system', content: `Project: ${projectId}` }])
      setActiveSubprojectId(null)
      setSessionTokens(0)
    }
  }, [projectId])

  useEffect(() => {
    const handlePaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items
      if (!items) return
      for (const item of Array.from(items)) {
        if (item.type.startsWith('image/')) {
          e.preventDefault()
          const blob = item.getAsFile()
          if (!blob) return
          const reader = new FileReader()
          reader.onload = (ev) => {
            const result = ev.target?.result as string
            const base64 = result.split(',')[1]
            setPastedImage(base64)
            setPastedImageType(
              ['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(item.type)
                ? item.type
                : 'image/png',
            )
          }
          reader.readAsDataURL(blob)
          break
        }
      }
    }
    document.addEventListener('paste', handlePaste)
    return () => document.removeEventListener('paste', handlePaste)
  }, [])

  // ── @ mention dropdown fetching ─────────────────────────────────────────────

  useEffect(() => {
    if (mentionQuery === null || !projectId) {
      setMentionItems([])
      return
    }

    if (mentionFetchRef.current) mentionFetchRef.current.abort()
    const ctrl = new AbortController()
    mentionFetchRef.current = ctrl

    const q = encodeURIComponent(mentionQuery)
    const apiKey = process.env.NEXT_PUBLIC_CLAW_API_KEY || ''
    const headers: Record<string, string> = apiKey ? { 'X-API-Key': apiKey } : {}

    const fetchTab = async () => {
      try {
        if (mentionTab === 'files') {
          const r = await fetch(
            `http://localhost:8765/projects/${projectId}/files?q=${q}`,
            { headers, signal: ctrl.signal },
          )
          const data = await r.json()
          setMentionItems(
            (data.files || []).slice(0, 20).map((f: string) => ({
              type: 'file',
              value: f,
              display: f.split('/').pop() || f,
              detail: f,
            }))
          )
        } else if (mentionTab === 'folders') {
          // Use files endpoint and deduplicate top-level directories
          const r = await fetch(
            `http://localhost:8765/projects/${projectId}/files`,
            { headers, signal: ctrl.signal },
          )
          const data = await r.json()
          const dirs = new Set<string>()
          ;(data.files || []).forEach((f: string) => {
            const parts = f.split('/')
            if (parts.length > 1) dirs.add(parts[0])
          })
          setMentionItems(
            Array.from(dirs)
              .filter(d => !mentionQuery || d.toLowerCase().includes(mentionQuery.toLowerCase()))
              .slice(0, 20)
              .map(d => ({ type: 'folder', value: d, display: d, detail: d + '/' }))
          )
        } else if (mentionTab === 'symbols') {
          if (!mentionQuery) { setMentionItems([]); return }
          const r = await fetch(
            `http://localhost:8765/projects/${projectId}/symbols?q=${q}`,
            { headers, signal: ctrl.signal },
          )
          const data = await r.json()
          setMentionItems(
            (data.symbols || []).slice(0, 20).map((s: { name: string; file: string; type: string }) => ({
              type: 'symbol',
              value: s.name,
              display: s.name,
              detail: `${s.type} in ${s.file}`,
            }))
          )
        } else if (mentionTab === 'sessions') {
          const r = await fetch(`/api/sessions?project=${projectId}`, { signal: ctrl.signal })
          const data = await r.json()
          setMentionItems(
            (data.sessions || []).slice(0, 20).map((s: { session_id: string; first_message?: string; created_at?: string }) => ({
              type: 'session',
              value: s.session_id,
              display: s.session_id.slice(0, 12),
              detail: s.first_message?.slice(0, 50) || s.created_at || '',
            }))
          )
        }
        setMentionIndex(0)
      } catch {
        // aborted or failed — ignore
      }
    }

    fetchTab()
  }, [mentionQuery, mentionTab, projectId])

  const closeMentionDropdown = useCallback(() => {
    setMentionQuery(null)
    setMentionItems([])
  }, [])

  const selectMentionItem = useCallback((item: DropdownItem) => {
    setMentions(prev => {
      if (prev.some(m => m.type === item.type && m.value === item.value)) return prev
      return [...prev, { type: item.type, value: item.value, display: item.display }]
    })
    // Remove the @query from the textarea
    setInput(prev => {
      const atIdx = prev.lastIndexOf('@')
      return atIdx >= 0 ? prev.slice(0, atIdx) : prev
    })
    closeMentionDropdown()
    textareaRef.current?.focus()
  }, [closeMentionDropdown])

  // ── Input handling ──────────────────────────────────────────────────────────

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value
    setInput(val)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'

    // Detect @ trigger
    const cursor = e.target.selectionStart ?? val.length
    const textBeforeCursor = val.slice(0, cursor)
    const atMatch = textBeforeCursor.match(/@(\S*)$/)
    if (atMatch) {
      setMentionQuery(atMatch[1])
    } else {
      closeMentionDropdown()
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Navigate mention dropdown
    if (mentionQuery !== null && mentionItems.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionIndex(i => Math.min(i + 1, mentionItems.length - 1))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionIndex(i => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        if (mentionItems[mentionIndex]) selectMentionItem(mentionItems[mentionIndex])
        return
      }
      if (e.key === 'Escape') {
        closeMentionDropdown()
        return
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const newSession = useCallback(() => {
    setSessionId(generateId())
    setSessionCost(0)
    setLocalCalls(0)
    setApiCalls(0)
    setSessionTokens(0)
    setArchiveBanner(null)
    setMentions([])
    setMessages([{
      id: generateId(),
      role: 'system',
      content: `New session — project: ${projectId}`,
    }])
  }, [projectId])

  const sendMessage = useCallback(async (
    content: string,
    toolApproval?: Record<string, unknown>,
  ) => {
    if (!projectId) return

    setLoading(true)

    const imgBase64 = pastedImage
    const imgType = pastedImageType
    const imgPreview = imgBase64 ? `data:${imgType};base64,${imgBase64}` : undefined

    if (content && !toolApproval) {
      setMessages(prev => [...prev, {
        id: generateId(),
        role: 'user',
        content,
        imagePreview: imgPreview,
      }])
    }

    setPastedImage(null)

    // Capture current mentions and reset (one-shot per message)
    const currentMentions = mentions
    setMentions([])

    // Capture current model override and reset to auto
    const currentOverride = modelOverride === 'auto' ? undefined : modelOverride
    setModelOverride('auto')

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: content || '',
          project_id: projectId,
          session_id: sessionId,
          channel: 'web',
          tool_approval: toolApproval || null,
          image_base64: imgBase64 || undefined,
          image_media_type: imgType,
          subproject_id: activeSubprojectId || undefined,
          mentions: currentMentions,
          model_override: currentOverride,
        }),
      })

      const data = await res.json()

      if (data.error) {
        setMessages(prev => [...prev, {
          id: generateId(),
          role: 'assistant',
          content: `⚠ ${data.error}`,
        }])
      } else {
        const isLocal = (data.model_used || '').toLowerCase().includes('qwen')
        if (isLocal) {
          setLocalCalls(c => c + 1)
        } else if (data.model_used) {
          setApiCalls(c => c + 1)
          setSessionCost(c => c + (data.cost_usd || 0))
        }

        if (data.tokens_used) {
          setSessionTokens(t => t + (data.tokens_used as number))
        }

        const meta = data.metadata || {}
        if (meta.session_archived) {
          setArchiveBanner(meta.archive_summary || 'Session archived — summary added to context')
          newSession()
        }

        setMessages(prev => [...prev, {
          id: generateId(),
          role: 'assistant',
          content: data.content || '(no response)',
          modelUsed: data.model_used,
          costUsd: data.cost_usd,
          modelRouting: meta.model_routing || 'auto',
          pendingToolCall: data.pending_tool_call || null,
          toolCalls: (data.tool_calls || []) as ToolCallRecord[],
        }])
      }
    } catch {
      setMessages(prev => {
        const updated = [...prev]
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].role === 'assistant' && updated[i].pendingToolCall) {
            updated[i] = { ...updated[i], pendingToolCall: null }
            break
          }
        }
        return [...updated, {
          id: generateId(),
          role: 'assistant',
          content: `⚠ Network error — API unreachable. Restart uvicorn and refresh.`,
        }]
      })
    } finally {
      setLoading(false)
    }
  }, [projectId, sessionId, pastedImage, pastedImageType, activeSubprojectId, mentions, modelOverride, newSession])

  const handleSubmit = () => {
    const text = input.trim()
    if ((!text && !pastedImage) || loading) return
    setInput('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
    sendMessage(text || 'What do you see in this screenshot?')
  }

  const handleApprove = useCallback((toolCall: PendingToolCall) => {
    sendMessage('', {
      tool_call_id: toolCall.tool_call_id,
      tool_name: toolCall.tool_name,
      input: toolCall.input,
      approved: true,
    })
  }, [sendMessage])

  const handleReject = useCallback((toolCall: PendingToolCall) => {
    sendMessage('', {
      tool_call_id: toolCall.tool_call_id,
      tool_name: toolCall.tool_name,
      input: toolCall.input,
      approved: false,
    })
  }, [sendMessage])

  const activeSubproject = subprojects.find(sp => sp.id === activeSubprojectId)
  const selectedModel = MODEL_OPTIONS.find(m => m.value === modelOverride) || MODEL_OPTIONS[0]

  return (
    <div className="flex h-full">
      {/* Session sidebar */}
      <SessionSidebar
        projectId={projectId}
        activeSessionId={sessionId}
        activeSubprojectId={activeSubprojectId}
        onSessionSelect={(sid) => {
          setSessionId(sid)
          setSessionTokens(0)
          setArchiveBanner(null)
          setMessages([{ id: generateId(), role: 'system', content: `Resumed session: ${sid}` }])
        }}
        onSubprojectChange={(spId) => {
          setActiveSubprojectId(spId)
        }}
      />

      {/* Main chat */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 bg-zinc-950">
          {/* Project dropdown */}
          <div className="flex items-center gap-2">
            <label className="text-[10px] text-zinc-600 uppercase tracking-wide">Project</label>
            <select
              value={projectId}
              onChange={e => setProjectId(e.target.value)}
              className="bg-zinc-900 border border-zinc-700 text-zinc-200 text-xs rounded px-2 py-1"
            >
              {projects.length === 0 && <option value="">No projects</option>}
              {projects.map(p => (
                <option key={p.id} value={p.id}>{p.id}</option>
              ))}
            </select>
          </div>

          {/* Subproject dropdown */}
          {subprojects.length > 0 && (
            <div className="flex items-center gap-2">
              <label className="text-[10px] text-zinc-600 uppercase tracking-wide">Client</label>
              <select
                value={activeSubprojectId || ''}
                onChange={e => setActiveSubprojectId(e.target.value || null)}
                className="bg-zinc-900 border border-zinc-700 text-zinc-200 text-xs rounded px-2 py-1"
              >
                <option value="">All clients</option>
                {subprojects.map(sp => (
                  <option key={sp.id} value={sp.id}>{sp.display_name}</option>
                ))}
              </select>
            </div>
          )}

          <div className="ml-auto flex items-center gap-3">
            <button
              onClick={newSession}
              className="text-xs py-1 px-2 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors"
            >
              New session
            </button>
            <div className="text-xs text-zinc-600">
              ${sessionCost.toFixed(4)} · {localCalls}L/{apiCalls}A
            </div>
            <div className="text-zinc-700 font-mono text-[10px]">
              {sessionId.slice(0, 10)}…
            </div>
          </div>
        </div>

        {/* Token usage bar */}
        {sessionTokens > 0 && <TokenBar tokens={sessionTokens} />}

        {/* Archive notification banner */}
        {archiveBanner && (
          <div className="flex items-center justify-between px-4 py-2 bg-zinc-800 border-b border-zinc-700 text-xs text-zinc-300">
            <span>Session archived — summary added to context</span>
            <button
              onClick={() => setArchiveBanner(null)}
              className="text-zinc-500 hover:text-zinc-300 ml-4"
            >
              ✕
            </button>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {messages.map(msg => (
            <MessageBubble
              key={msg.id}
              message={msg}
              onApprove={handleApprove}
              onReject={handleReject}
            />
          ))}

          {loading && (
            <div className="text-sm text-zinc-500 italic animate-pulse mb-3">
              {activeSubproject ? `[${activeSubproject.display_name}] ` : ''}Thinking…
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-zinc-800 bg-zinc-950 px-4 py-3">
          {/* Image preview */}
          {pastedImage && (
            <div className="relative mb-2 inline-block">
              <img
                src={`data:${pastedImageType};base64,${pastedImage}`}
                alt="Pasted screenshot"
                className="max-h-28 rounded border border-zinc-600"
              />
              <button
                onClick={() => setPastedImage(null)}
                className="absolute -top-2 -right-2 bg-zinc-700 hover:bg-zinc-600 rounded-full w-5 h-5 text-xs flex items-center justify-center text-zinc-300 leading-none"
              >
                ×
              </button>
            </div>
          )}

          {/* Context pills — pinned @ mentions */}
          {mentions.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {mentions.map((m, i) => (
                <MentionPill
                  key={`${m.type}:${m.value}`}
                  mention={m}
                  onRemove={() => setMentions(prev => prev.filter((_, j) => j !== i))}
                />
              ))}
            </div>
          )}

          {/* @ mention dropdown */}
          {mentionQuery !== null && (
            <div className="relative mb-2">
              <div className="absolute bottom-0 left-0 right-0 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50 overflow-hidden">
                {/* Tabs */}
                <div className="flex border-b border-zinc-800">
                  {(['files', 'folders', 'symbols', 'sessions'] as const).map(tab => (
                    <button
                      key={tab}
                      onClick={() => { setMentionTab(tab); setMentionIndex(0) }}
                      className={`flex-1 py-1.5 text-[11px] font-medium transition-colors capitalize
                        ${mentionTab === tab
                          ? 'text-zinc-100 bg-zinc-800'
                          : 'text-zinc-500 hover:text-zinc-300'
                        }`}
                    >
                      {tab}
                    </button>
                  ))}
                </div>

                {/* Items */}
                {mentionItems.length === 0 ? (
                  <div className="px-3 py-2 text-xs text-zinc-600 italic">
                    {mentionQuery ? `No ${mentionTab} matching "${mentionQuery}"` : `Type to search ${mentionTab}…`}
                  </div>
                ) : (
                  <div className="max-h-48 overflow-y-auto">
                    {mentionItems.map((item, i) => (
                      <button
                        key={`${item.type}:${item.value}`}
                        onClick={() => selectMentionItem(item)}
                        className={`w-full text-left px-3 py-1.5 flex items-center gap-2 text-xs transition-colors
                          ${i === mentionIndex ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-300 hover:bg-zinc-800'}`}
                      >
                        <span className="font-mono text-zinc-200 truncate">{item.display}</span>
                        {item.detail && (
                          <span className="text-zinc-600 truncate text-[10px] ml-auto shrink-0 max-w-[40%]">
                            {item.detail}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}

                <div className="px-3 py-1 border-t border-zinc-800 text-[10px] text-zinc-700">
                  ↑↓ navigate · Enter to add · Esc to close
                </div>
              </div>
            </div>
          )}

          {/* Input row */}
          <div className="flex gap-2 items-end">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              placeholder={
                projectId
                  ? activeSubproject
                    ? `Ask CLAW about ${activeSubproject.display_name}… (@ to pin context)`
                    : `Ask CLAW about ${projectId}… (@ to pin context)`
                  : 'Select a project first'
              }
              disabled={!projectId || loading}
              rows={1}
              className="flex-1 bg-zinc-900 border border-zinc-700 text-zinc-100 text-sm rounded-lg px-3 py-2 resize-none min-h-[38px] max-h-[120px] focus:outline-none focus:border-zinc-500 placeholder:text-zinc-600 disabled:opacity-50"
            />

            {/* Model selector */}
            <div ref={modelDropdownRef} className="relative shrink-0">
              <button
                onClick={() => setModelDropdownOpen(o => !o)}
                className={`h-[38px] px-2.5 text-xs rounded-lg border transition-colors flex items-center gap-1
                  ${modelOverride !== 'auto'
                    ? 'bg-zinc-700 border-zinc-500 text-zinc-100'
                    : 'bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-zinc-500'
                  }`}
                title="Select model for this message"
              >
                {selectedModel.label} <span className="text-zinc-600">▾</span>
              </button>

              {modelDropdownOpen && (
                <div className="absolute bottom-full right-0 mb-1 w-52 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-50 overflow-hidden">
                  {MODEL_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => { setModelOverride(opt.value); setModelDropdownOpen(false) }}
                      className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between transition-colors
                        ${modelOverride === opt.value ? 'bg-zinc-700 text-zinc-100' : 'text-zinc-300 hover:bg-zinc-800'}`}
                    >
                      <span className="flex items-center gap-2">
                        {modelOverride === opt.value && <span className="text-zinc-400">●</span>}
                        {modelOverride !== opt.value && <span className="text-zinc-700">○</span>}
                        <span>{opt.label}</span>
                        <span className="text-zinc-600 text-[10px]">{opt.detail}</span>
                      </span>
                      {opt.cost && (
                        <span className="text-zinc-600 text-[10px] ml-2 shrink-0">{opt.cost}</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <button
              onClick={handleSubmit}
              disabled={(!input.trim() && !pastedImage) || loading || !projectId}
              className="h-[38px] px-4 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 text-white text-sm rounded-lg transition-colors shrink-0"
            >
              Send
            </button>
          </div>
          <p className="text-xs text-zinc-700 mt-1.5">
            Enter to send · Shift+Enter for newline · @ to pin context
          </p>
        </div>
      </div>
    </div>
  )
}
