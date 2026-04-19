/**
 * SSE proxy: POST /api/voice/chat/agent-stream → GET /chat/stream (full agent)
 *
 * The /voice PWA's Chat tab uses this endpoint when it needs tool access
 * (query_amazon_intel, search_crm, search_wiki, etc.) — unlike the
 * voice-mode /api/voice/chat/stream proxy which hits the TTS-optimised
 * tool-less endpoint.
 *
 * Session-cookie auth on the public side (same as other /api/voice/*
 * routes); injects DEEK_API_KEY for the backend call.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from '@/lib/auth'

const DEEK_API_URL =
  process.env.DEEK_API_URL ||
  process.env.CLAW_API_URL ||
  'http://localhost:8765'
const DEEK_API_KEY =
  process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || ''

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json({ error: 'not_authenticated' }, { status: 401 })
  }

  let body: any
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'invalid_json' }, { status: 400 })
  }

  const message = String(body?.content || '').trim()
  if (!message) {
    return NextResponse.json({ error: 'content_required' }, { status: 400 })
  }
  const sessionId = String(body?.session_id || `voice-chat-${Date.now()}`)
  const project = String(body?.project || 'deek')

  // /chat/stream is a GET endpoint with query params.
  const qs = new URLSearchParams({
    project,
    session_id: sessionId,
    message,
  })

  const upstream = await fetch(`${DEEK_API_URL}/chat/stream?${qs.toString()}`, {
    method: 'GET',
    headers: {
      'X-API-Key': DEEK_API_KEY,
      Accept: 'text/event-stream',
    },
  })

  if (!upstream.ok || !upstream.body) {
    return NextResponse.json(
      { error: 'upstream_failed', status: upstream.status },
      { status: 502 },
    )
  }

  // Translate the agent's SSE format (single `data:` JSON lines with
  // `type` discriminator) into the voice-chat client's expected format
  // (`event: response_delta` / `event: done` / `event: error` +
  // `data:` JSON payload). Keeps ChatView.tsx simple and consistent
  // with the voice-mode protocol.
  const encoder = new TextEncoder()
  const decoder = new TextDecoder()

  const stream = new ReadableStream({
    async start(controller) {
      const send = (eventType: string, data: any) => {
        controller.enqueue(
          encoder.encode(
            `event: ${eventType}\ndata: ${JSON.stringify(data)}\n\n`,
          ),
        )
      }

      const reader = upstream.body!.getReader()
      let buf = ''
      let completed = false

      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const blocks = buf.split('\n\n')
          buf = blocks.pop() || ''
          for (const block of blocks) {
            let dataStr = ''
            for (const l of block.split('\n')) {
              if (l.startsWith('data: ')) dataStr = l.slice(6).trim()
            }
            if (!dataStr) continue
            let evt: any
            try {
              evt = JSON.parse(dataStr)
            } catch {
              continue
            }
            const t = evt?.type
            if (t === 'tool_start') {
              send('response_delta', {
                text: `\n[🔧 ${evt.tool || 'tool'}…]\n`,
              })
            } else if (t === 'tool_end') {
              // Optional: show duration inline. Keep it short.
              send('response_delta', {
                text: `[done in ${Math.round((evt.duration_ms || 0) / 100) / 10}s]\n`,
              })
            } else if (t === 'complete') {
              const text = evt.response || ''
              if (text) send('response_delta', { text })
              send('done', {
                session_id: sessionId,
                model_used: evt.model_used || '',
                latency_ms: evt.latency_ms || 0,
                outcome: 'success',
                cost_usd: evt.cost_usd || 0,
              })
              completed = true
            } else if (t === 'error') {
              send('error', { error: evt.message || 'agent error' })
            }
            // routing / tokens / tool_queued / done — ignore (not user-facing)
          }
        }
        if (!completed) {
          send('done', {
            session_id: sessionId,
            model_used: '',
            latency_ms: 0,
            outcome: 'stream_ended',
            cost_usd: 0,
          })
        }
      } catch (err: any) {
        send('error', { error: err?.message || String(err) })
      } finally {
        controller.close()
      }
    },
  })

  return new Response(stream, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
