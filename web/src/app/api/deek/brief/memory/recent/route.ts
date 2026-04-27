/**
 * Proxy: GET /api/deek/brief/memory/recent?limit=20
 *   → GET ${DEEK_API}/api/deek/brief/memory/recent?user=<session.email>&limit=N
 *
 * Returns the last N memory chunks written via brief replies, scoped
 * to the authenticated user's email.
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
  const limit = Math.min(
    Math.max(parseInt(url.searchParams.get('limit') || '20', 10) || 20, 1),
    100,
  )
  try {
    const res = await fetch(
      `${DEEK_API_URL}/api/deek/brief/memory/recent?user=${encodeURIComponent(session.email)}&limit=${limit}`,
      {
        headers: { 'X-API-Key': DEEK_API_KEY },
        cache: 'no-store',
        signal: AbortSignal.timeout(15_000),
      },
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json({ items: [], count: 0 }, { status: 502 })
  }
}
