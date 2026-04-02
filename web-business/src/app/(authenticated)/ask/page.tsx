'use client'

import { useEffect, useRef, useState, useCallback, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
}

// ---- Markdown renderer (basic) --------------------------------------------

function renderMarkdown(text: string): string {
  return text
    // Bold
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    // Unordered list items
    .replace(/^[-*]\s(.+)$/gm, '<li>$1</li>')
    // Numbered list items
    .replace(/^\d+\.\s(.+)$/gm, '<li>$1</li>')
    // Wrap consecutive <li> in <ul>
    .replace(/(<li>.*?<\/li>(\n|$))+/g, (match) => `<ul class="list-disc list-inside space-y-1 my-2">${match}</ul>`)
    // Paragraphs: double newlines
    .replace(/\n\n/g, '</p><p>')
    // Single newlines
    .replace(/\n/g, '<br />')
}

function AssistantBubble({ content }: { content: string }) {
  return (
    <div
      className="prose prose-sm max-w-none text-slate-800 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:text-slate-700"
      dangerouslySetInnerHTML={{ __html: `<p>${renderMarkdown(content)}</p>` }}
    />
  )
}

// ---- Session ID -----------------------------------------------------------

function generateSessionId() {
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

// ---- Inner component (uses useSearchParams) --------------------------------

function AskPageInner() {
  const searchParams = useSearchParams()
  const prefill = searchParams.get('q') ?? ''

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState(prefill)
  const [sending, setSending] = useState(false)
  const sessionId = useRef<string>(generateSessionId())
  const bottomRef = useRef<HTMLDivElement>(null)
  const esRef = useRef<EventSource | null>(null)

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || sending) return

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setSending(true)

    // Close any existing EventSource
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }

    // Create placeholder assistant message
    const assistantId = `a-${Date.now()}`
    setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '' }])

    // Build SSE URL
    const params = new URLSearchParams({
      project: 'nbne',
      session_id: sessionId.current,
      message: text,
      channel: 'web',
    })

    const es = new EventSource(`/api/chat/stream?${params.toString()}`)
    esRef.current = es

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        // Accept any event that carries response text
        const chunk: string =
          parsed.content ?? parsed.text ?? parsed.delta ?? parsed.message ?? ''
        if (chunk) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + chunk } : m
            )
          )
        }
        // Stream complete signals
        if (parsed.done || parsed.type === 'done' || parsed.finish_reason) {
          es.close()
          esRef.current = null
          setSending(false)
        }
      } catch {
        // Non-JSON event — treat raw data as text chunk
        if (event.data && event.data !== '[DONE]') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + event.data } : m
            )
          )
        }
        if (event.data === '[DONE]') {
          es.close()
          esRef.current = null
          setSending(false)
        }
      }
    }

    es.onerror = () => {
      es.close()
      esRef.current = null
      setSending(false)
    }
  }, [input, sending])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px-3rem)] max-w-3xl mx-auto">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto space-y-4 pb-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-slate-400">
              Ask anything about the business — stock, orders, processes, financials.
            </p>
          </div>
        )}

        {messages.map((msg) =>
          msg.role === 'user' ? (
            <div key={msg.id} className="flex justify-end">
              <div className="max-w-[75%] bg-indigo-600 text-white text-sm px-4 py-3 rounded-2xl rounded-tr-sm">
                {msg.content}
              </div>
            </div>
          ) : (
            <div key={msg.id} className="flex justify-start">
              <div className="max-w-[75%] bg-white border border-slate-200 text-slate-800 text-sm px-4 py-3 rounded-2xl rounded-tl-sm shadow-sm">
                {msg.content ? (
                  <AssistantBubble content={msg.content} />
                ) : (
                  <span className="text-slate-400 animate-pulse">Thinking…</span>
                )}
              </div>
            </div>
          )
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="bg-white border border-slate-200 rounded-xl p-3 flex gap-3 items-end shadow-sm">
        <textarea
          className="flex-1 resize-none text-sm text-slate-800 placeholder-slate-400 focus:outline-none min-h-[40px] max-h-[160px] overflow-y-auto"
          rows={1}
          placeholder="Ask anything…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={sending}
        />
        <button
          onClick={sendMessage}
          disabled={sending || !input.trim()}
          className="flex-shrink-0 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Send
        </button>
      </div>
    </div>
  )
}

// ---- Page export ----------------------------------------------------------

export default function AskPage() {
  return (
    <Suspense fallback={<div className="text-sm text-slate-400">Loading…</div>}>
      <AskPageInner />
    </Suspense>
  )
}
