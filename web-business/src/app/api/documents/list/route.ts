import { cookies } from 'next/headers'
import { NextRequest, NextResponse } from 'next/server'
import { cairnFetch } from '@/lib/api'
import { AUTH_COOKIE_NAME, isTokenExpired } from '@/lib/auth'

export async function GET(_req: NextRequest) {
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
      '/memory/retrieve?query=Document&project=nbne&limit=20',
      { cache: 'no-store' }
    )
    if (!cairnRes.ok) {
      return NextResponse.json([], { status: 200 })
    }
    const data = await cairnRes.json()
    // Deek returns { results: [...] } or an array
    const results = Array.isArray(data) ? data : data.results ?? []
    return NextResponse.json(results)
  } catch {
    return NextResponse.json([], { status: 200 })
  }
}
