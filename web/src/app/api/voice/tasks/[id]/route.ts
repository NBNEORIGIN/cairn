/**
 * Proxy: PATCH /api/voice/tasks/{id} — mark done / update task.
 */
import { NextRequest, NextResponse } from 'next/server'
import { getServerSession } from '@/lib/auth'

const DEEK_API_URL =
  process.env.DEEK_API_URL ||
  process.env.CLAW_API_URL ||
  'http://localhost:8765'
const DEEK_API_KEY =
  process.env.DEEK_API_KEY || process.env.CLAW_API_KEY || ''

export const dynamic = 'force-dynamic'

export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const session = await getServerSession()
  if (!session) {
    return NextResponse.json({ error: 'not_authenticated' }, { status: 401 })
  }
  const body = await req.json().catch(() => null)
  if (!body) return NextResponse.json({ error: 'invalid_json' }, { status: 400 })
  try {
    const res = await fetch(
      `${DEEK_API_URL}/api/deek/tasks/${encodeURIComponent(params.id)}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': DEEK_API_KEY },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(10_000),
      },
    )
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err: any) {
    return NextResponse.json({ error: 'Deek offline', detail: err?.message }, { status: 502 })
  }
}
