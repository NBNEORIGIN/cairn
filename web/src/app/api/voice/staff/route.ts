/**
 * Proxy: GET /api/voice/staff — list all staff profiles.
 * Admin/PM only (ADMIN role on the Deek session, which corresponds to
 * director-tier per the location ACL).
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

export const dynamic = 'force-dynamic'

export async function GET(_req: NextRequest) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json({ error: 'not_authenticated' }, { status: 401 })
  }
  if (!ADMIN_ROLES.has(session.role)) {
    return NextResponse.json({ error: 'forbidden', reason: 'admin only' }, { status: 403 })
  }
  try {
    const res = await fetch(`${DEEK_API_URL}/api/deek/staff`, {
      headers: { 'X-API-Key': DEEK_API_KEY },
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json({ profiles: [] }, { status: 502 })
  }
}

export async function PUT(req: NextRequest) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json({ error: 'not_authenticated' }, { status: 401 })
  }
  if (!ADMIN_ROLES.has(session.role)) {
    return NextResponse.json({ error: 'forbidden' }, { status: 403 })
  }
  const body = await req.json().catch(() => null)
  if (!body) return NextResponse.json({ error: 'invalid_json' }, { status: 400 })
  try {
    const res = await fetch(`${DEEK_API_URL}/api/deek/staff`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': DEEK_API_KEY },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10_000),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err: any) {
    return NextResponse.json({ error: 'Deek offline', detail: err?.message }, { status: 502 })
  }
}
