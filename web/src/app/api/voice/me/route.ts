/**
 * GET /api/voice/me — return the current user's session + allowed locations.
 *
 * Used by the /voice PWA on mount to (a) confirm auth, (b) render only
 * the locations this user is allowed to see.
 */
import { NextResponse } from 'next/server'
import { getServerSession, canAccessLocation, buildLoginUrl } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const ALL_LOCATIONS = ['workshop', 'office', 'home'] as const

export async function GET(req: Request) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json(
      {
        authenticated: false,
        login_url: buildLoginUrl(req.url),
      },
      { status: 401 },
    )
  }
  const allowed = ALL_LOCATIONS.filter(loc => canAccessLocation(session, loc))
  return NextResponse.json({
    authenticated: true,
    user: {
      id: session.id,
      email: session.email,
      name: session.name,
      role: session.role,
    },
    allowed_locations: allowed,
  })
}
