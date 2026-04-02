import { cookies } from 'next/headers'
import { NextRequest, NextResponse } from 'next/server'
import { cairnFetch } from '@/lib/api'
import { AUTH_COOKIE_NAME, isTokenExpired } from '@/lib/auth'

export async function POST(req: NextRequest) {
  const cookieStore = await cookies()
  const accessToken = cookieStore.get(AUTH_COOKIE_NAME)?.value

  if (!accessToken) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 })
  }
  if (isTokenExpired(accessToken)) {
    return NextResponse.json({ error: 'Token expired' }, { status: 401 })
  }

  let body: { text?: string; title?: string }
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'Invalid request body' }, { status: 400 })
  }

  const { text, title } = body
  if (!text) {
    return NextResponse.json({ error: 'No text provided' }, { status: 400 })
  }

  const date = new Date().toISOString().slice(0, 10)
  const query = title ?? `Voice memo - ${date}`

  let cairnRes: Response
  try {
    cairnRes = await cairnFetch('/memory/write', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project: 'nbne',
        query,
        decision: text,
        outcome: 'committed',
        model: 'whisper-1',
        files_changed: [],
      }),
    })
  } catch {
    return NextResponse.json({ error: 'Memory service unavailable' }, { status: 503 })
  }

  if (!cairnRes.ok) {
    return NextResponse.json({ error: 'Failed to save to memory' }, { status: 502 })
  }

  const data = await cairnRes.json().catch(() => ({}))
  return NextResponse.json({ success: true, id: data.id ?? null })
}
