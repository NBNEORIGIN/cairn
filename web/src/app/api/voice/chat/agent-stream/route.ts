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

// Read env *inside* the handler at request time, not at module load —
// otherwise Next.js inlines the build-time value and a missing build-arg
// silently bakes a stale dev key into the production bundle.
function deekConfig() {
  return {
    apiUrl:
      process.env.DEEK_API_URL ||
      process.env.CLAW_API_URL ||
      'http://localhost:8765',
    apiKey:
      process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || '',
  }
}

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
  // Vision attachments — forwarded straight through. POST path only;
  // a base64-encoded image is too large for the GET query string.
  const imageBase64: string | undefined = body?.image_base64 || undefined
  const imageMediaType: string =
    body?.image_media_type || 'image/png'

  const cfg = deekConfig()
  // Use POST /chat/stream — same SSE response shape as the GET variant
  // but accepts the message + (optional) image_base64 in JSON body so
  // we don't blow URL length limits on image attachments.
  const upstream = await fetch(`${cfg.apiUrl}/chat/stream`, {
    method: 'POST',
    headers: {
      'X-API-Key': cfg.apiKey,
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      project,
      session_id: sessionId,
      message,
      ...(imageBase64
        ? { image_base64: imageBase64, image_media_type: imageMediaType }
        : {}),
    }),
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

      // Accumulate the assistant's response so we can log it to
      // deek_voice_sessions after the stream closes — that's what the
      // chat-history sidebar (left rail on /voice) reads from. The
      // /chat/stream agent endpoint doesn't write to that table on its
      // own, so the proxy logs on its behalf.
      let assembledResponse = ''
      let finalModel = ''
      let finalLatencyMs = 0
      let finalCostUsd = 0
      let finalOutcome = 'success'

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
            if (t === 'response_delta') {
              if (evt.text) {
                assembledResponse += evt.text
                send('response_delta', { text: evt.text })
              }
            } else if (t === 'tool_start') {
              // Distinct event so the client can render a thinking pane
              // (tool name + spinner) instead of inlining "[🔧 …]" text
              // into the response body.
              send('tool_start', { tool: evt.tool || 'tool' })
            } else if (t === 'tool_end') {
              send('tool_end', {
                tool: evt.tool || 'tool',
                duration_ms: evt.duration_ms || 0,
              })
            } else if (t === 'complete') {
              finalModel = evt.model_used || ''
              finalLatencyMs = evt.latency_ms || 0
              finalCostUsd = evt.cost_usd || 0
              // Defensive: the agent's `complete` event carries a
              // `response` field. Most paths (normal final answer)
              // also stream that text via preceding `response_delta`
              // chunks, but several paths skip the stream and put
              // the text only in `complete.response` —
              //   - tool approvals (agent.py:781)
              //   - tool-queued REVIEW/DESTRUCTIVE (agent.py:1065)
              //   - GenerationStopped (agent.py:1247)
              //   - GenerationTimedOut (agent.py:1259)
              // Without this fallback the user sees a blank response.
              // Diagnosed 2026-05-07 from deek_voice_sessions rows
              // with response_len=0.
              if (!assembledResponse && evt.response) {
                const responseText = String(evt.response)
                assembledResponse = responseText
                send('response_delta', { text: responseText })
              }
              send('done', {
                session_id: sessionId,
                model_used: finalModel,
                latency_ms: finalLatencyMs,
                outcome: finalOutcome,
                cost_usd: finalCostUsd,
              })
              completed = true
            } else if (t === 'error') {
              finalOutcome = 'error'
              send('error', { error: evt.message || 'agent error' })
            }
            // routing / tokens / status / tool_queued / done — ignore.
          }
        }
        if (!completed) {
          finalOutcome = finalOutcome === 'success' ? 'stream_ended' : finalOutcome
          send('done', {
            session_id: sessionId,
            model_used: finalModel,
            latency_ms: finalLatencyMs,
            outcome: finalOutcome,
            cost_usd: finalCostUsd,
          })
        }
      } catch (err: any) {
        finalOutcome = 'error'
        send('error', { error: err?.message || String(err) })
      } finally {
        // Log to deek_voice_sessions BEFORE closing the response stream.
        // Background async work after controller.close() gets dropped by
        // the Next.js runtime when the connection ends — we lost Jo's
        // entire chat history that way on 2026-04-29. Awaiting the log
        // call before close adds <500ms to perceived response time
        // (the user already saw the streamed answer; this is just the
        // connection lingering). That's the right trade.
        try {
          await fetch(`${cfg.apiUrl}/api/deek/voice/sessions/log`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-API-Key': cfg.apiKey,
            },
            body: JSON.stringify({
              session_id: sessionId,
              user: session.email,
              location: String(body?.location || 'office'),
              question: message,
              response: assembledResponse,
              model_used: finalModel,
              latency_ms: finalLatencyMs,
              cost_usd: finalCostUsd,
              outcome: finalOutcome,
            }),
            signal: AbortSignal.timeout(4_000),
          })
        } catch {
          // logging failure must not bubble — chat already streamed.
        }

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
