/**
 * Proxy for GET /api/deek/voice/metrics — admin-only telemetry dashboard.
 *
 * Restricted to ADMIN and PM roles to avoid exposing voice transcripts
 * (which may contain sensitive business data) to STAFF/READONLY users.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from '@/lib/auth'

const DEEK_API_URL =
  process.env.DEEK_API_URL ||
  process.env.CLAW_API_URL ||
  'http://localhost:8765'
const DEEK_API_KEY =
  process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || ''

const ADMIN_ROLES = new Set(['ADMIN', 'PM'])

export async function GET(_req: NextRequest) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json(
      { error: 'not_authenticated' },
      { status: 401 },
    )
  }
  if (!ADMIN_ROLES.has(session.role)) {
    return NextResponse.json(
      { error: 'forbidden', reason: 'Admin only' },
      { status: 403 },
    )
  }

  try {
    const res = await fetch(`${DEEK_API_URL}/api/deek/voice/metrics`, {
      headers: { 'X-API-Key': DEEK_API_KEY },
      signal: AbortSignal.timeout(10_000),
      cache: 'no-store',
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json({ error: 'Deek offline' }, { status: 502 })
  }
}
