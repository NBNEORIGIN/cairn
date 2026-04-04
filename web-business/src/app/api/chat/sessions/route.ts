import { cookies } from 'next/headers'
import { NextRequest, NextResponse } from 'next/server'
import { cairnFetch } from '@/lib/api'
import { AUTH_COOKIE_NAME, isTokenExpired } from '@/lib/auth'

export async function GET(req: NextRequest) {
  const cookieStore = await cookies()
  const accessToken = cookieStore.get(AUTH_COOKIE_NAME)?.value

  if (!accessToken) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })
  }
  if (isTokenExpired(accessToken)) {
    return NextResponse.json({ error: 'Token expired' }, { status: 401 })
  }

  try {
    const cairnRes = await cairnFetch(
      '/projects/nbne/sessions',
      { cache: 'no-store' },
    )
    if (!cairnRes.ok) {
      return NextResponse.json({ sessions: [] }, { status: 200 })
    }
    const data = await cairnRes.json()
    return NextResponse.json(data)
  } catch {
    return NextResponse.json({ sessions: [] }, { status: 200 })
  }
}
