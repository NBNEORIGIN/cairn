/**
 * GET /api/voice/me — returns the current user + allowed locations.
 * Used by /voice on mount to render only permitted locations.
 */
import { NextResponse } from 'next/server'
import { getServerSession, canAccessLocation, LOGIN_PATH } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const ALL_LOCATIONS = ['workshop', 'office', 'home'] as const

export async function GET(req: Request) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json(
      {
        authenticated: false,
        login_url: LOGIN_PATH,
      },
      { status: 401 },
    )
  }
  const allowed = ALL_LOCATIONS.filter(loc => canAccessLocation(session, loc))
  return NextResponse.json({
    authenticated: true,
    user: {
      email: session.email,
      name: session.name,
      role: session.role,
    },
    allowed_locations: allowed,
  })
}
