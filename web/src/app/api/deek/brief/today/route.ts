/**
 * Proxy: GET /api/deek/brief/today
 *   → GET ${DEEK_API}/api/deek/brief/today?user=<session.email>
 *
 * Tenant scoping: ``user`` query param is derived from the JWT session
 * cookie, not the client. Toby and Jo share DEEK_USERS but each gets
 * their own brief because of this.
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
      `${DEEK_API_URL}/api/deek/brief/today?user=${encodeURIComponent(session.email)}`,
      {
        headers: { 'X-API-Key': DEEK_API_KEY },
        cache: 'no-store',
        signal: AbortSignal.timeout(15_000),
      },
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json({ error: 'deek_offline' }, { status: 502 })
  }
}
