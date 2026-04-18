/**
 * Proxy: GET /api/voice/briefings/pending — for the header badge.
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

export async function GET(_req: NextRequest) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json({ error: 'not_authenticated' }, { status: 401 })
  }
  try {
    const res = await fetch(
      `${DEEK_API_URL}/api/deek/briefings/pending?user=${encodeURIComponent(session.email)}&limit=10`,
      {
        headers: { 'X-API-Key': DEEK_API_KEY },
        cache: 'no-store',
        signal: AbortSignal.timeout(10_000),
      },
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json({ items: [], unseen_count: 0 }, { status: 502 })
  }
}
