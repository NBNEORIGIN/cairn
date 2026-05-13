/**
 * Proxy: POST /api/voice/inbox/{id}/stage
 *   → POST ${DEEK_API}/api/voice/inbox/{id}/stage
 *
 * Sends the draft to sales@nbnesigns.co.uk for manual review-and-send.
 * Body: { staged_by?: string, dry_run?: boolean }.
 *
 * Auto-injects staged_by from the session email so the audit trail
 * records who actioned the draft without the client having to.
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

export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json({ error: 'not_authenticated' }, { status: 401 })
  }
  const body = await req.json().catch(() => ({}))
  // staged_by always comes from the session — client can't spoof it
  body.staged_by = session.email
  try {
    const res = await fetch(
      `${DEEK_API_URL}/api/voice/inbox/${encodeURIComponent(params.id)}/stage`,
      {
        method: 'POST',
        headers: {
          'X-API-Key': DEEK_API_KEY,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(30_000),
      },
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (e: any) {
    return NextResponse.json(
      { error: 'upstream_failed', detail: e?.message || String(e) },
      { status: 502 },
    )
  }
}
