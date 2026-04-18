/**
 * Auth middleware — gates /voice and /api/voice/*.
 *
 * The full session verification (JWE decrypt via jose) runs inside the
 * route handlers where Node runtime is available. The middleware here
 * does a CHEAP check: does the session cookie exist at all? If not,
 * redirect straight to CRM login. If yes, proceed and let the route
 * handler do full verification.
 *
 * This avoids running jose in the Edge runtime (which is possible but
 * requires the Web Crypto API and adds friction). Cheap gate + real
 * verification downstream is the standard Next.js pattern.
 */
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const SECURE_COOKIE = '__Secure-next-auth.session-token'
const PLAIN_COOKIE = 'next-auth.session-token'

const CRM_LOGIN_URL =
  process.env.CRM_LOGIN_URL || 'https://crm.nbnesigns.co.uk/login'

export const config = {
  matcher: [
    '/voice/:path*',
    '/api/voice/:path*',
    '/admin/:path*',
  ],
}

export function middleware(req: NextRequest) {
  const cookie =
    req.cookies.get(SECURE_COOKIE)?.value ||
    req.cookies.get(PLAIN_COOKIE)?.value

  if (cookie) {
    // Cookie present — proceed. Route handlers verify the JWT payload.
    return NextResponse.next()
  }

  // No session — redirect to CRM login for page requests, 401 for API.
  const isApi = req.nextUrl.pathname.startsWith('/api/')
  if (isApi) {
    return new NextResponse(
      JSON.stringify({ error: 'not_authenticated', login_url: CRM_LOGIN_URL }),
      { status: 401, headers: { 'content-type': 'application/json' } },
    )
  }

  const callbackUrl = req.nextUrl.href
  const loginUrl = `${CRM_LOGIN_URL}?callbackUrl=${encodeURIComponent(callbackUrl)}`
  return NextResponse.redirect(loginUrl)
}
