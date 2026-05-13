/**
 * Proxy: GET /api/voice/inbox/{id}
 *   → GET ${DEEK_API}/api/voice/inbox/{id}
 *
 * Detail panel for a single pending draft.
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

export async function GET(
  _req: NextRequest,
  { params }: { params: { id: string } },
) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json({ error: 'not_authenticated' }, { status: 401 })
  }
  try {
    const res = await fetch(
      `${DEEK_API_URL}/api/voice/inbox/${encodeURIComponent(params.id)}`,
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
