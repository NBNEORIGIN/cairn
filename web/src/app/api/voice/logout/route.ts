/**
 * POST /api/voice/logout — clear the deek.session cookie.
 */
import { NextResponse } from 'next/server'
import { sessionCookieOptions } from '@/lib/auth'

export const dynamic = 'force-dynamic'

export async function POST() {
  const opts = sessionCookieOptions(0)
  const res = NextResponse.json({ ok: true })
  res.cookies.set(opts.name, '', {
    httpOnly: opts.httpOnly,
    sameSite: opts.sameSite,
    path: opts.path,
    secure: opts.secure,
    maxAge: 0,
  })
  return res
}
