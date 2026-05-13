/**
 * Proxy: GET /api/voice/inbox
 *   → GET ${DEEK_API}/api/voice/inbox?limit=&offset=&project_id=&include_reviewed=
 *
 * Lists pending Deek-drafted email replies for the inbox view.
 * Auth: session cookie at this layer; X-API-Key to the backend.
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

export async function GET(req: NextRequest) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json({ error: 'not_authenticated' }, { status: 401 })
  }
  const url = new URL(req.url)
  const search = url.search // forward all query params
  try {
    const res = await fetch(
      `${DEEK_API_URL}/api/voice/inbox${search}`,
      {
        headers: { 'X-API-Key': DEEK_API_KEY },
        cache: 'no-store',
        signal: AbortSignal.timeout(15_000),
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
