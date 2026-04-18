/**
 * Auth middleware — gates /voice, /api/voice/*, /admin/*.
 *
 * Allows /voice/login and /api/voice/login through unauthenticated.
 *
 * Cheap cookie-presence check in Edge runtime. Route handlers then do
 * full JWT verification using jose + DEEK_JWT_SECRET.
 */
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const COOKIE_NAME = 'deek.session'

// Paths under the matched prefixes that should skip auth.
const PUBLIC_PATHS = new Set<string>([
  '/voice/login',
  '/api/voice/login',
  '/api/voice/logout',  // logout is idempotent — allow both authed and not
])

export const config = {
  matcher: [
    '/voice/:path*',
    '/api/voice/:path*',
    '/admin/:path*',
  ],
}

export function middleware(req: NextRequest) {
  const pathname = req.nextUrl.pathname

  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next()
  }

  const cookie = req.cookies.get(COOKIE_NAME)?.value
  if (cookie) {
    return NextResponse.next()
  }

  const isApi = pathname.startsWith('/api/')
  if (isApi) {
    return new NextResponse(
      JSON.stringify({ error: 'not_authenticated' }),
      { status: 401, headers: { 'content-type': 'application/json' } },
    )
  }

  // Build a callback URL using the public host (not internal Docker addr).
  const host = req.headers.get('host') || 'deek.nbnesigns.co.uk'
  const proto = req.headers.get('x-forwarded-proto') || 'https'
  const callbackUrl = `${proto}://${host}${pathname}${req.nextUrl.search || ''}`
  const loginUrl = new URL('/voice/login', `${proto}://${host}`)
  loginUrl.searchParams.set('callbackUrl', callbackUrl)
  return NextResponse.redirect(loginUrl)
}
