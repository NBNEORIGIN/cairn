/**
 * SSE proxy: POST /api/voice/chat/stream → POST /api/deek/chat/voice/stream
 *
 * Streams Ollama response_delta events straight through to the client.
 * Re-verifies session + ACL before opening the upstream stream.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getServerSession, locationDenyReason } from '@/lib/auth'

// Read env at request time so Next.js can't inline a stale build-time value.
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

  const location = String(body?.location || '')
  const deny = locationDenyReason(session, location)
  if (deny) {
    return NextResponse.json(
      { error: 'forbidden', reason: deny },
      { status: 403 },
    )
  }

  const payload = { ...body, user: session.email }

  // Open the upstream SSE stream and proxy it straight through.
  const cfg = deekConfig()
  const upstream = await fetch(`${cfg.apiUrl}/api/deek/chat/voice/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': cfg.apiKey,
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(payload),
    // No timeout — the caller controls duration via AbortController
  })

  if (!upstream.ok || !upstream.body) {
    return NextResponse.json(
      { error: 'upstream_failed', status: upstream.status },
      { status: 502 },
    )
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
