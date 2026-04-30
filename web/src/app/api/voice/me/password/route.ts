/**
 * Proxy: POST /api/voice/me/password
 *   → POST ${DEEK_API}/api/deek/users/me/password
 *
 * Self-service password change. Body: { old_password, new_password }.
 * The user's email is taken from the JWT cookie — never trust the client.
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
  const oldPassword = String(body?.old_password || '')
  const newPassword = String(body?.new_password || '')
  if (!oldPassword || !newPassword) {
    return NextResponse.json(
      { error: 'old_password_and_new_password_required' },
      { status: 400 },
    )
  }
  if (newPassword.length < 8) {
    return NextResponse.json(
      { error: 'new password must be at least 8 characters' },
      { status: 400 },
    )
  }

  try {
    const res = await fetch(`${DEEK_API_URL}/api/deek/users/me/password`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': DEEK_API_KEY,
      },
      body: JSON.stringify({
        email: session.email,
        old_password: oldPassword,
        new_password: newPassword,
      }),
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json({ error: 'upstream_failed' }, { status: 502 })
  }
}
