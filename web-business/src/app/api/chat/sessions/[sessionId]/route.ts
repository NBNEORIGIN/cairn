import { cookies } from 'next/headers'
import { NextRequest, NextResponse } from 'next/server'
import { cairnFetch } from '@/lib/api'
import { AUTH_COOKIE_NAME, isTokenExpired } from '@/lib/auth'

function checkAuth(cookieStore: Awaited<ReturnType<typeof cookies>>) {
  const accessToken = cookieStore.get(AUTH_COOKIE_NAME)?.value
  if (!accessToken) return { error: 'Not authenticated', status: 401 }
  if (isTokenExpired(accessToken)) return { error: 'Token expired', status: 401 }
  return null
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const cookieStore = await cookies()
  const authErr = checkAuth(cookieStore)
  if (authErr) return NextResponse.json(authErr, { status: authErr.status })

  const { sessionId } = await params
  try {
    const res = await cairnFetch(`/projects/nbne/sessions/${sessionId}`, { cache: 'no-store' })
    if (!res.ok) return NextResponse.json({ error: 'Not found' }, { status: 404 })
    return NextResponse.json(await res.json())
  } catch {
    return NextResponse.json({ error: 'Deek API unavailable' }, { status: 503 })
  }
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const cookieStore = await cookies()
  const authErr = checkAuth(cookieStore)
  if (authErr) return NextResponse.json(authErr, { status: authErr.status })

  const { sessionId } = await params
  const body = await req.json()
  try {
    const res = await cairnFetch(`/projects/nbne/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return NextResponse.json(await res.json(), { status: res.status })
  } catch {
    return NextResponse.json({ error: 'Deek API unavailable' }, { status: 503 })
  }
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const cookieStore = await cookies()
  const authErr = checkAuth(cookieStore)
  if (authErr) return NextResponse.json(authErr, { status: authErr.status })

  const { sessionId } = await params
  try {
    const res = await cairnFetch(`/projects/nbne/sessions/${sessionId}`, { method: 'DELETE' })
    return NextResponse.json(await res.json(), { status: res.status })
  } catch {
    return NextResponse.json({ error: 'Deek API unavailable' }, { status: 503 })
  }
}
