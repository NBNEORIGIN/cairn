/**
 * Proxy: POST /api/deek/brief/reply
 *   → POST ${DEEK_API}/api/deek/brief/reply
 *
 * Forwards { brief_id, answers } unchanged. The backend looks up the
 * brief's user_email from memory_brief_runs, not from the client; we
 * still gate on session presence so unauthenticated callers can't
 * apply replies even with a guessed brief_id.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from '@/lib/auth'

const DEEK_API_URL =
  process.env.DEEK_API_URL ||
  process.env.CLAW_API_URL ||
  'http://localhost:8765'
const DEEK_API_KEY =
  process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || ''

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
  try {
    const res = await fetch(`${DEEK_API_URL}/api/deek/brief/reply`, {
      method: 'POST',
      headers: {
        'X-API-Key': DEEK_API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(30_000),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json({ error: 'deek_offline' }, { status: 502 })
  }
}
