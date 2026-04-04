import { cookies } from 'next/headers'
import { NextRequest, NextResponse } from 'next/server'
import { cairnFetch } from '@/lib/api'
import { AUTH_COOKIE_NAME, isTokenExpired } from '@/lib/auth'

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const cookieStore = await cookies()
  const accessToken = cookieStore.get(AUTH_COOKIE_NAME)?.value
  if (!accessToken) return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })
  if (isTokenExpired(accessToken)) return NextResponse.json({ error: 'Token expired' }, { status: 401 })

  const { sessionId } = await params
  try {
    const res = await cairnFetch(`/projects/nbne/sessions/${sessionId}/archive`, {
      method: 'POST',
    })
    return NextResponse.json(await res.json(), { status: res.status })
  } catch {
    return NextResponse.json({ error: 'Cairn API unavailable' }, { status: 503 })
  }
}
