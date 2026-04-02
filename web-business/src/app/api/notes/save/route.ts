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

  let body: { title?: string; content?: string }
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'Invalid request body' }, { status: 400 })
  }

  const { title, content } = body
  if (!content) {
    return NextResponse.json({ error: 'No content provided' }, { status: 400 })
  }

  const query = `Note: ${title ?? 'Untitled note'}`

  try {
    const cairnRes = await cairnFetch('/memory/write', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project: 'nbne',
        query,
        decision: content,
        outcome: 'committed',
        model: 'manual',
        files_changed: [],
      }),
    })

    if (!cairnRes.ok) {
      return NextResponse.json({ error: 'Failed to save note' }, { status: 502 })
    }
  } catch {
    return NextResponse.json({ error: 'Memory service unavailable' }, { status: 503 })
  }

  return NextResponse.json({ success: true })
}
