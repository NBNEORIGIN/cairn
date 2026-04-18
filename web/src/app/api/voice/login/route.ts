/**
 * POST /api/voice/login — verify credentials against DEEK_USERS env var,
 * issue a HS256 JWT cookie on success.
 *
 * Body: { email, password }
 * Returns: 200 + session info on success, 401 on bad creds.
 */
import { NextResponse } from 'next/server'
import {
  verifyCredentials,
  issueSessionToken,
  sessionCookieOptions,
} from '@/lib/auth'

export const dynamic = 'force-dynamic'

export async function POST(req: Request) {
  let body: any
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'invalid_json' }, { status: 400 })
  }

  const email = String(body?.email || '').trim()
  const password = String(body?.password || '')
  if (!email || !password) {
    return NextResponse.json(
      { error: 'email and password required' },
      { status: 400 },
    )
  }

  const user = await verifyCredentials(email, password)
  if (!user) {
    return NextResponse.json(
      { error: 'Invalid email or password.' },
      { status: 401 },
    )
  }

  const token = await issueSessionToken(user)
  const opts = sessionCookieOptions()
  const res = NextResponse.json({
    ok: true,
    user: { email: user.email, name: user.name, role: user.role },
  })
  res.cookies.set(opts.name, token, {
    httpOnly: opts.httpOnly,
    sameSite: opts.sameSite,
    path: opts.path,
    secure: opts.secure,
    maxAge: opts.maxAge,
  })
  return res
}
