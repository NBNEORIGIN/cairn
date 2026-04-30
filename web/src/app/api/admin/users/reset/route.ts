/**
 * Proxy: POST /api/admin/users/reset — admin password reset
 *
 * ADMIN-only. Body: { target_email, new_password }. The admin's email
 * comes from the JWT cookie; the client doesn't choose `by_email`.
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
  if (session.role !== 'ADMIN') {
    return NextResponse.json({ error: 'forbidden' }, { status: 403 })
  }

  let body: any
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'invalid_json' }, { status: 400 })
  }
  const targetEmail = String(body?.target_email || '').trim().toLowerCase()
  const newPassword = String(body?.new_password || '')
  if (!targetEmail || !newPassword) {
    return NextResponse.json(
      { error: 'target_email_and_new_password_required' },
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
    const res = await fetch(`${DEEK_API_URL}/api/deek/users/admin/reset`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': DEEK_API_KEY,
      },
      body: JSON.stringify({
        target_email: targetEmail,
        new_password: newPassword,
        by_email: session.email,
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
