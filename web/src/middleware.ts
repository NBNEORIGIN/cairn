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
    '/',
    '/voice/:path*',
    '/api/voice/:path*',
    '/admin/:path*',
  ],
}

// Simple UA-based mobile detection. Edge runtime has no window.matchMedia,
// and User-Agent is good enough for "is this a phone?" — we fall back to
// showing the desktop UI if we're unsure.
const MOBILE_UA_RE = /Mobi|Android|iPhone|iPod|BlackBerry|Windows Phone/i

function isMobile(req: NextRequest): boolean {
  const ua = req.headers.get('user-agent') || ''
  return MOBILE_UA_RE.test(ua)
}

export function middleware(req: NextRequest) {
  const pathname = req.nextUrl.pathname

  // ── Mobile redirect: / → /voice ─────────────────────────────────
  // The desktop ChatWindow at / is a power-user interface. On phones
  // we send users to the mobile-first PWA. Users can still explicitly
  // visit /?desktop=1 to see the legacy page if they want.
  if (pathname === '/') {
    if (isMobile(req) && !req.nextUrl.searchParams.has('desktop')) {
      const url = req.nextUrl.clone()
      url.pathname = '/voice'
      url.search = ''
      return NextResponse.redirect(url)
    }
    return NextResponse.next()
  }

  // ── Auth gate for protected paths ──────────────────────────────
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
