/**
 * Proxy: GET /api/voice/briefing → GET /api/deek/briefing?user=<current user>
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
    return NextResponse.json(
      { error: 'not_authenticated' },
      { status: 401 },
    )
  }
  try {
    const res = await fetch(
      `${DEEK_API_URL}/api/deek/briefing?user=${encodeURIComponent(session.email)}`,
      {
        headers: { 'X-API-Key': DEEK_API_KEY },
        cache: 'no-store',
        signal: AbortSignal.timeout(15_000),
      },
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json({ error: 'Deek offline' }, { status: 502 })
  }
}
